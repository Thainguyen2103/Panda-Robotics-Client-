"""Observable eye/hand/object signals. Scores are not psychological diagnoses."""
from collections import deque
import math
import numpy as np
from config import settings


def eye_geometry(landmarks, shape):
    p = np.array([[v.x*shape[1],v.y*shape[0]] for v in landmarks])
    if len(p) < 478 or not np.isfinite(p).all():
        return None
    ears,iris,vertical = [],[],[]
    for indices,center in (((33,160,158,133,153,144),468),((362,385,387,263,373,380),473)):
        a,b,c,d,e,f = p[list(indices)]
        width = np.linalg.norm(d-a)
        if width < 8:
            return None
        ears.append(float((np.linalg.norm(b-f)+np.linalg.norm(c-e))/(2*width)))
        axis = (d-a)/width
        iris.append(float(np.dot(p[center]-a,axis)/width))
        normal = np.array([-axis[1],axis[0]])
        vertical.append(float(np.dot(p[center]-(b+c+e+f)/4,normal)/width))
    return dict(ear_left=ears[0],ear_right=ears[1],iris_horizontal=iris,iris_vertical=vertical)


class EyeState:
    def __init__(self): self.reset()

    def reset(self):
        self.samples = deque()
        self.blinks = deque()
        self.closed_since = None
        self.last = None
        self.started = None
        self.closed = False
        self.intervals = deque(maxlen=30)

    def update(self, geometry, angles, now):
        if geometry is None:
            self.reset()
            return dict(state="unknown",gaze="unknown",blink_rate_per_min=None)
        if self.last is not None and now-self.last > .4:
            # Do not bridge a missed interval into a long eye closure/blink.
            self.reset()
        if self.started is None: self.started = now
        if self.last is not None: self.intervals.append(now-self.last)
        self.last = now
        ear = (geometry["ear_left"]+geometry["ear_right"])/2
        both_closed = max(geometry["ear_left"],geometry["ear_right"]) < settings.VISION_EAR_CLOSED
        both_open = min(geometry["ear_left"],geometry["ear_right"]) > settings.VISION_EAR_OPEN
        if "blink_left" in geometry and "blink_right" in geometry:
            both_closed &= min(geometry["blink_left"],geometry["blink_right"]) > .55
            both_open |= max(geometry["blink_left"],geometry["blink_right"]) < .25
        if not self.closed and both_closed:
            self.closed,self.closed_since = True,now
        elif self.closed and both_open:
            duration = now-self.closed_since
            if .05 <= duration <= .8: self.blinks.append(now)
            self.closed,self.closed_since = False,None
        self.samples.append((now,self.closed))
        while self.samples and now-self.samples[0][0] > 60: self.samples.popleft()
        while self.blinks and now-self.blinks[0] > 60: self.blinks.popleft()
        duration = now-self.closed_since if self.closed_since is not None else 0.
        state = "prolonged_closure" if duration >= settings.VISION_EYES_CLOSED_SEC else "closed" if self.closed else "open"
        gaze = "unknown"
        if angles and both_open:
            centered = all(.34 <= v <= .66 for v in geometry["iris_horizontal"]) and all(abs(v) < .10 for v in geometry.get("iris_vertical",[0,0]))
            gaze = "toward_camera" if centered and abs(angles["yaw"]) < 15 and abs(angles["pitch"]) < 18 else "away"
        observed = min(60.,now-self.started)
        fps = 1/float(np.median(self.intervals)) if self.intervals else 0.
        closed_seconds = sum((b[0]-a[0])*a[1] for a,b in zip(self.samples,list(self.samples)[1:]))
        span = self.samples[-1][0]-self.samples[0][0]
        return dict(state=state,gaze=gaze,ear=round(ear,3),closure_seconds=round(duration,2),possible_drowsiness=state=="prolonged_closure",
                    blink_count_60s=len(self.blinks),blink_rate_per_min=round(len(self.blinks)*60/observed,1) if observed >= 20 else None,
                    closed_fraction=round(closed_seconds/span,3) if span >= 20 else None,
                    sample_fps=round(fps,1),quality="limited_sampling" if fps < 15 else "estimated",
                    observed_seconds=round(observed,1))


def distance_estimate(box, frame_width, angles):
    if box is None or box[2] < 30 or not angles or abs(angles["yaw"]) > 20 or abs(angles["pitch"]) > 20:
        return dict(cm=None,source="unavailable")
    scale = settings.VISION_DISTANCE_SCALE_CM
    source = "calibrated_reference" if scale else "assumed_fov"
    if not scale:
        scale = settings.VISION_FACE_WIDTH_CM/(2*math.tan(math.radians(settings.VISION_CAMERA_HFOV/2)))
    return dict(cm=round(scale*frame_width/box[2],1),source=source)


def angle(a,b,c):
    x,y = a-b,c-b
    norm = np.linalg.norm(x)*np.linalg.norm(y)
    return math.degrees(math.acos(float(np.clip(np.dot(x,y)/norm,-1,1)))) if norm > 1e-8 else 0.


HAND_EDGES = tuple((i,i+1) for start in (1,5,9,13,17) for i in range(start,start+3))+((0,1),(0,5),(5,9),(9,13),(13,17),(0,17))


def finger_gesture(points):
    """Geometry rules in aspect-corrected image coordinates, invariant to hand scale."""
    p = np.asarray(points)
    if p.shape != (21,3) or not np.isfinite(p).all(): return "unknown"
    palm = np.linalg.norm(p[0]-p[9])
    if palm < 1e-5: return "unknown"
    extended = []
    for base in (5,9,13,17):
        extended.append(angle(p[base],p[base+1],p[base+3]) > 155 and np.linalg.norm(p[base+3]-p[0]) > 1.12*np.linalg.norm(p[base+1]-p[0]))
    thumb = angle(p[1],p[2],p[4]) > 150 and np.linalg.norm(p[4]-p[9]) > .7*palm
    if extended == [True,True,False,False] and np.linalg.norm(p[8]-p[12]) > .25*palm: return "victory"
    if not any(extended) and thumb and p[4,1] < p[3,1] < p[2,1]: return "thumbs_up"
    if all(extended) and thumb: return "open_palm"
    if extended == [True,False,False,False] and not thumb: return "pointing"
    if not any(extended) and not thumb: return "fist"
    return "unknown"


class HandDetails:
    def __init__(self,path):
        import mediapipe as mp
        self.mp,self.timestamp = mp,-1
        self.history = {}
        self.model = mp.tasks.vision.HandLandmarker.create_from_options(mp.tasks.vision.HandLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(path)),running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_hands=2,min_hand_detection_confidence=.6,min_hand_presence_confidence=.6,min_tracking_confidence=.6))

    def close(self): self.model.close()
    def reset(self): self.history.clear()

    def detect(self,frame,now,joints,body):
        import cv2
        self.timestamp = max(self.timestamp+1,int(now*1000))
        result = self.model.detect_for_video(self.mp.Image(image_format=self.mp.ImageFormat.SRGB,data=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)),self.timestamp)
        hands,new_history = [],{}
        for i,landmarks in enumerate(result.hand_landmarks):
            coords = np.array([[v.x,v.y,v.z] for v in landmarks])
            if not np.isfinite(coords).all(): continue
            handedness = result.handedness[i][0]
            side = handedness.category_name.lower()
            wrist = coords[0,:2]
            nearest = [(float(np.linalg.norm(wrist-[j["x"],j["y"]])),key) for key,j in joints.items() if key.endswith("wrist") and j["visible"]]
            associated = False
            if nearest and min(nearest)[0] < .18:
                side = min(nearest)[1].split('_')[0]
                associated = True
            elif body:
                x,y,w,h = body
                associated = x <= wrist[0]*frame.shape[1] <= x+w and y <= wrist[1]*frame.shape[0] <= y+h
            corrected = coords*np.array([frame.shape[1],frame.shape[0],frame.shape[1]])
            candidate = finger_gesture(corrected)
            previous = self.history.get(side)
            count = previous[1]+1 if previous and previous[0] == candidate and now-previous[2] < .5 and np.linalg.norm(wrist-previous[3]) < .2 else 1
            new_history[side] = candidate,count,now,wrist
            hands.append(dict(side=side,associated=associated,confidence=round(float(handedness.score),3),
                gesture=candidate if count >= 2 else "unknown",landmarks=np.round(coords,5).tolist(),timestamp=now))
        self.history = new_history
        return hands


def combined_actions(head,arm,hands):
    items = [dict(channel="head",label=head)] if head != "unknown" else []
    if arm != "unknown": items.append(dict(channel="arms",label=arm))
    for hand in hands:
        if hand["associated"] and hand["gesture"] != "unknown":
            items.append(dict(channel=hand["side"]+"_hand",label=hand["gesture"]))
    return items


def nearby_objects(objects,hands):
    """Proximity only: do not claim an object is grasped from 2D overlap."""
    output = []
    for obj in objects:
        x,y,w,h = obj["box"]
        sides = []
        for hand in hands:
            if not hand["associated"]: continue
            for px,py,_ in hand["landmarks"]:
                if x-.03 <= px <= x+w+.03 and y-.03 <= py <= y+h+.03:
                    sides.append(hand["side"])
                    break
        output.append({**obj,"near_hands":sorted(set(sides))})
    return output
