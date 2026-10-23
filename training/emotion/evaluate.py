"""Compare ONNX classifiers on identical face crops, without detection/fusion."""
import argparse
import csv
import json
from pathlib import Path
import platform
import time

import cv2
import numpy as np

from .common import LABELS, sha256, write_json
from .data import load_split, resize_faces
from .metrics import classification_metrics


def compare(data, models, output, split='validation', threads=2, warmup=20):
    if threads < 1 or warmup < 0:
        raise ValueError('Invalid thread/warmup count')
    if not models or len({name for name, _ in models}) != len(models):
        raise ValueError('Model names must be nonempty and unique')
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError('Comparison directory already contains files; choose a new directory')
    images, targets, ids, manifest = load_split(data, split)
    faces = resize_faces(images).astype(np.float32)[:, None]
    expected = targets.argmax(1)
    cv2.setNumThreads(threads)
    reports = []
    for name, path in models:
        path = Path(path)
        metadata_path = path.with_suffix('.onnx.json')
        metadata = json.loads(metadata_path.read_text(encoding='utf-8')) if metadata_path.exists() else None
        if metadata and (metadata['labels'] != list(LABELS)
                or metadata['model_sha256'] != sha256(path)
                or metadata['dataset_fingerprint'] != manifest['fingerprint']):
            raise ValueError(f'Custom model metadata/label/data mismatch: {name}')
        net = cv2.dnn.readNetFromONNX(str(path))
        net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)

        def infer(batch):
            net.setInput(batch)
            logits = net.forward().reshape(-1)
            if logits.shape != (8,) or not np.isfinite(logits).all():
                raise ValueError(f'{name}: expected eight finite logits')
            return logits

        for index in range(warmup):
            infer(faces[index % len(faces):index % len(faces) + 1])
        predictions, timings, scores = [], [], []
        for face in faces:
            began = time.perf_counter()
            logits = infer(face[None])
            timings.append((time.perf_counter() - began) * 1000)
            scores.append(logits.tolist())
            predictions.append(int(logits.argmax()))
        reports.append(dict(name=name, model=str(path), sha256=sha256(path), bytes=path.stat().st_size,
            metrics=classification_metrics(expected, predictions), metadata=metadata,
            timing_ms=dict(median=float(np.median(timings)), p95=float(np.percentile(timings, 95)),
                           scope='setInput+forward+finite_check; batch=1; excludes resize/detection/fusion', warmup=warmup),
            predictions=[dict(id=str(i), expected=LABELS[int(y)], predicted=LABELS[p], logits=s)
                         for i, y, p, s in zip(ids, expected, predictions, scores)]))
    result = dict(schema=1, evaluation='direct_face_classification_no_detection_no_fusion', split=split,
        labels=list(LABELS), protocol=manifest['protocol'], dataset_fingerprint=manifest['fingerprint'],
        dataset_manifest=manifest,
        environment=dict(backend='opencv_dnn_cpu', opencv=cv2.__version__, numpy=np.__version__,
                         machine=platform.machine(), processor=platform.processor(), threads=threads),
        notes=['Same accepted samples, resize and raw pixel range for every model.',
               'Eight-class macro metrics include zero for absent classes; inspect complete_eight_classes.',
               'Do not infer webcam accuracy, temporal stability or GPU speed from this report.'],
        models=reports)
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / 'comparison.json', result)
    with (output / 'summary.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=['name', 'accuracy', 'macro_f1', 'balanced_accuracy',
                                                   'median_ms', 'p95_ms', 'bytes', 'complete_eight_classes'])
        writer.writeheader()
        for report in reports:
            writer.writerow(dict(name=report['name'], bytes=report['bytes'],
                **{key: report['metrics'][key] for key in ('accuracy', 'macro_f1', 'balanced_accuracy', 'complete_eight_classes')},
                median_ms=report['timing_ms']['median'], p95_ms=report['timing_ms']['p95']))
    print((output / 'summary.csv').read_text(encoding='utf-8'), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--model', action='append', required=True, metavar='NAME=PATH')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--split', choices=('validation', 'test'), default='validation')
    parser.add_argument('--threads', type=int, default=2)
    parser.add_argument('--warmup', type=int, default=20)
    args = parser.parse_args()
    models = []
    for spec in args.model:
        name, separator, path = spec.partition('=')
        if not separator or not name.strip() or not path:
            parser.error('--model must be NAME=PATH')
        models.append((name.strip(), Path(path)))
    compare(args.data, models, args.output, args.split, args.threads, args.warmup)


if __name__ == '__main__':
    main()
