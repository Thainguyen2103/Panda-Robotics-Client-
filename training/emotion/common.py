"""Stable artifact formats shared by offline commands (no robot imports)."""
import hashlib
import json
import os
from pathlib import Path

LABELS = ('neutral', 'happy', 'surprised', 'sad', 'angry', 'disgust', 'fear', 'contempt')
PROTOCOL = 'ferplus-shared-v1'
SPLITS = {'Training': 'train', 'PublicTest': 'validation', 'PrivateTest': 'test'}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                    allow_nan=False) + '\n', encoding='utf-8')
    os.replace(temporary, path)
