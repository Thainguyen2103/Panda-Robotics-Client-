"""Hand landmarks and geometry-based gesture labels."""
import math

import numpy as np

from config import settings


def angle(a,b,c):
    x,y = a-b,c-b
    norm = np.linalg.norm(x)*np.linalg.norm(y)
    return math.degrees(math.acos(float(np.clip(np.dot(x,y)/norm,-1,1)))) if norm > 1e-8 else 0.


HAND_EDGES = tuple((i,i+1) for start in (1,5,9,13,17) for i in range(start,start+3))+((0,1),(0,5),(5,9),(9,13),(13,17),(0,17))


def finger_states(points):
    p = np.asarray(points)
    if p.shape != (21,3) or not np.isfinite(p).all(): return None
    states=[]
    for base in (5,9,13,17):
        straight = angle(p[base],p[base+1],p[base+3]) >= settings.VISION_FINGER_STRAIGHT_DEGREES
        reaches = np.linalg.norm(p[base+3]-p[0]) >= settings.VISION_FINGER_EXTENSION_RATIO*np.linalg.norm(p[base+1]-p[0])
        states.append(bool(straight and reaches))
    return states


def finger_gesture(points):
    p = np.asarray(points)
    if p.shape != (21,3) or not np.isfinite(p).all(): return "unknown"
    palm = np.linalg.norm(p[0]-p[9])
    if palm < 1e-5: return "unknown"
    extended = finger_states(p)
    thumb = (angle(p[1],p[2],p[4]) >= settings.VISION_THUMB_STRAIGHT_DEGREES
             and np.linalg.norm(p[4]-p[9]) > .65*palm)
    thumb_index_touch = np.linalg.norm(p[4]-p[8]) < .32*palm
    if thumb_index_touch and extended[1:] == [True,True,True]: return "ok_sign"
    if thumb_index_touch and not all(extended[1:]): return "pinch"
    if extended == [True,True,False,False] and np.linalg.norm(p[8]-p[12]) > .25*palm: return "victory"
    if not any(extended) and thumb and p[4,1] < p[3,1] < p[2,1]: return "thumbs_up"
    if not any(extended) and thumb and p[4,1] > p[3,1] > p[2,1]: return "thumbs_down"
    if all(extended) and thumb: return "open_palm"
    if all(extended) and not thumb: return "four_fingers"
    if extended == [True,True,True,False]: return "three_fingers"
    if extended == [True,False,False,True] and not thumb: return "rock_sign"
    if extended == [True,False,False,True] and thumb: return "i_love_you"
    if extended == [False,False,False,True] and thumb: return "shaka"
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
            num_hands=2,min_hand_detection_confidence=settings.VISION_HANDS_CONFIDENCE,
            min_hand_presence_confidence=settings.VISION_HANDS_CONFIDENCE,
            min_tracking_confidence=settings.VISION_HANDS_CONFIDENCE))

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
            states = finger_states(corrected)
            extended_count = sum(states) if states is not None else 0
            previous = self.history.get(side)
            count = previous[1]+1 if previous and previous[0] == candidate and now-previous[2] < .5 and np.linalg.norm(wrist-previous[3]) < .2 else 1
            new_history[side] = candidate,count,now,wrist
            hands.append(dict(side=side,associated=bool(associated),confidence=round(float(handedness.score),3),
                gesture=candidate if count >= 2 else "unknown",gesture_candidate=candidate,
                stability=count,extended_fingers=extended_count,
                center=np.round(coords[:,:2].mean(axis=0),5).tolist(),
                landmarks=np.round(coords,5).tolist(),timestamp=now))
        self.history = new_history
        return hands
