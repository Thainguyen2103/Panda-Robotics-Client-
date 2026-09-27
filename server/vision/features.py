"""Compatibility facade for facial and upper-body features."""
from server.vision.body.pose import ARM_EDGES, JOINT_NAMES, upper_body
from server.vision.face.analysis import (
    ExpressionState, FaceDetails, HeadMotion, combined_emotion_scores,
    emotion_candidate, expression_intensities,
)

__all__ = [
    "ARM_EDGES", "JOINT_NAMES", "ExpressionState", "FaceDetails", "HeadMotion",
    "combined_emotion_scores", "emotion_candidate", "expression_intensities",
    "upper_body",
]
