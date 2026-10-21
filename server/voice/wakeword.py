"""Compatibility alias for ``server.voice.wake.porcupine``."""
import importlib
import sys


_implementation = importlib.import_module("server.voice.wake.porcupine")


sys.modules[__name__] = _implementation
