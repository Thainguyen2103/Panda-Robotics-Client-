"""Observable eye geometry, blink state, gaze and face-distance estimates."""
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
