"""Evaluate labeled face photos locally, without a camera, MQTT or saving photos.

Dataset layout: ROOT/{neutral,happy,surprised,sad,angry,disgust,fear,contempt}/*.
Frame-level candidates are evaluated without pretending a repeated photo is video.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from config import settings
from server.vision.face.analysis import EMOTIONS, FaceDetails, expression_decision
from server.vision.paths import model_path
from server.vision.pipeline.engine import cv2, emotion_probabilities

IMAGE_EXTENSIONS = {'.jpg','.jpeg','.png','.bmp','.webp'}


def classification_metrics(expected, predicted):
    """Unknown predictions count as misses, including in macro F1 and recall."""
    if len(expected) != len(predicted):
        raise ValueError('Expected and predicted lengths differ')
    columns = (*EMOTIONS,'unknown')
    matrix = {label:{column:0 for column in columns} for label in EMOTIONS}
    for actual,guess in zip(expected,predicted):
        matrix[actual][guess] += 1
    per_class = {}
    for label in EMOTIONS:
        tp = matrix[label][label]
        support = sum(matrix[label].values())
        guessed = sum(row[label] for row in matrix.values())
        precision = tp/guessed if guessed else 0.
        recall = tp/support if support else 0.
        per_class[label] = dict(support=support,precision=precision,recall=recall,
            f1=2*precision*recall/(precision+recall) if precision+recall else 0.)
    total = len(expected)
    present = [values for values in per_class.values() if values['support']]
    return dict(samples=total,accuracy=sum(a==b for a,b in zip(expected,predicted))/total if total else None,
        coverage=sum(label!='unknown' for label in predicted)/total if total else None,
        macro_f1=sum(values['f1'] for values in present)/len(present) if present else None,
        balanced_accuracy=sum(values['recall'] for values in present)/len(present) if present else None,
        macro_classes=len(present),complete_eight_classes=len(present)==len(EMOTIONS),
        per_class=per_class,confusion_matrix=matrix)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset',type=Path)
    parser.add_argument('--output',type=Path,help='Optional JSON report; contains relative image filenames, no images')
    parser.add_argument('--model',type=Path,help='Override the ONNX classifier for this evaluation only')
    parser.add_argument('--allow-partial',action='store_true',help='Allow missing emotion classes; report clearly marks partial results')
    args = parser.parse_args()
    samples = [(path,label) for label in EMOTIONS for path in sorted((args.dataset/label).rglob('*'))
               if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS]
    if not samples:
        parser.error('No labeled images found. Use one subfolder per canonical emotion label.')
    missing = sorted(set(EMOTIONS)-{label for _,label in samples})
    if missing and not args.allow_partial:
        parser.error('Missing emotion classes: '+', '.join(missing)+'. Use --allow-partial for a limited diagnostic.')
    if cv2 is None:
        parser.error('OpenCV is required')
    cv2.setNumThreads(settings.VISION_CV_THREADS)
    detector = cv2.FaceDetectorYN_create(str(model_path('face_detection_yunet_2023mar.onnx')),
        '',(320,320),settings.VISION_FACE_THRESHOLD)
    emotion_model = args.model if args.model is not None else settings.EMOTION_MODEL
    model = cv2.dnn.readNetFromONNX(str(model_path(emotion_model)))
    details = FaceDetails(model_path(settings.VISION_FACE_DETAILS_MODEL),video=False) if settings.VISION_FACE_DETAILS_ENABLED else None
    rows,timings,failures = [],[],Counter()
    try:
        for index,(path,label) in enumerate(samples):
            began = time.monotonic()
            row = dict(file=str(path.relative_to(args.dataset)),expected=label,
                       fer_argmax='unknown',fused_candidate='unknown',source='uncertain')
            try:
                # imdecode supports Windows Unicode paths where imread may fail.
                frame = cv2.imdecode(np.fromfile(path,dtype=np.uint8),cv2.IMREAD_COLOR)
                if frame is None:
                    raise ValueError('unreadable_image')
                # Match the camera's working resolution, then its YuNet resolution.
                scale = min(1.,settings.VISION_WIDTH/frame.shape[1],settings.VISION_HEIGHT/frame.shape[0])
                if scale < 1:
                    frame = cv2.resize(frame,(max(1,int(frame.shape[1]*scale)),max(1,int(frame.shape[0]*scale))))
                scale = min(1.,settings.VISION_FACE_WIDTH/frame.shape[1])
                small = cv2.resize(frame,(max(1,int(frame.shape[1]*scale)),max(1,int(frame.shape[0]*scale)))) if scale < 1 else frame
                detector.setInputSize((small.shape[1],small.shape[0]))
                faces = detector.detect(small)[1]
                if faces is None:
                    raise ValueError('no_face')
                faces = faces.copy()
                faces[:,:14] /= scale
                faces = [face for face in faces if np.isfinite(face).all() and min(face[2:4]) >= settings.VISION_MIN_FACE_SIZE]
                if len(faces) != 1:
                    raise ValueError('multiple_faces' if len(faces)>1 else 'face_too_small')
                face = faces[0]
                probs = emotion_probabilities(model,frame,face)
                # IMAGE mode prevents tracking history leaking between subjects.
                motion = details.detect(frame,face[:4],index+1.) if details else None
                cues = motion['cues'] if motion else {}
                candidate,_,source = expression_decision(probs,cues)
                row.update(fer_argmax=EMOTIONS[int(np.argmax(probs))],fused_candidate=candidate,source=source,
                    landmark_available=bool(cues),fer_probs={name:float(value) for name,value in zip(EMOTIONS,probs)})
            except Exception as exc:
                row['error'] = str(exc)
                failures[str(exc)] += 1
            rows.append(row)
            timings.append((time.monotonic()-began)*1000)
    finally:
        if details is not None:
            details.close()
    expected = [row['expected'] for row in rows]
    report = dict(evaluation='independent_images_no_temporal_confirmation',
        notes='FER argmax and fused candidates use the same new preprocessing. This is not a before/after accuracy benchmark. Failures count as unknown; macro averages use present classes.',
        missing_classes=missing,model=str(emotion_model),
        model_sha256={name:hashlib.sha256(model_path(name).read_bytes()).hexdigest()
            for name in (str(emotion_model),'face_detection_yunet_2023mar.onnx',
                         *((settings.VISION_FACE_DETAILS_MODEL,) if settings.VISION_FACE_DETAILS_ENABLED else ()))},
        configuration=dict(opencv=cv2.__version__,numpy=np.__version__,
            face_threshold=settings.VISION_FACE_THRESHOLD,min_face_size=settings.VISION_MIN_FACE_SIZE,
            fer_threshold=settings.VISION_EMOTION_THRESHOLD,fer_margin=settings.VISION_EMOTION_MARGIN,
            align_roll=settings.VISION_EMOTION_ALIGN_ROLL,landmarks=settings.VISION_FACE_DETAILS_ENABLED),
        fer_argmax=classification_metrics(expected,[row['fer_argmax'] for row in rows]),
        fused_candidate=classification_metrics(expected,[row['fused_candidate'] for row in rows]),
        failures=dict(failures),median_ms=float(np.median(timings)),p95_ms=float(np.percentile(timings,95)),samples=rows)
    serialized = json.dumps(report,ensure_ascii=False,indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(serialized+'\n',encoding='utf-8')
    print(serialized)
    return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(main())
