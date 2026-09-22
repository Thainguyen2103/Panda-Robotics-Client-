"""Temporal head gestures derived from stable face landmarks."""
from collections import deque

import numpy as np


def excursions(values, threshold):
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
    """Temporal landmark ratios for a frontal face."""
    def __init__(self):
        self.history = deque()
        self.last_event = -float("inf")

    def reset(self):
        self.history.clear()
        self.last_event = -float("inf")

    def update(self, face, now):
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
