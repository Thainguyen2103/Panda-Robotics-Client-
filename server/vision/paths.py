"""Filesystem locations used by the vision subsystem."""
from pathlib import Path

from config import settings


MODEL_DIR = Path(settings.VISION_MODEL_DIR)
DATA_DIR = Path(settings.VISION_DATA_DIR)


def model_path(name: str | Path) -> Path:
    path = Path(name)
    return path if path.is_absolute() else MODEL_DIR / path


def data_path(name: str | Path) -> Path:
    path = Path(name)
    return path if path.is_absolute() else DATA_DIR / path
