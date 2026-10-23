"""Data alignment and leakage checks for offline training, using synthetic pixels."""
import csv
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from training.emotion.data import VOTE_COLUMNS, load_split, prepare, vote_target
from training.emotion.metrics import classification_metrics


def make_csvs(root):
    fer, plus = root / 'fer.csv', root / 'plus.csv'
    with fer.open('w', newline='') as left, plus.open('w', newline='') as right:
        a, b = csv.writer(left), csv.writer(right)
        a.writerow(['emotion', 'pixels', 'Usage'])
        b.writerow(['Usage', 'Image name', *VOTE_COLUMNS])
        for index, usage in enumerate(('Training', 'PublicTest', 'PrivateTest')):
            a.writerow([0, ' '.join(['128'] * 2304), usage])
            b.writerow([usage, f'fer{index:07d}.png', 6, 4, *([0] * 8)])
    return fer, plus


class TrainingDataTests(unittest.TestCase):
    def test_soft_votes_and_rejection_of_unknown_ties_and_singletons(self):
        target, reason = vote_target([6, 4, 0, 0, 0, 0, 0, 0, 0, 0])
        np.testing.assert_allclose(target[:2], [.6, .4])
        self.assertIsNone(reason)
        for votes, expected in (([1] * 10, 'no_votes_after_singletons'),
                ([4, 4, 0, 0, 0, 0, 0, 0, 2, 0], 'tied_top_emotion'),
                ([4, 0, 0, 0, 0, 0, 0, 0, 6, 0], 'unknown_or_nonface')):
            self.assertEqual(vote_target(votes), (None, expected))
        with self.assertRaises(ValueError):
            vote_target([float('nan')] * 10)

    def test_splits_identity_duplicates_and_checksum(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fer, plus = make_csvs(root)
            manifest = prepare(fer, plus, root / 'prepared')
            self.assertEqual(manifest['raw_rows'], 3)
            self.assertTrue(manifest['has_cross_split_duplicates'])
            images, targets, ids, _ = load_split(root / 'prepared', 'test')
            self.assertEqual(images.shape, (1, 48, 48))
            self.assertEqual(ids.tolist(), ['fer0000002.png'])
            self.assertAlmostEqual(float(targets[0, 0]), .6)
            with (root / 'prepared' / 'test.npz').open('ab') as stream:
                stream.write(b'changed')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                load_split(root / 'prepared', 'test')

    def test_shifted_or_missing_rows_fail_before_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fer, plus = make_csvs(root)
            text = plus.read_text().replace('fer0000001.png', 'invalid.png')
            plus.write_text(text)
            with self.assertRaisesRegex(ValueError, 'Invalid or duplicate'):
                prepare(fer, plus, root / 'out')
            self.assertFalse((root / 'out').exists())
            plus.write_text('\n'.join(text.splitlines()[:-1]) + '\n')
            # Restore identity so the test reaches the missing-row check.
            plus.write_text(plus.read_text().replace('invalid.png', 'fer0000001.png'))
            with self.assertRaisesRegex(ValueError, 'row counts differ'):
                prepare(fer, plus, root / 'out')

    def test_annotation_filename_need_not_equal_csv_row_index(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fer, plus = make_csvs(root)
            plus.write_text(plus.read_text().replace('fer0000001.png', 'fer0000060.png'))
            prepare(fer, plus, root / 'prepared')
            _, _, ids, _ = load_split(root / 'prepared', 'validation')
            self.assertEqual(ids.tolist(), ['fer0000001.png'])

    def test_metrics_include_all_eight_classes(self):
        metrics = classification_metrics([0, 1, 1], [0, 0, 1])
        self.assertAlmostEqual(metrics['accuracy'], 2 / 3)
        self.assertAlmostEqual(metrics['macro_f1'], 1 / 6)
        self.assertFalse(metrics['complete_eight_classes'])
        self.assertEqual(metrics['per_class']['contempt']['support'], 0)
        self.assertEqual(metrics['confusion_matrix'][1][0], 1)
        complete = classification_metrics(list(range(8)), list(range(8)))
        self.assertTrue(complete['complete_eight_classes'])
        self.assertEqual(complete['macro_f1'], 1.)


if __name__ == '__main__':
    unittest.main()
