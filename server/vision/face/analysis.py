"""Detailed facial motion and reusable upper-body joints; no camera/network on import."""
from collections import deque
import math
import numpy as np
from config import settings
from server.vision.face.eyes import eye_geometry

EMOTIONS = ("neutral","happy","surprised","sad","angry","disgust","fear","contempt")


def _valid_cues(cues):
    return {key:float(np.clip(value,0,1)) for key,value in (cues or {}).items()
            if isinstance(value,(int,float,np.number)) and np.isfinite(value)}


def _distribution(probs):
    if probs is None:
        return None
    raw = np.asarray(probs,dtype=float).reshape(-1)
    if raw.size != len(EMOTIONS) or not np.isfinite(raw).all() or np.any(raw < 0) or raw.sum() <= 0:
        return None
    return raw/raw.sum()


class FaceDetails:
    def __init__(self, path, *, video=True):
        import mediapipe as mp
        self.mp = mp
        self.video = video
        self.timestamp = -1
        self.model = mp.tasks.vision.FaceLandmarker.create_from_options(
            mp.tasks.vision.FaceLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=str(path)),
                running_mode=mp.tasks.vision.RunningMode.VIDEO if video else mp.tasks.vision.RunningMode.IMAGE,
                num_faces=1, min_face_detection_confidence=.6,
                min_face_presence_confidence=.6, min_tracking_confidence=.6,
                output_face_blendshapes=True, output_facial_transformation_matrixes=True))

    def close(self):
        self.model.close()

    def detect(self, frame, box, now):
        import cv2
        self.timestamp = max(self.timestamp+1,int(now*1000))
        image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB,
                              data=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB))
        result = self.model.detect_for_video(image,self.timestamp) if self.video else self.model.detect(image)
        if not result.face_landmarks:
            return None
        nose = result.face_landmarks[0][1]
        x,y,w,h = box
        if not (x <= nose.x*frame.shape[1] <= x+w and y <= nose.y*frame.shape[0] <= y+h):
            return None
        scores = {v.category_name:float(v.score) for v in result.face_blendshapes[0]} if result.face_blendshapes else {}
        def pair(name):
            return (scores.get(name+"Left",0.)+scores.get(name+"Right",0.))/2
        smile_left,smile_right = scores.get("mouthSmileLeft",0.),scores.get("mouthSmileRight",0.)
        cues = dict(brow_down=pair("browDown"),brow_inner_up=scores.get("browInnerUp",0.),
                    eye_squint=pair("eyeSquint"),mouth_frown=pair("mouthFrown"),
                    mouth_press=pair("mouthPress"),smile=(smile_left+smile_right)/2,
                    smile_left=smile_left,smile_right=smile_right,
                    jaw_open=scores.get("jawOpen",0.),eye_wide=pair("eyeWide"),
                    brow_outer_up=pair("browOuterUp"),mouth_stretch=pair("mouthStretch"),
                    nose_sneer=pair("noseSneer"),upper_lip_raise=pair("mouthUpperUp"))
        angles = None
        if result.facial_transformation_matrixes:
            matrix = np.asarray(result.facial_transformation_matrixes[0])[:3,:3]
            if np.isfinite(matrix).all():
                u,_,vt = np.linalg.svd(matrix)
                rotation = u@vt
                if np.linalg.det(rotation) > 0:
                    pitch,yaw,roll = cv2.RQDecomp3x3(rotation)[0]
                    if max(abs(pitch),abs(yaw),abs(roll)) < 65:
                        angles = dict(pitch=float(pitch),yaw=float(yaw),roll=float(roll))
        eyes = eye_geometry(result.face_landmarks[0],frame.shape)
        if eyes is not None:
            eyes.update(blink_left=scores.get("eyeBlinkLeft",0.),blink_right=scores.get("eyeBlinkRight",0.))
        return dict(angles=angles,cues=cues,eyes=eyes)


def expression_intensities(cues):
    """Independent geometric activation scores, not probabilities summing to one."""
    c = _valid_cues(cues)
    smile_left,smile_right = c.get("smile_left",0),c.get("smile_right",0)
    raised_brows = max(c.get("brow_inner_up",0),c.get("brow_outer_up",0))
    return dict(happy=float(c.get("smile",0)),
        surprised=float(min(c.get("jaw_open",0),max(c.get("eye_wide",0),c.get("brow_outer_up",0)))),
        angry=float(math.sqrt(c.get("brow_down",0)*max(c.get("eye_squint",0),c.get("mouth_press",0)))),
        sad=float(math.sqrt(c.get("brow_inner_up",0)*c.get("mouth_frown",0))),
        disgust=float(math.sqrt(c.get("nose_sneer",0)*c.get("upper_lip_raise",0))),
        fear=float((raised_brows*c.get("eye_wide",0)*max(c.get("jaw_open",0),c.get("mouth_stretch",0)))**(1/3)),
        contempt=float(math.sqrt(max(smile_left,smile_right)*abs(smile_left-smile_right))))


def _supported_expressions(cues):
    """Require combinations of movements; a single brow/jaw cue is insufficient."""
    c = _valid_cues(cues)
    left,right = c.get("smile_left",0),c.get("smile_right",0)
    asymmetric = max(left,right) >= .35 and abs(left-right) >= .22
    return dict(
        happy=c.get("smile",0) >= .25 and not asymmetric,
        surprised=c.get("jaw_open",0) >= .18 and max(c.get("eye_wide",0),c.get("brow_outer_up",0)) >= .18,
        angry=c.get("brow_down",0) >= .30 and max(c.get("eye_squint",0),c.get("mouth_press",0)) >= .12,
        sad=c.get("brow_inner_up",0) >= .25 and c.get("mouth_frown",0) >= .12,
        disgust=c.get("nose_sneer",0) >= .25 and c.get("upper_lip_raise",0) >= .15,
        fear=max(c.get("brow_inner_up",0),c.get("brow_outer_up",0)) >= .25
             and c.get("eye_wide",0) >= .18 and max(c.get("jaw_open",0),c.get("mouth_stretch",0)) >= .18,
        contempt=asymmetric)


def combined_emotion_scores(probs, cues):
    """Normalized evidence ranking, not a calibrated probability of emotion."""
    raw = _distribution(probs)
    if raw is None:
        return {}
    intensities = expression_intensities(cues)
    supported = _supported_expressions(cues)
    scores = .75*raw
    activation = max((intensities[name] for name,valid in supported.items() if valid),default=0.)
    # FER+ frequently absorbs subtle expressions into neutral. Reduce neutral only
    # when independent facial motion exists, then add class-specific evidence.
    scores[0] *= max(.35,1-.65*activation)
    for index,name in enumerate(EMOTIONS[1:],1):
        if supported[name]:
            scores[index] += .25*intensities[name]
    scores /= scores.sum()
    return {name:float(value) for name,value in zip(EMOTIONS,scores)}


def expression_decision(probs, cues):
    """Return candidate, required dwell and source, without temporal confirmation."""
    label,count,source = emotion_candidate(probs,cues)
    if source == "fer" and label != "neutral":
        return label,.30,source
    if source == "fer+landmarks":
        return label,.45,source
    c = _valid_cues(cues)
    strengths = expression_intensities(c)
    supported = _supported_expressions(c)
    thresholds = dict(happy=.45,surprised=.30,angry=.30,sad=.24,disgust=.24,fear=.20,contempt=.25)
    supported["angry"] &= c.get("brow_down",0) >= .42
    supported["sad"] &= c.get("brow_inner_up",0) >= .30
    # Fear and surprise share raised brows/open eyes. Stretching the lips
    # supplies the additional evidence needed for a landmarks-only fear label.
    supported["fear"] &= c.get("mouth_stretch",0) >= .25 and c.get("mouth_stretch",0) >= .65*c.get("jaw_open",0)
    if supported["fear"]:
        supported["surprised"] = False
    candidates = sorted(((strengths[name]/thresholds[name],name) for name in thresholds
                         if supported[name] and strengths[name] >= thresholds[name]),reverse=True)
    if candidates:
        # Competing expressions must separate; dictionary/if order cannot decide.
        if len(candidates) == 1 or candidates[0][0]-candidates[1][0] >= .15:
            name = candidates[0][1]
            dwell = .18 if name in ("happy","surprised") else .55 if name in ("fear","disgust") else .65
            return name,dwell,"landmarks"
        return "unknown",.30,"uncertain"
    if label == "neutral":
        return label,settings.VISION_EMOTION_NEUTRAL_DWELL,source
    return label,.65 if count == 5 else .30,source


class ExpressionState:
    def __init__(self): self.reset()
    def reset(self):
        self.value,self.pending = "unknown","unknown"
        self.since,self.confirmed = 0.,-float("inf")
        self.source = "uncertain"
        self.confidence = 0.
        self.last_update = None
        self.pending_source = "uncertain"
        self.observations = 0
        self.observed_at = None

    def update(self,probs,cues,now,*,fer_fresh=True):
        if self.last_update is not None and (now < self.last_update or now-self.last_update > settings.VISION_EMOTION_STALE_SEC):
            self.reset()
        self.last_update = now
        probs = _distribution(probs)
        intensities = expression_intensities(cues)
        label,dwell,source = expression_decision(probs,cues)
        if label != self.pending or source != self.pending_source:
            self.pending,self.since = label,now
            self.pending_source = source
            self.observations,self.observed_at = 0,None
        # Cached FER probabilities may be displayed, but only a new inference
        # can confirm or extend a FER-based label. Landmarks are sampled each frame.
        fresh = source == "landmarks" or fer_fresh
        if label != "unknown" and fresh and now != self.observed_at:
            if self.observations == 0:
                self.since = now
            self.observations += 1
            self.observed_at = now
        if label != "unknown" and fresh and self.observations >= 2 and now-self.since >= dwell:
            self.value,self.confirmed,self.source = label,now,source
            self.confidence = intensities[label] if source == "landmarks" else float(probs[EMOTIONS.index(label)])
        # Allow a brief neutral interruption without erasing a confirmed expression.
        # Cached FER still cannot confirm or refresh either label.
        expiry = settings.VISION_EMOTION_NEUTRAL_DWELL+.3 if label == "neutral" and self.value not in ("neutral","unknown") else .6
        if now-self.confirmed > expiry:
            self.value,self.source = "unknown","uncertain"
            self.confidence = 0.
        return dict(emotion=self.value,emotion_source=self.source,emotion_confidence=self.confidence,
                    emotion_scores=combined_emotion_scores(probs,cues),expression_intensities=intensities)


class HeadMotion:
    """Recognize motion gestures and stable head poses from face rotation."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.history = deque()
        self.smoothed = None
        self.last_event = -float("inf")
        self.pose_candidate = "unknown"
        self.pose_since = 0.

    def update(self, angles, now):
        if angles is None or not all(np.isfinite(angles[k]) for k in ("pitch","yaw","roll")):
            self.reset()
            return "unknown"
        if self.history and now-self.history[-1][0] > .7:
            self.reset()
        raw = np.array([angles["pitch"],angles["yaw"],angles["roll"]])
        self.smoothed = raw if self.smoothed is None else .65*raw+.35*self.smoothed
        self.history.append((now,self.smoothed.copy()))
        while self.history and now-self.history[0][0] > 1.8:
            self.history.popleft()
        if len(self.history) < 4 or now-self.history[0][0] < .3 or now-self.last_event < .8:
            return "unknown"
        samples = np.array([v for _,v in self.history])
        ranges = np.ptp(samples,axis=0)
        for axis,label,minimum in ((0,"head_nod",settings.VISION_HEAD_NOD_DEGREES),
                                   (1,"head_shake",settings.VISION_HEAD_SHAKE_DEGREES)):
            if ranges[axis] < minimum or ranges[axis] < ranges[1-axis]*1.2 or ranges[2] > ranges[axis]:
                continue
            values = samples[:,axis]
            for sign in (1,-1):
                directed = values*sign
                peak = int(np.argmax(directed))
                if 0 < peak < len(values)-1 and directed[peak]-directed[0] >= minimum and directed[peak]-directed[-1] >= minimum*.5:
                    self.last_event = now
                    self.history.clear()
                    return label
        # A pose must settle before it is published. This prevents a normal nod or
        # shake on its way to the peak from being mislabeled as a held posture.
        recent = samples[-4:]
        settled = len(recent) == 4 and np.max(np.ptp(recent,axis=0)) <= 2.5
        pitch,yaw,roll = self.smoothed
        candidate = "unknown"
        if settled:
            if abs(roll) >= settings.VISION_HEAD_TILT_DEGREES and abs(roll) > max(abs(pitch),abs(yaw))*.75:
                candidate = "head_tilt_right" if roll > 0 else "head_tilt_left"
            elif abs(yaw) >= settings.VISION_HEAD_TURN_DEGREES and abs(yaw) > abs(pitch)*1.15:
                candidate = "head_turn_right" if yaw > 0 else "head_turn_left"
            elif abs(pitch) >= settings.VISION_HEAD_LOOK_DEGREES and abs(pitch) > abs(yaw)*1.15:
                candidate = "head_down" if pitch > 0 else "head_up"
        if candidate != self.pose_candidate:
            self.pose_candidate,self.pose_since = candidate,now
        return candidate if candidate != "unknown" and now-self.pose_since >= .25 else "unknown"


def emotion_candidate(probs, cues):
    """Keep FER scores intact; geometry only corroborates subtle candidates."""
    probs = _distribution(probs)
    if probs is None:
        return "unknown",3,"uncertain"
    order = np.argsort(probs)
    top,runner = int(order[-1]),int(order[-2])
    decisive = probs[top] >= settings.VISION_EMOTION_THRESHOLD and probs[top]-probs[runner] >= settings.VISION_EMOTION_MARGIN
    if decisive and top != 0:
        return EMOTIONS[top],3,"fer"
    supported = _supported_expressions(cues)
    intensities = expression_intensities(cues)
    candidates = sorted(((probs[index]+.25*intensities[name],name)
                         for index,name in enumerate(EMOTIONS[1:],1)
                         if supported[name] and top in (0,index) and probs[index] >= .12
                         and probs[index] >= probs[top]*.28),reverse=True)
    if candidates:
        if len(candidates) == 1 or candidates[0][0]-candidates[1][0] >= .04:
            return candidates[0][1],5,"fer+landmarks"
        return "unknown",3,"uncertain"
    if decisive:
        return EMOTIONS[top],3,"fer"
    return "unknown",3,"uncertain"
