"""Detailed facial motion and reusable upper-body joints; no camera/network on import."""
from collections import deque
import math
import numpy as np
from config import settings
from server.vision_signals import eye_geometry


class FaceDetails:
    def __init__(self, path):
        import mediapipe as mp
        self.mp = mp
        self.timestamp = -1
        self.model = mp.tasks.vision.FaceLandmarker.create_from_options(
            mp.tasks.vision.FaceLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=str(path)),
                running_mode=mp.tasks.vision.RunningMode.VIDEO,
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
        result = self.model.detect_for_video(image,self.timestamp)
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
    c = cues or {}
    smile_left,smile_right = c.get("smile_left",0),c.get("smile_right",0)
    raised_brows = max(c.get("brow_inner_up",0),c.get("brow_outer_up",0))
    return dict(happy=float(c.get("smile",0)),
        surprised=float(min(c.get("jaw_open",0),max(c.get("eye_wide",0),c.get("brow_outer_up",0)))),
        angry=float(math.sqrt(c.get("brow_down",0)*max(c.get("eye_squint",0),c.get("mouth_press",0)))),
        sad=float(math.sqrt(c.get("brow_inner_up",0)*c.get("mouth_frown",0))),
        disgust=float(math.sqrt(c.get("nose_sneer",0)*c.get("upper_lip_raise",0))),
        fear=float((raised_brows*c.get("eye_wide",0)*max(c.get("jaw_open",0),c.get("mouth_stretch",0)))**(1/3)),
        contempt=float(math.sqrt(max(smile_left,smile_right)*abs(smile_left-smile_right))))


def combined_emotion_scores(probs, cues):
    """Fuse FER+ distribution and independent landmarks into a normalized ranking."""
    labels = ("neutral","happy","surprised","sad","angry","disgust","fear","contempt")
    if probs is None:
        return {}
    raw = np.clip(np.asarray(probs,dtype=float).reshape(-1),0,1)
    if raw.size != len(labels) or not np.isfinite(raw).all() or raw.sum() <= 0:
        return {}
    raw /= raw.sum()
    intensities = expression_intensities(cues)
    scores = .75*raw
    activation = max(intensities.values(),default=0.)
    # FER+ frequently absorbs subtle expressions into neutral. Reduce neutral only
    # when independent facial motion exists, then add class-specific evidence.
    scores[0] *= max(.35,1-.65*activation)
    for index,name in enumerate(labels[1:],1):
        scores[index] += .25*np.clip(intensities.get(name,0.),0,1)
    scores /= scores.sum()
    return {name:float(value) for name,value in zip(labels,scores)}


class ExpressionState:
    def __init__(self): self.reset()
    def reset(self):
        self.value,self.pending = "unknown","unknown"
        self.since,self.confirmed = 0.,-float("inf")
        self.source = "uncertain"

    def update(self,probs,cues,now):
        intensities = expression_intensities(cues)
        model_label,count,model_source = emotion_candidate(probs,cues) if probs is not None else ("unknown",3,"uncertain")
        # Trust a decisive non-neutral FER result. Geometric cues primarily recover
        # expressions that FER+ incorrectly collapses into its dominant neutral class.
        if model_source == "fer" and model_label != "neutral":
            label,dwell,source = model_label,.30,model_source
        elif model_source == "fer+landmarks":
            label,dwell,source = model_label,.45,model_source
        elif intensities["happy"] >= .45:
            label,dwell,source = "happy",.18,"landmarks"
        elif intensities["surprised"] >= .30:
            label,dwell,source = "surprised",.18,"landmarks"
        elif intensities["angry"] >= .30 and (cues or {}).get("brow_down",0) >= .42:
            label,dwell,source = "angry",.65,"landmarks"
        elif intensities["sad"] >= .24 and (cues or {}).get("brow_inner_up",0) >= .30:
            label,dwell,source = "sad",.65,"landmarks"
        elif intensities["disgust"] >= .24:
            label,dwell,source = "disgust",.55,"landmarks"
        elif intensities["fear"] >= .20:
            label,dwell,source = "fear",.55,"landmarks"
        elif intensities["contempt"] >= .25:
            label,dwell,source = "contempt",.65,"landmarks"
        elif probs is not None:
            label,source = model_label,model_source
            dwell = .65 if count == 5 else .30
        else:
            label,dwell,source = "unknown",.30,"uncertain"
        if label != self.pending:
            self.pending,self.since = label,now
        if label != "unknown" and now-self.since >= dwell:
            self.value,self.confirmed,self.source = label,now,source
        elif now-self.confirmed > .6:
            self.value,self.source = "unknown","uncertain"
        labels = ("neutral","happy","surprised","sad","angry","disgust","fear","contempt")
        score = intensities.get(self.value,0.) if self.source == "landmarks" else float(probs[labels.index(self.value)]) if probs is not None and self.value in labels else 0.
        return dict(emotion=self.value,emotion_source=self.source,emotion_confidence=score,
                    emotion_scores=combined_emotion_scores(probs,cues),expression_intensities=intensities)


class HeadMotion:
    """Recognize an out-and-back rotation; a one-way turn is not a gesture."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.history = deque()
        self.smoothed = None
        self.last_event = -float("inf")

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
        return "unknown"


def emotion_candidate(probs, cues):
    """Keep FER scores intact; geometry only corroborates subtle candidates."""
    labels = ("neutral","happy","surprised","sad","angry","disgust","fear","contempt")
    order = np.argsort(probs)
    top,runner = int(order[-1]),int(order[-2])
    decisive = probs[top] >= settings.VISION_EMOTION_THRESHOLD and probs[top]-probs[runner] >= settings.VISION_EMOTION_MARGIN
    if decisive and top != 0:
        return labels[top],3,"fer"
    cues = cues or {}
    angry = cues.get("brow_down",0) >= .3 and max(cues.get("eye_squint",0),cues.get("mouth_press",0)) >= .12
    sad = cues.get("brow_inner_up",0) >= .25 and cues.get("mouth_frown",0) >= .12
    disgust = cues.get("nose_sneer",0) >= .25 and cues.get("upper_lip_raise",0) >= .15
    fear = (max(cues.get("brow_inner_up",0),cues.get("brow_outer_up",0)) >= .25
            and cues.get("eye_wide",0) >= .18
            and max(cues.get("jaw_open",0),cues.get("mouth_stretch",0)) >= .18)
    smile_left,smile_right = cues.get("smile_left",0),cues.get("smile_right",0)
    contempt = max(smile_left,smile_right) >= .35 and abs(smile_left-smile_right) >= .22
    for index,supported in ((3,sad),(4,angry),(5,disgust),(6,fear),(7,contempt)):
        if supported and top in (0,index) and index in (top,runner) and probs[index] >= .12 and probs[index] >= probs[top]*.28:
            return labels[index],5,"fer+landmarks"
    if decisive:
        return labels[top],3,"fer"
    return "unknown",3,"uncertain"


JOINT_NAMES = {5:"left_shoulder",6:"right_shoulder",7:"left_elbow",8:"right_elbow",9:"left_wrist",10:"right_wrist"}
ARM_EDGES = (("left_shoulder","left_elbow"),("left_elbow","left_wrist"),
             ("right_shoulder","right_elbow"),("right_elbow","right_wrist"),
             ("left_shoulder","right_shoulder"))


def upper_body(points, shape):
    """Normalized image coordinates, visibility and 2D elbow angles."""
    p = np.asarray(points)
    if p.shape != (17,3) or not np.isfinite(p).all():
        return {},{}
    height,width = shape[:2]
    joints = {}
    for index,name in JOINT_NAMES.items():
        x,y,confidence = map(float,p[index])
        visible = confidence >= settings.VISION_KEYPOINT_THRESHOLD and 0 <= x < width and 0 <= y < height
        joints[name] = dict(x=round(x/width,5) if visible else None,
                            y=round(y/height,5) if visible else None,
                            confidence=round(confidence,3),visible=visible)
    angles = {}
    for side,indices in (("left",(5,7,9)),("right",(6,8,10))):
        angles[side] = None
        if all(joints[JOINT_NAMES[i]]["visible"] for i in indices):
            shoulder,elbow,wrist = p[list(indices),:2]
            a,b = shoulder-elbow,wrist-elbow
            norm = np.linalg.norm(a)*np.linalg.norm(b)
            if norm > 1:
                angles[side] = round(math.degrees(math.acos(float(np.clip(np.dot(a,b)/norm,-1,1)))),1)
    return joints,angles
