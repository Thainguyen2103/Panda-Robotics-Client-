"""Eight-class metrics; missing classes are explicit, never silently omitted."""
import numpy as np

from .common import LABELS


def classification_metrics(expected, predicted):
    expected, predicted = np.asarray(expected), np.asarray(predicted)
    if expected.ndim != 1 or predicted.shape != expected.shape or not len(expected):
        raise ValueError('Need nonempty, equal-length one-dimensional predictions')
    if not np.isin(expected, range(8)).all() or not np.isin(predicted, range(8)).all():
        raise ValueError('Class IDs must be 0..7')
    matrix = np.zeros((8, 8), dtype=np.int64)
    np.add.at(matrix, (expected.astype(int), predicted.astype(int)), 1)
    per_class = {}
    for index, label in enumerate(LABELS):
        tp = int(matrix[index, index])
        support, guesses = int(matrix[index].sum()), int(matrix[:, index].sum())
        precision, recall = tp / guesses if guesses else 0., tp / support if support else 0.
        per_class[label] = dict(support=support, precision=precision, recall=recall,
            f1=2 * precision * recall / (precision + recall) if precision + recall else 0.)
    return dict(samples=len(expected), accuracy=float(np.trace(matrix) / matrix.sum()),
        macro_f1=float(np.mean([c['f1'] for c in per_class.values()])),
        balanced_accuracy=float(np.mean([c['recall'] for c in per_class.values()])),
        macro_classes=8, complete_eight_classes=all(c['support'] for c in per_class.values()),
        labels=list(LABELS), confusion_matrix=matrix.tolist(), per_class=per_class)
