"""Public, backward-compatible API for Moon's voice subsystem.

The device-heavy local runtime is loaded only when one of its attributes is
actually requested. Importing ``server.voice.core`` therefore stays free of
microphone, MQTT, TTS and network side effects.
"""
import importlib
import sys
import types


_RUNTIME_NAME = f"{__name__}.runtime.local"


def _runtime_module():
    return importlib.import_module(".runtime.local", __name__)


def __getattr__(name):
    runtime = _runtime_module()
    try:
        return getattr(runtime, name)
    except AttributeError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc


class _VoiceFacade(types.ModuleType):
    """Forward assignments to legacy private state after the runtime is loaded."""
    def __setattr__(self, name, value):
        if name.startswith("_") and name not in {
            "__all__", "__class__", "__spec__", "__path__",
        }:
            runtime = sys.modules.get(_RUNTIME_NAME)
            if runtime is not None and hasattr(runtime, name):
                setattr(runtime, name, value)
        super().__setattr__(name, value)


__all__ = [
    "continuous_listen_loop",
    "external_mic_active",
    "listen_for_question",
    "pause_listening",
    "register_callbacks",
    "resume_listening",
    "set_external_mic",
    "transcribe_bytes",
]

sys.modules[__name__].__class__ = _VoiceFacade
