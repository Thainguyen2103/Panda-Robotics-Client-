"""Compatibility alias for ``server.voice.wakeword``."""
import importlib
import sys


_implementation = importlib.import_module("server.voice.wakeword")


sys.modules[__name__] = _implementation
