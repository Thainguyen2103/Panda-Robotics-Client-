"""Vision inference engine; importing it opens no camera or network connection."""
import logging
import time

import numpy as np
try:
    import cv2
except ImportError:
    cv2 = None

from config import settings
from server.vision.body.gestures import ArmGestures
from server.vision.body.pose import upper_body
from server.vision.face.analysis import FaceDetails, HeadMotion, ExpressionState
from server.vision.face.eyes import EyeState, distance_estimate
from server.vision.face.gestures import HeadGestures
from server.vision.fusion import combined_actions, nearby_objects
from server.vision.hands.analysis import HandDetails
from server.vision.paths import MODEL_DIR, DATA_DIR, model_path, data_path
from server.vision.stability import StableLabel

LOG = logging.getLogger("moon.vision")
BASE = MODEL_DIR  # Backward-compatible name; new code should use MODEL_DIR/DATA_DIR.
EMOTIONS = ("neutral", "happy", "surprised", "sad", "angry", "disgust", "fear", "contempt")


def iou(a, b):
    if a is None or b is None:
        return 0.0
    x, y = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[0]+a[2], b[0]+b[2]), min(a[1]+a[3], b[1]+b[3])
    intersection = max(0, right-x)*max(0, bottom-y)
    return intersection/max(1, a[2]*a[3]+b[2]*b[3]-intersection)


def emotion_face_crop(frame, box, padding=.12):
    """Return a padded square face so resizing to FER+'s 64x64 does not stretch it."""
    x,y,w,h = map(float,box[:4])
    side = max(1,int(round(max(w,h)*(1+2*padding))))
    left,top = int(round(x+w/2-side/2)),int(round(y+h/2-side/2))
    right,bottom = left+side,top+side
    pad_left,pad_top = max(0,-left),max(0,-top)
    pad_right,pad_bottom = max(0,right-frame.shape[1]),max(0,bottom-frame.shape[0])
    if pad_left or pad_top or pad_right or pad_bottom:
        frame = cv2.copyMakeBorder(frame,pad_top,pad_bottom,pad_left,pad_right,cv2.BORDER_REPLICATE)
        left,top = left+pad_left,top+pad_top
    return frame[top:top+side,left:left+side]


def empty_result(status="ok"):
    return dict(status=status, person_detected=False, face_detected=False,
                identity="unknown", identity_score=None, emotion="unknown",
                emotion_confidence=0., action="unknown", head_action="unknown",
                arm_action="unknown", face_box=None, person_box=None,
                upper_body_joints={}, elbow_angles={}, pose_time=0.,
                head_pose=None, expression_cues={}, emotion_source="uncertain",
                actions=[],hands=[],objects=[],emotion_probs={},emotion_scores={},expression_intensities={},
                eyes={"state":"unknown","gaze":"unknown","blink_rate_per_min":None},
                distance={"cm":None,"source":"unavailable"},
                inference_ms=0., frame_time=0.)


class VisionEngine:
    def __init__(self):
        self.models, self.errors = {}, {}
        self.emotion_label, self.identity_label = StableLabel(hold=3), StableLabel(hold=1)
        self.head, self.arms = HeadGestures(), ArmGestures()
        self.head_motion = HeadMotion()
        self.eye_state,self.expression_state = EyeState(),ExpressionState()
        self.master = None
        self.reset()
        if cv2 is None:
            self.errors["opencv"] = "OpenCV is not installed"
            return
        cv2.setNumThreads(settings.VISION_CV_THREADS)
        self._load("face", lambda: cv2.FaceDetectorYN_create(str(model_path("face_detection_yunet_2023mar.onnx")), "", (320,320), settings.VISION_FACE_THRESHOLD))
        self._load("identity", lambda: cv2.FaceRecognizerSF_create(str(model_path("face_recognition_sface_2021dec.onnx")), ""))
        self._load("emotion", lambda: cv2.dnn.readNetFromONNX(str(model_path(settings.EMOTION_MODEL))))
        if settings.VISION_FACE_DETAILS_ENABLED:
            self._load("face_details",lambda:FaceDetails(model_path(settings.VISION_FACE_DETAILS_MODEL)))
        if settings.VISION_HANDS_ENABLED:
            self._load("hands",lambda:HandDetails(model_path(settings.VISION_HANDS_MODEL)))
        enrollment = data_path("master_face.npy")
        if enrollment.exists():
            try:
                feature = np.load(enrollment, allow_pickle=False)
                if feature.size != 128 or not np.isfinite(feature).all() or np.linalg.norm(feature) < 1e-6:
                    raise ValueError("Invalid master face embedding")
                self.master = feature.astype(np.float32).reshape(1,128)
            except Exception as exc:
                self.errors["enrollment"] = str(exc)
        if settings.VISION_POSE_ENABLED:
            def load_pose():
                path = model_path(settings.YOLO_MODEL)
                if not path.is_file():
                    raise FileNotFoundError(f"Missing pose model: {path.name}")
                import torch
                torch.set_num_threads(settings.VISION_CV_THREADS)
                from ultralytics import YOLO
                return YOLO(str(path), task="pose")
            self._load("pose", load_pose)
        if settings.VISION_OBJECTS_ENABLED:
            def load_objects():
                path = model_path(settings.VISION_OBJECTS_MODEL)
                if not path.is_file(): raise FileNotFoundError(path.name)
                import torch
                torch.set_num_threads(settings.VISION_CV_THREADS)
                from ultralytics import YOLO
                return YOLO(str(path),task="detect")
            self._load("objects",load_objects)

    def _load(self, name, loader):
        try:
            self.models[name] = loader()
        except Exception as exc:
            self.errors[name] = str(exc)
            LOG.warning("Cannot load %s: %s",name,exc)

    def _run(self, name, operation):
        try:
            value = operation()
            self.errors.pop(name,None)
            return value
        except Exception as exc:
            if name not in self.errors:
                LOG.warning("%s inference failed: %s",name,exc)
            self.errors[name] = str(exc)
            return None

    def reset(self):
        self.face_box = self.pose_box = self.emotion_probs = None
        self.identity_time = self.emotion_time = -float("inf")
        self.identity_result = {"identity":"unknown","identity_score":None}
        self.emotion_result = {"emotion":"unknown","emotion_confidence":0.}
        self.pose_time = -float("inf")
        self.pose_action = self.head_action = "unknown"
        self.head_until = 0.
        self.joints,self.elbow_angles = {},{}
        self.head_pose,self.cues = None,{}
        self.head_motion.reset()
        self.eye_state.reset()
        self.expression_state.reset()
        self.hands,self.objects = [],[]
        self.hands_time,self.objects_time = -float("inf"),-float("inf")
        if "hands" in self.models: self.models["hands"].reset()
        self.emotion_label.reset()
        self.identity_label.reset()
        self.head.reset()
        self.arms.reset()

    def close(self):
        for name in ("face_details","hands"):
            if name in self.models: self.models[name].close()

    def _objects(self,frame,now):
        prediction = self.models["objects"].predict(frame,imgsz=settings.VISION_OBJECTS_SIZE,
            conf=settings.VISION_OBJECTS_CONFIDENCE,device=settings.VISION_DEVICE,verbose=False)[0]
        objects = []
        for box,score,category in zip(prediction.boxes.xyxy.cpu().numpy(),prediction.boxes.conf.cpu().numpy(),prediction.boxes.cls.cpu().numpy()):
            label = prediction.names[int(category)]
            if label == "person": continue
            x,y,r,b = map(float,box)
            objects.append(dict(label=label,confidence=round(float(score),3),timestamp=now,
                box=[x/frame.shape[1],y/frame.shape[0],(r-x)/frame.shape[1],(b-y)/frame.shape[0]]))
        return objects

    def _person_region_for_hands(self, frame):
        """Use pose when available, otherwise associate hands near the tracked face.

        The fallback deliberately stays inside the image and only affects whether a
        hand gesture belongs to the tracked person; it does not fabricate arm joints.
        """
        if self.pose_box:
            return self.pose_box
        if not self.face_box:
            return None
        x,y,w,h = self.face_box
        left=max(0.,x-1.8*w); top=max(0.,y-.4*h)
        right=min(float(frame.shape[1]),x+2.8*w); bottom=min(float(frame.shape[0]),y+5.0*h)
        return left,top,right-left,bottom-top

    def _schedule(self,now,face):
        # One expensive secondary model per frame keeps eye/head sampling responsive.
        candidates = []
        stages = (("identity",self.identity_time,settings.VISION_IDENTITY_FPS,face and self.master is not None),
                  ("emotion",self.emotion_time,settings.VISION_EMOTION_FPS,face),
                  ("pose",self.pose_time,settings.VISION_POSE_FPS,True),
                  ("hands",self.hands_time,settings.VISION_HANDS_FPS,True),
                  ("objects",self.objects_time,settings.VISION_OBJECTS_FPS,True))
        for name,last,fps,enabled in stages:
            if enabled and name in self.models and now-last >= 1/max(1,fps):
                candidates.append(((now-last)*fps,name))
        return max(candidates,key=lambda item:item[0])[1] if candidates else None

    def _pose(self, frame, now):
        result = self.models["pose"].predict(frame, imgsz=settings.VISION_POSE_SIZE,
            conf=.5, device=settings.VISION_DEVICE, verbose=False)[0]
        boxes = result.boxes.xyxy.cpu().numpy()
        candidates = [(float(x),float(y),float(r-x),float(b-y)) for x,y,r,b in boxes]
        eligible = list(range(len(candidates))) if result.keypoints is not None else []
        if self.face_box:
            x,y,w,h = self.face_box
            eligible = [i for i in eligible if candidates[i][0] <= x+w/2 <= candidates[i][0]+candidates[i][2]
                        and candidates[i][1] <= y+h/2 <= candidates[i][1]+candidates[i][3]]
        if not eligible:
            self.pose_box, self.pose_action = None, "unknown"
            self.joints,self.elbow_angles = {},{}
            self.arms.reset()
            return
        index = max(eligible,key=lambda i: (iou(self.pose_box,candidates[i]) > .25,candidates[i][2]*candidates[i][3]))
        box = candidates[index]
        if iou(self.pose_box,box) < .25:
            self.arms.reset()
        self.pose_box = box
        points = result.keypoints.data[index].cpu().numpy()
        self.joints,self.elbow_angles = upper_body(points,frame.shape)
        self.pose_action = self.arms.update(points,now)

    def process(self, frame, now=None):
        started = time.monotonic()
        now = started if now is None else now
        result, best = empty_result(), None
        if "face" in self.models:
            def detect():
                detector = self.models["face"]
                scale = min(1.,settings.VISION_FACE_WIDTH/frame.shape[1])
                small = cv2.resize(frame,(int(frame.shape[1]*scale),max(1,int(frame.shape[0]*scale)))) if scale < 1 else frame
                detector.setInputSize((small.shape[1],small.shape[0]))
                faces = detector.detect(small)[1]
                if faces is not None:
                    faces = faces.copy()
                    faces[:,:14] /= scale
                return faces
            faces = self._run("face",detect)
            if faces is not None:
                valid = [f for f in faces if np.isfinite(f).all() and min(f[2:4]) > 0]
                if valid:
                    best = max(valid,key=lambda f:(iou(self.face_box,f[:4]) > .25,f[2]*f[3]))
        if best is None:
            stage = self._schedule(now,False)
            self.face_box, self.emotion_probs = None, None
            self.identity_time = self.emotion_time = -float("inf")
            self.identity_result = {"identity":"unknown","identity_score":None}
            self.emotion_result = {"emotion":"unknown","emotion_confidence":0.}
            self.emotion_label.reset()
            self.identity_label.reset()
            self.head.reset()
            self.head_motion.reset()
            self.eye_state.reset()
            self.expression_state.reset()
            self.head_pose,self.cues = None,{}
            self.head_action, self.head_until = "unknown", 0.
        else:
            if iou(self.face_box,best[:4]) < .25:
                self.reset()
            self.face_box = tuple(float(v) for v in best[:4])
            stage = self._schedule(now,min(best[2:4]) >= settings.VISION_MIN_FACE_SIZE)
            result.update(face_detected=True,face_box=list(self.face_box))
            x,y,w,h = self.face_box
            crop = frame[max(0,int(y)):max(0,min(frame.shape[0],int(y+h))),max(0,int(x)):max(0,min(frame.shape[1],int(x+w)))]
            if crop.size and min(crop.shape[:2]) >= settings.VISION_MIN_FACE_SIZE:
                details = self._run("face_details",lambda:self.models["face_details"].detect(frame,self.face_box,now)) if "face_details" in self.models else None
                self.head_pose = details["angles"] if details else None
                self.cues = details["cues"] if details else {}
                result["eyes"] = self.eye_state.update(details.get("eyes") if details else None,self.head_pose,now)
                result["distance"] = distance_estimate(self.face_box,frame.shape[1],self.head_pose)
                # Never mix sparse ratios with 3D angle histories during tracking loss.
                event = self.head_motion.update(self.head_pose,now) if "face_details" in self.models else self.head.update(best,now)
                if event != "unknown":
                    self.head_action,self.head_until = event,now+.7
                if stage == "identity":
                    self.identity_time = now
                    def recognize():
                        model = self.models["identity"]
                        feature = model.feature(model.alignCrop(frame,best))
                        return float(model.match(self.master,feature,cv2.FaceRecognizerSF_FR_COSINE))
                    score = self._run("identity",recognize)
                    if score is not None and np.isfinite(score):
                        result["identity_score"] = score
                        result["identity"] = self.identity_label.update("Master" if score >= settings.VISION_IDENTITY_THRESHOLD else "Guest")
                    else:
                        self.identity_label.reset()
                    self.identity_result = {key:result[key] for key in ("identity","identity_score")}
                result.update(self.identity_result)
                emotion_fresh = False
                if now-self.emotion_time > settings.VISION_EMOTION_STALE_SEC:
                    self.emotion_probs = None
                if stage == "emotion":
                    self.emotion_time = now
                    def expression():
                        gray = cv2.cvtColor(emotion_face_crop(frame,best),cv2.COLOR_BGR2GRAY)
                        blob = cv2.dnn.blobFromImage(gray,1.,(64,64),swapRB=False,crop=False)
                        self.models["emotion"].setInput(blob)
                        logits = self.models["emotion"].forward().reshape(-1)
                        if logits.size != 8 or not np.isfinite(logits).all():
                            raise ValueError("Invalid FER+ logits")
                        probs = np.exp(logits-logits.max())
                        return probs/probs.sum()
                    probs = self._run("emotion",expression)
                    if probs is not None:
                        emotion_fresh = True
                        self.emotion_probs = probs if self.emotion_probs is None else .65*probs+.35*self.emotion_probs
                    else:
                        self.emotion_probs = None
                        self.emotion_label.reset()
                result.update(self.expression_state.update(
                    self.emotion_probs,self.cues,now,fer_fresh=emotion_fresh))
                result["emotion_probs"] = {name:round(float(value),5) for name,value in zip(EMOTIONS,self.emotion_probs)} if self.emotion_probs is not None else {}
            else:
                self.identity_time = self.emotion_time = -float("inf")
                self.identity_result = {"identity":"unknown","identity_score":None}
                self.emotion_result = {"emotion":"unknown","emotion_confidence":0.}
                self.emotion_probs = None
                self.emotion_label.reset()
                self.identity_label.reset()
                self.head.reset()
                self.head_motion.reset()
                self.eye_state.reset()
                self.expression_state.reset()
                self.head_pose,self.cues = None,{}
                self.head_until = 0.
        if stage == "pose":
            self.pose_time = now
            self._run("pose",lambda:self._pose(frame,now))
            if "pose" in self.errors:
                self.pose_box,self.pose_action = None,"unknown"
                self.joints,self.elbow_angles = {},{}
                self.arms.reset()
        if now-self.pose_time > .75:
            self.pose_box,self.pose_action = None,"unknown"
            self.joints,self.elbow_angles = {},{}
        head_action = self.head_action if now < self.head_until else "unknown"
        if stage == "hands":
            self.hands_time = now
            body_hint = self._person_region_for_hands(frame)
            self.hands = self._run("hands",lambda:self.models["hands"].detect(frame,now,self.joints,body_hint)) or []
        if now-self.hands_time > settings.VISION_HANDS_STALE_SEC: self.hands = []
        if stage == "objects":
            self.objects_time = now
            self.objects = self._run("objects",lambda:self._objects(frame,now)) or []
        if now-self.objects_time > settings.VISION_OBJECTS_STALE_SEC: self.objects = []
        actions = combined_actions(head_action,self.pose_action,self.hands)
        result.update(person_detected=best is not None or self.pose_box is not None,
                      person_box=list(self.pose_box) if self.pose_box else None,
                      head_action=head_action,arm_action=self.pose_action,
                      upper_body_joints=self.joints,elbow_angles=self.elbow_angles,
                      pose_time=self.pose_time if np.isfinite(self.pose_time) else 0.,
                      head_pose=self.head_pose,expression_cues=self.cues,
                      actions=actions,hands=self.hands,objects=nearby_objects(self.objects,self.hands),
                      hand_count=len(self.hands),object_count=len(self.objects),
                      secondary_stage=stage,
                      frame_size=[frame.shape[1],frame.shape[0]],
                      action=" + ".join(item["label"] for item in actions) or "unknown",
                      inference_ms=round((time.monotonic()-started)*1000,1),
                      models={name:name in self.models and name not in self.errors for name in ("face","identity","emotion","pose","face_details","hands","objects")},
                      errors=dict(self.errors),enrolled=self.master is not None)
        if self.errors:
            result["status"] = "degraded"
        return result
