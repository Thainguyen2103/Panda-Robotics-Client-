"""Small synthetic run verifies real optimization and exact epoch-boundary resume."""
from pathlib import Path
import tempfile
import unittest

import numpy as np
import torch

from test_emotion_training_data import make_csvs
from training.emotion.data import prepare
from training.emotion.model import EmotionCNN, FaceDataset
from training.emotion.train import load_checkpoint, parse_args, train


class TrainingRunTests(unittest.TestCase):
    def test_raw_pixel_contract_and_hard_soft_targets(self):
        torch.set_num_threads(1)
        images = np.full((1, 48, 48), 128, dtype=np.uint8)
        targets = np.array([[.6, .4, 0, 0, 0, 0, 0, 0]], dtype=np.float32)
        pixels, soft = FaceDataset(images, targets)[0]
        _, hard = FaceDataset(images, targets, 'hard')[0]
        self.assertEqual(tuple(pixels.shape), (1, 64, 64))
        self.assertEqual(float(pixels.max()), 128.)
        self.assertEqual(hard.tolist(), [1., 0., 0., 0., 0., 0., 0., 0.])
        self.assertAlmostEqual(float(soft[1]), .4)
        with torch.no_grad():
            output = EmotionCNN().eval()(pixels[None])
        self.assertEqual(tuple(output.shape), (1, 8))
        self.assertTrue(torch.isfinite(output).all())

    def test_resume_matches_uninterrupted_training_with_augmentation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fer, plus = make_csvs(root)
            prepare(fer, plus, root / 'data')
            common = ['--data', str(root / 'data'), '--mode', 'soft', '--epochs', '3',
                      '--batch-size', '2', '--device', 'cpu', '--threads', '1']
            train(parse_args([*common, '--output', str(root / 'full')]))
            train(parse_args([*common, '--output', str(root / 'resumed'), '--session-epochs', '1']))
            # Simulate a disconnect after last.pt was saved but before best.pt.
            (root / 'resumed' / 'best.pt').unlink()
            train(parse_args([*common, '--output', str(root / 'resumed'), '--resume']))
            full = load_checkpoint(root / 'full' / 'last.pt')
            resumed = load_checkpoint(root / 'resumed' / 'last.pt')
            self.assertEqual(full['history'], resumed['history'])
            self.assertEqual(full['epoch'], 3)
            for key, tensor in full['model'].items():
                torch.testing.assert_close(tensor, resumed['model'][key], rtol=0, atol=0)
            with self.assertRaisesRegex(ValueError, 'config or dataset changed'):
                train(parse_args([*common, '--output', str(root / 'resumed'), '--resume', '--lr', '.01']))


if __name__ == '__main__':
    unittest.main()
