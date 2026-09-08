"""YuNet/SFace/FER+ and upper-body gestures, using a latest-frame mailbox.

Importing this module opens neither a camera nor a network connection.
"""
import base64
from collections import deque
import logging
from pathlib import Path
import sys
import threading
import time

import numpy as np
try:
    import cv2
except ImportError:
    cv2 = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import settings
from server.vision_features import FaceDetails, HeadMotion, ExpressionState, upper_body, ARM_EDGES
from server.vision_signals import EyeState, HandDetails, distance_estimate, combined_actions, nearby_objects, HAND_EDGES

LOG = logging.getLogger("panda.vision")
BASE = Path(__file__).resolve().parent
EMOTIONS = ("neutral", "happy", "surprised", "sad", "angry", "disgust", "fear", "contempt")


def iou(a, b):
    if a is None or b is None:
        return 0.0
    x, y = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[0]+a[2], b[0]+b[2]), min(a[1]+a[3], b[1]+b[3])
    intersection = max(0, right-x)*max(0, bottom-y)
    return intersection/max(1, a[2]*a[3]+b[2]*b[3]-intersection)


class StableLabel:
    def __init__(self, count=3, hold=0):
        self.count = count
        self.hold = hold
        self.reset()

    def reset(self):
        self.pending, self.samples = "unknown", 0
        self.value, self.uncertain = "unknown", 0

    def update(self, label):
        if label == "unknown":
            self.pending,self.samples = "unknown",0
            self.uncertain += 1
            if self.uncertain > self.hold:
                self.value = "unknown"
            return self.value
        self.samples = self.samples+1 if label == self.pending else 1
        self.pending = label
        if self.samples >= self.count:
            self.value,self.uncertain = label,0
        else:
            self.uncertain += 1
            if self.uncertain > self.hold:
                self.value = "unknown"
        return self.value


def excursions(values, threshold):
    """Count changes of direction only after a substantial excursion."""
    if not values:
        return 0
    anchor, direction, reversals = values[0], 0, 0
    for value in values[1:]:
        delta = value-anchor
        if abs(delta) >= threshold:
            new_direction = 1 if delta > 0 else -1
            reversals += int(bool(direction) and direction != new_direction)
            direction, anchor = new_direction, value
    return reversals


class HeadGestures:
    """Temporal landmark ratios for a frontal face; heuristic, not a trained HAR model."""
    def __init__(self):
        self.history = deque()
        self.last_event = -float("inf")

    def reset(self):
        self.history.clear()
        self.last_event = -float("inf")

    def update(self, face, now):
        # YuNet: right eye, left eye, nose, right mouth, left mouth.
        points = np.asarray(face[4:14], dtype=float).reshape(5, 2)
        eye_mid = points[:2].mean(axis=0)
        eye_axis = points[1]-points[0]
        width = np.linalg.norm(eye_axis)
        if width < 15 or not np.isfinite(points).all():
            self.reset()
            return "unknown"
        eye_axis /= width
        down = np.array([-eye_axis[1], eye_axis[0]])
        if np.dot(points[3:].mean(axis=0)-eye_mid, down) < 0:
            down = -down
        mouth_distance = np.dot(points[3:].mean(axis=0)-eye_mid, down)
        if mouth_distance < .25*width:
            self.reset()
            return "unknown"
        nose = points[2]-eye_mid
        yaw = float(np.dot(nose, eye_axis)/width)
        pitch = float(np.dot(nose, down)/mouth_distance)
        if self.history and now-self.history[-1][0] > .5:
            self.history.clear()
        self.history.append((now, yaw, pitch))
        while self.history and now-self.history[0][0] > 1.6:
            self.history.popleft()
        if len(self.history) < 5 or now-self.history[0][0] < .4 or now-self.last_event < 1.0:
            return "unknown"
        yaw_values = [v[1] for v in self.history]
        pitch_values = [v[2] for v in self.history]
        yaw_range, pitch_range = np.ptp(yaw_values), np.ptp(pitch_values)
        label = "unknown"
        if yaw_range >= .28 and yaw_range > pitch_range*1.5 and excursions(yaw_values, .12) >= 1:
            label = "head_shake"
        elif pitch_range >= .18 and pitch_range > yaw_range*1.5 and excursions(pitch_values, .08) >= 1:
            label = "head_nod"
        if label != "unknown":
            self.last_event = now
            self.history.clear()
        return label


class ArmGestures:
    """Only shoulders/elbows/wrists are required; lower-body points are unused."""
    def __init__(self):
        self.history = {9: deque(), 10: deque()}
        self.stable = StableLabel(2)

    def reset(self):
        for history in self.history.values():
            history.clear()
        self.stable.reset()

    def update(self, points, now):
        p = np.asarray(points)
        if p.shape != (17, 3) or not np.isfinite(p).all():
            self.reset()
            return "unknown"
        def visible(*indices):
            return all(p[i,2] >= settings.VISION_KEYPOINT_THRESHOLD for i in indices)
        if not visible(5,6):
            self.reset()
            return "unknown"
        scale = max(float(np.linalg.norm(p[5,:2]-p[6,:2])),20.)
        raised, waving = [], False
        for shoulder, elbow, wrist in ((5,7,9),(6,8,10)):
            up = visible(wrist) and p[wrist,1] < p[shoulder,1]-.15*scale
            raised.append(up)
            history = self.history[wrist]
            if not up:
                history.clear()
                continue
            if history and now-history[-1][0] > .6:
                history.clear()
            # Elbow-relative motion is less affected by the whole upper body moving.
            reference = elbow if visible(elbow) else shoulder
            if history and history[-1][2] != reference:
                history.clear()
            history.append((now,float((p[wrist,0]-p[reference,0])/scale),reference))
            while history and now-history[0][0] > 1.8:
                history.popleft()
            if len(history) >= 4 and history[-1][0]-history[0][0] >= .45:
                waving |= excursions([v[1] for v in history], .16) >= 1
        label = ("waving" if waving else "both_hands_up" if all(raised)
                 else "hand_raised" if any(raised) else "unknown")
        return self.stable.update(label)


def empty_result(status="ok"):
    return dict(status=status, person_detected=False, face_detected=False,
                identity="unknown", identity_score=None, emotion="unknown",
                emotion_confidence=0., action="unknown", head_action="unknown",
                arm_action="unknown", face_box=None, person_box=None,
                upper_body_joints={}, elbow_angles={}, pose_time=0.,
                head_pose=None, expression_cues={}, emotion_source="uncertain",
                actions=[],hands=[],objects=[],emotion_probs={},expression_intensities={},
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
        self._load("face", lambda: cv2.FaceDetectorYN_create(str(BASE/"face_detection_yunet_2023mar.onnx"), "", (320,320), settings.VISION_FACE_THRESHOLD))
        self._load("identity", lambda: cv2.FaceRecognizerSF_create(str(BASE/"face_recognition_sface_2021dec.onnx"), ""))
        self._load("emotion", lambda: cv2.dnn.readNetFromONNX(str(BASE/settings.EMOTION_MODEL)))
        if settings.VISION_FACE_DETAILS_ENABLED:
            self._load("face_details",lambda:FaceDetails(BASE/settings.VISION_FACE_DETAILS_MODEL))
        if settings.VISION_HANDS_ENABLED:
            self._load("hands",lambda:HandDetails(BASE/settings.VISION_HANDS_MODEL))
        if (BASE/"master_face.npy").exists():
            try:
                feature = np.load(BASE/"master_face.npy", allow_pickle=False)
                if feature.size != 128 or not np.isfinite(feature).all() or np.linalg.norm(feature) < 1e-6:
                    raise ValueError("Invalid master face embedding")
                self.master = feature.astype(np.float32).reshape(1,128)
            except Exception as exc:
                self.errors["enrollment"] = str(exc)
        if settings.VISION_POSE_ENABLED:
            def load_pose():
                path = Path(settings.YOLO_MODEL)
                if not path.is_absolute():
                    path = BASE/path
                if not path.is_file():
                    raise FileNotFoundError(f"Missing pose model: {path.name}")
                import torch
                torch.set_num_threads(settings.VISION_CV_THREADS)
                from ultralytics import YOLO
                return YOLO(str(path), task="pose")
            self._load("pose", load_pose)
        if settings.VISION_OBJECTS_ENABLED:
            def load_objects():
                path = BASE/settings.VISION_OBJECTS_MODEL
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
        prediction = self.models["objects"].predict(frame,imgsz=320,conf=.45,device=settings.VISION_DEVICE,verbose=False)[0]
        objects = []
        for box,score,category in zip(prediction.boxes.xyxy.cpu().numpy(),prediction.boxes.conf.cpu().numpy(),prediction.boxes.cls.cpu().numpy()):
            label = prediction.names[int(category)]
            if label == "person": continue
            x,y,r,b = map(float,box)
            objects.append(dict(label=label,confidence=round(float(score),3),timestamp=now,
                box=[x/frame.shape[1],y/frame.shape[0],(r-x)/frame.shape[1],(b-y)/frame.shape[0]]))
        return objects

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
                if stage == "emotion":
                    self.emotion_time = now
                    def expression():
                        gray = cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY)
                        blob = cv2.dnn.blobFromImage(gray,1.,(64,64),swapRB=False,crop=False)
                        self.models["emotion"].setInput(blob)
                        logits = self.models["emotion"].forward().reshape(-1)
                        if logits.size != 8 or not np.isfinite(logits).all():
                            raise ValueError("Invalid FER+ logits")
                        probs = np.exp(logits-logits.max())
                        return probs/probs.sum()
                    probs = self._run("emotion",expression)
                    if probs is not None:
                        self.emotion_probs = probs if self.emotion_probs is None else .65*probs+.35*self.emotion_probs
                    else:
                        self.emotion_probs = None
                        self.emotion_label.reset()
                result.update(self.expression_state.update(self.emotion_probs,self.cues,now))
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
            self.hands = self._run("hands",lambda:self.models["hands"].detect(frame,now,self.joints,self.pose_box)) or []
        if now-self.hands_time > .6: self.hands = []
        if stage == "objects":
            self.objects_time = now
            self.objects = self._run("objects",lambda:self._objects(frame,now)) or []
        if now-self.objects_time > 1.5: self.objects = []
        actions = combined_actions(head_action,self.pose_action,self.hands)
        result.update(person_detected=best is not None or self.pose_box is not None,
                      person_box=list(self.pose_box) if self.pose_box else None,
                      head_action=head_action,arm_action=self.pose_action,
                      upper_body_joints=self.joints,elbow_angles=self.elbow_angles,
                      pose_time=self.pose_time if np.isfinite(self.pose_time) else 0.,
                      head_pose=self.head_pose,expression_cues=self.cues,
                      actions=actions,hands=self.hands,objects=nearby_objects(self.objects,self.hands),
                      secondary_stage=stage,
                      frame_size=[frame.shape[1],frame.shape[0]],
                      action=" + ".join(item["label"] for item in actions) or "unknown",
                      inference_ms=round((time.monotonic()-started)*1000,1),
                      models={name:name in self.models and name not in self.errors for name in ("face","identity","emotion","pose","face_details","hands","objects")},
                      errors=dict(self.errors),enrolled=self.master is not None)
        if self.errors:
            result["status"] = "degraded"
        return result


class LatestFrame:
    """Single-slot mailbox: slow inference never queues old frames."""
    def __init__(self):
        self.lock = threading.Lock()
        self.frame,self.timestamp,self.sequence = None,0.,0

    def put(self, frame):
        with self.lock:
            self.frame,self.timestamp = frame,time.monotonic()
            self.sequence += 1

    def get(self):
        with self.lock:
            return self.frame,self.timestamp,self.sequence


def camera_source():
    source = settings.VISION_SOURCE
    return int(source) if str(source).isdigit() else source


def start_vision(callback, stop_event=None, publish=None):
    """Preserve the brain callback; send detailed diagnostics on a separate topic."""
    if publish is None:
        from server.mqtt_bridge import publish
    stop = stop_event if stop_event is not None else threading.Event()
    mailbox = LatestFrame()
    result_lock = threading.Lock()
    latest = empty_result("starting")
    last_good_inference = time.monotonic()

    def emit(result):
        nonlocal latest,last_good_inference
        with result_lock:
            latest = result
            if result.get("frame_time",0):
                last_good_inference = time.monotonic()
        try:
            publish(settings.TOPIC_VISION_STATUS,result)
            publish("panda/user_status",result)
            callback(result["person_detected"],result["emotion"],result["action"])
        except Exception:
            LOG.exception("Vision output failed")

    def capture():
        cap = None
        try:
            while not stop.is_set():
                if cap is None:
                    if cv2 is None:
                        stop.wait(1)
                        continue
                    cap = cv2.VideoCapture(camera_source())
                    if not cap.isOpened():
                        cap.release()
                        cap = None
                        stop.wait(2)
                        continue
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH,settings.VISION_WIDTH)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT,settings.VISION_HEIGHT)
                    cap.set(cv2.CAP_PROP_BUFFERSIZE,1)
                ok,frame = cap.read()
                if not ok or frame is None:
                    mailbox.put(None)
                    cap.release()
                    cap = None
                    stop.wait(1)
                    continue
                scale = min(1.,settings.VISION_WIDTH/frame.shape[1],settings.VISION_HEIGHT/frame.shape[0])
                if scale < 1:
                    frame = cv2.resize(frame,(max(1,int(frame.shape[1]*scale)),max(1,int(frame.shape[0]*scale))))
                mailbox.put(frame)
                stop.wait(.001)
        except Exception:
            LOG.exception("Camera capture failed")
            mailbox.put(None)
        finally:
            if cap is not None:
                cap.release()

    def infer():
        engine = VisionEngine()
        sequence = -1
        try:
            while not stop.is_set():
                began = time.monotonic()
                frame,timestamp,current = mailbox.get()
                if frame is not None and current != sequence and began-timestamp <= settings.VISION_STALE_SEC:
                    sequence = current
                    try:
                        result = engine.process(frame)
                        result["frame_time"] = timestamp
                        if time.monotonic()-timestamp <= settings.VISION_STALE_SEC:
                            emit(result)
                    except Exception:
                        LOG.exception("Vision frame failed")
                        engine.reset()
                elif frame is None or began-timestamp > settings.VISION_STALE_SEC:
                    engine.reset()
                stop.wait(max(.01,1/max(1,settings.VISION_AI_FPS)-(time.monotonic()-began)))
        finally:
            close = getattr(engine,"close",None)
            if close:
                close()

    workers = [threading.Thread(target=fn,daemon=True,name=name)
               for fn,name in ((capture,"vision-camera"),(infer,"vision-ai"))]
    for worker in workers:
        worker.start()
    last_sequence,last_offline = -1,-float("inf")
    try:
        while not stop.is_set():
            began = time.monotonic()
            frame,timestamp,sequence = mailbox.get()
            with result_lock:
                result = dict(latest)
                inference_age = began-last_good_inference
            camera_lost = frame is None or began-timestamp > settings.VISION_STALE_SEC
            if camera_lost or inference_age > settings.VISION_STALE_SEC:
                if began-last_offline >= 1:
                    emit(empty_result("camera_unavailable" if camera_lost else "inference_stale"))
                    last_offline = began
            if frame is not None and sequence != last_sequence and not camera_lost:
                last_sequence = sequence
                display = frame.copy()
                if began-result.get("frame_time",0) <= .5:
                    for hand in result.get("hands",[]):
                        if began-hand["timestamp"] > .5: continue
                        points = [(int(v[0]*display.shape[1]),int(v[1]*display.shape[0])) for v in hand["landmarks"]]
                        for a,b in HAND_EDGES: cv2.line(display,points[a],points[b],(80,220,120),1)
                        for p in points: cv2.circle(display,p,2,(80,255,180),-1)
                    for obj in result.get("objects",[]):
                        if began-obj["timestamp"] > 1.5: continue
                        x,y,w,h = obj["box"]
                        x,y,w,h = int(x*display.shape[1]),int(y*display.shape[0]),int(w*display.shape[1]),int(h*display.shape[0])
                        cv2.rectangle(display,(x,y),(x+w,y+h),(220,180,80),1)
                        cv2.putText(display,obj["label"],(x,max(14,y-4)),cv2.FONT_HERSHEY_SIMPLEX,.4,(220,180,80),1)
                    if settings.VISION_DRAW_SKELETON and began-result.get("pose_time",0) <= .5:
                        joints = result.get("upper_body_joints",{})
                        def point(joint):
                            return (int(joint["x"]*display.shape[1]),int(joint["y"]*display.shape[0]))
                        for a,b in ARM_EDGES:
                            if joints.get(a,{}).get("visible") and joints.get(b,{}).get("visible"):
                                cv2.line(display,point(joints[a]),point(joints[b]),(255,200,0),2)
                        for joint in joints.values():
                            if joint["visible"]:
                                cv2.circle(display,point(joint),4,(0,220,255),-1)
                    for key,color in (("face_box",(0,255,0)),("person_box",(255,180,0))):
                        if result.get(key):
                            x,y,w,h = map(int,result[key])
                            cv2.rectangle(display,(x,y),(x+w,y+h),color,2)
                    # Labels belong in the stable dashboard, not flickering on the video.
                width = min(480,display.shape[1])
                display = cv2.resize(display,(width,max(1,round(display.shape[0]*width/display.shape[1]))))
                ok,encoded = cv2.imencode(".jpg",display,[cv2.IMWRITE_JPEG_QUALITY,60])
                if ok:
                    publish(settings.TOPIC_CAMERA,base64.b64encode(encoded).decode("ascii"))
            stop.wait(max(.001,1/max(1,settings.VISION_STREAM_FPS)-(time.monotonic()-began)))
    finally:
        stop.set()
        for worker in workers:
            worker.join(timeout=2)


if __name__ == "__main__":
    if hasattr(sys.stdout,"reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8",errors="replace")
    logging.basicConfig(level=logging.INFO)
    start_vision(lambda detected,emotion,action:None)
