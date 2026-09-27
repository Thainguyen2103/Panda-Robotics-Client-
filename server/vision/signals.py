"""Compatibility facade for observable face, hand and object signals."""
from server.vision.face.eyes import EyeState, distance_estimate, eye_geometry
from server.vision.fusion import combined_actions, nearby_objects
from server.vision.hands.analysis import (
    HAND_EDGES, HandDetails, angle, finger_gesture, finger_states,
)

__all__ = [
    "HAND_EDGES", "EyeState", "HandDetails", "angle", "combined_actions",
    "distance_estimate", "eye_geometry", "finger_gesture", "finger_states",
    "nearby_objects",
]
