"""Filesystem locations used by the voice subsystem."""
from pathlib import Path

from config import settings


MODEL_DIR = Path(settings.VOICE_MODEL_DIR)


def wake_model_path() -> Path:
    """Return the configured Porcupine model without touching the filesystem."""
    configured = str(settings.MOON_PPN_PATH or "").strip()
    return Path(configured).expanduser().resolve() if configured else MODEL_DIR / "moon.ppn"
