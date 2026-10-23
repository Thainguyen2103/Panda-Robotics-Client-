"""Export raw-pixel ONNX and require numerical parity in ORT and OpenCV."""
import argparse
import os
from pathlib import Path

import cv2
import numpy as np
import onnx
import onnxruntime as ort
import torch

from .common import LABELS, PROTOCOL, sha256, write_json
from .data import load_split, resize_faces
from .model import EmotionCNN
from .train import load_checkpoint


def export(checkpoint, data, output, samples=16):
    if samples < 1:
        raise ValueError('Need at least one validation sample for parity')
    output = Path(output)
    if output.exists():
        raise ValueError('Export exists; choose a new versioned filename')
    state = load_checkpoint(checkpoint)
    images, _, ids, manifest = load_split(data, 'validation')
    if manifest['fingerprint'] != state['config']['dataset_fingerprint']:
        raise ValueError('Export validation data differs from the training dataset')
    torch.set_num_threads(2)
    cv2.setNumThreads(2)
    model = EmotionCNN().eval()
    model.load_state_dict(state['model'])
    faces = resize_faces(images[:samples]).astype(np.float32)[:, None]
    # Boundary probes catch accidental double normalization and invalid ranges.
    probes = np.stack([np.zeros((1, 64, 64), np.float32),
                       np.full((1, 64, 64), 255, np.float32),
                       np.linspace(0, 255, 4096, dtype=np.float32).reshape(1, 64, 64)])
    checks = np.concatenate([faces, probes])
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.stem + '.tmp.onnx')
    try:
        # Fixed batch=1 and opset 13 for the project's cv2.dnn runtime.
        torch.onnx.export(model, torch.from_numpy(checks[:1]), str(temporary),
            input_names=['pixels'], output_names=['logits'], opset_version=13,
            dynamo=False, external_data=False)
        graph = onnx.load(str(temporary))
        onnx.checker.check_model(graph)
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        session = ort.InferenceSession(str(temporary), sess_options=options,
                                       providers=['CPUExecutionProvider'])
        net = cv2.dnn.readNetFromONNX(str(temporary))
        net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        ort_error, opencv_error = 0., 0.
        with torch.inference_mode():
            for face in checks:
                batch = face[None]
                expected = model(torch.from_numpy(batch)).numpy()
                actual = session.run(None, {'pixels': batch})[0]
                net.setInput(batch)
                live = net.forward()
                np.testing.assert_allclose(actual, expected, rtol=1e-3, atol=1e-4)
                np.testing.assert_allclose(live, expected, rtol=1e-3, atol=1e-4)
                ort_error = max(ort_error, float(np.max(np.abs(actual - expected))))
                opencv_error = max(opencv_error, float(np.max(np.abs(live - expected))))
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    metadata = dict(schema=1, architecture=state['architecture'], protocol=PROTOCOL,
        labels=list(LABELS), input=dict(shape=[1, 1, 64, 64], dtype='float32', range=[0, 255]),
        normalization='inside_graph: pixels / 127.5 - 1', output='eight_logits_no_softmax',
        checkpoint_sha256=sha256(checkpoint), model_sha256=sha256(output),
        dataset_fingerprint=manifest['fingerprint'], training=state['config'], epoch=state['epoch'],
        best_validation_macro_f1=state['best_score'],
        parity=dict(validation_ids=ids[:samples].tolist(), boundary_probes=3,
                    ort_max_abs_error=ort_error, opencv_max_abs_error=opencv_error,
                    rtol=1e-3, atol=1e-4, opencv=cv2.__version__, onnxruntime=ort.__version__))
    write_json(output.with_suffix('.onnx.json'), metadata)
    print(f'Exported and verified: {output}', flush=True)
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--samples', type=int, default=16)
    args = parser.parse_args()
    export(args.checkpoint, args.data, args.output, args.samples)


if __name__ == '__main__':
    main()
