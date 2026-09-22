"""Public API for Moon's vision subsystem."""
from config import settings

from .engine import (
    ArmGestures,
    HeadGestures,
    StableLabel,
    VisionEngine,
    cv2,
    emotion_face_crop,
    empty_result,
    iou,
)
from .features import FaceDetails, HeadMotion, ExpressionState, upper_body, ARM_EDGES
from .paths import MODEL_DIR, DATA_DIR, model_path, data_path
from .runtime import LatestFrame, camera_source, start_vision
from .signals import (
    EyeState,
    HandDetails,
    HAND_EDGES,
    combined_actions,
    distance_estimate,
    eye_geometry,
    finger_gesture,
    finger_states,
    nearby_objects,
)

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
