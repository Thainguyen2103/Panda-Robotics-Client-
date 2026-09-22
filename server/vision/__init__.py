"""Public API for Moon's vision subsystem."""
from config import settings

from .body.gestures import ArmGestures
from .pipeline.engine import (
    VisionEngine,
    cv2,
    emotion_face_crop,
    empty_result,
    iou,
)
from .body.pose import ARM_EDGES, upper_body
from .face.analysis import FaceDetails, HeadMotion, ExpressionState
from .face.eyes import EyeState, distance_estimate, eye_geometry
from .face.gestures import HeadGestures
from .fusion import combined_actions, nearby_objects
from .hands.analysis import HAND_EDGES, HandDetails, finger_gesture, finger_states
from .paths import MODEL_DIR, DATA_DIR, model_path, data_path
from .runtime.camera import LatestFrame, camera_source, start_vision
from .stability import StableLabel

# Compatibility for older tools that treated the source directory as model data.
BASE = MODEL_DIR

__all__ = [
    "ARM_EDGES", "BASE", "DATA_DIR", "HAND_EDGES", "MODEL_DIR",
    "ArmGestures", "EyeState", "ExpressionState", "FaceDetails",
    "HandDetails", "HeadGestures", "HeadMotion", "LatestFrame",
    "StableLabel", "VisionEngine", "camera_source", "combined_actions",
    "cv2", "data_path", "distance_estimate", "emotion_face_crop",
    "empty_result", "eye_geometry", "finger_gesture", "finger_states",
    "iou", "model_path", "nearby_objects", "settings", "start_vision", "upper_body",
]
