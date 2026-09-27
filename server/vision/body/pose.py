"""Normalized upper-body joints and elbow angles."""
import math

import numpy as np

from config import settings


JOINT_NAMES = {5:"left_shoulder",6:"right_shoulder",7:"left_elbow",8:"right_elbow",9:"left_wrist",10:"right_wrist"}
ARM_EDGES = (("left_shoulder","left_elbow"),("left_elbow","left_wrist"),
             ("right_shoulder","right_elbow"),("right_elbow","right_wrist"),
             ("left_shoulder","right_shoulder"))


def upper_body(points, shape):
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
