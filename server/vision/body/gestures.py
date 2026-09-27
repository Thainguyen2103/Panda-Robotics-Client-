"""Upper-body gesture classification."""
from collections import deque

import numpy as np

from config import settings
from server.vision.face.gestures import excursions
from server.vision.stability import StableLabel


class ArmGestures:
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
        visible_shoulders = [i for i in (5,6) if visible(i)]
        if not visible_shoulders:
            self.reset()
            return "unknown"
        if len(visible_shoulders) == 2:
            scale = float(np.linalg.norm(p[5,:2]-p[6,:2]))
        else:
            shoulder = visible_shoulders[0]
            elbow = 7 if shoulder == 5 else 8
            wrist = 9 if shoulder == 5 else 10
            limb = elbow if visible(elbow) else wrist if visible(wrist) else shoulder
            scale = float(np.linalg.norm(p[shoulder,:2]-p[limb,:2]))*1.35
        scale = max(scale,20.)
        raised, waving = [], False
        for shoulder, elbow, wrist in ((5,7,9),(6,8,10)):
            up = visible(shoulder,wrist) and p[wrist,1] < p[shoulder,1]-.15*scale
            raised.append(up)
            history = self.history[wrist]
            if not up:
                history.clear()
                continue
            if history and now-history[-1][0] > .6:
                history.clear()
            reference = elbow if visible(elbow) else shoulder
            if history and history[-1][2] != reference:
                history.clear()
            history.append((now,float((p[wrist,0]-p[reference,0])/scale),reference))
            while history and now-history[0][0] > 1.8:
                history.popleft()
            if len(history) >= 4 and history[-1][0]-history[0][0] >= .45:
                waving |= excursions([v[1] for v in history], .16) >= 1
        available = [(s,e,w) for s,e,w in ((5,7,9),(6,8,10)) if visible(s,w)]
        out = [abs(p[w,0]-p[s,0]) > .65*scale and abs(p[w,1]-p[s,1]) < .40*scale
               for s,e,w in available]
        hips = [visible(s,e,w) and p[w,1] > p[s,1]+.30*scale
                and abs(p[w,0]-p[s,0]) < .65*scale
                and abs(p[e,0]-p[s,0]) > .25*scale for s,e,w in available]
        crossed = False
        if visible(5,6,9,10):
            across = (p[6,:2]-p[5,:2])/scale
            down = np.array([-across[1],across[0]])
            if down[1] < 0:
                down = -down
            left = (p[9,:2]-p[5,:2])/scale
            right = (p[10,:2]-p[5,:2])/scale
            crossed = (np.dot(left,across) > .55 and np.dot(right,across) < .45
                       and -.15 <= np.dot(right,across)
                       and np.dot(left,across) <= 1.15
                       and all(.15 <= np.dot(wrist,down) <= 1.05 for wrist in (left,right)))
        label = ("waving" if waving else "both_hands_up" if len(available)==2 and all(raised)
                 else "hand_raised" if any(raised) else "arms_crossed" if crossed
                 else "arms_out" if len(out)==2 and all(out)
                 else "arm_out" if any(out) else "hands_on_hips" if len(hips)==2 and all(hips)
                 else "hand_on_hip" if any(hips) else "unknown")
        return self.stable.update(label)
