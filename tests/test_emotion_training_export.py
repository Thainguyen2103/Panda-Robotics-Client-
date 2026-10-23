"""Synthetic end-to-end export/parity/benchmark; not an accuracy measurement."""
import json
from pathlib import Path
import tempfile
import unittest

from test_emotion_training_data import make_csvs
from training.emotion.data import prepare
from training.emotion.evaluate import compare
from training.emotion.export import export
from training.emotion.train import parse_args, train


class TrainingExportTests(unittest.TestCase):
    def test_export_opencv_parity_and_identical_comparison_samples(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fer, plus = make_csvs(root)
            prepare(fer, plus, root / 'data')
            train(parse_args(['--data', str(root / 'data'), '--output', str(root / 'run'),
                              '--mode', 'hard', '--epochs', '1', '--device', 'cpu', '--threads', '1']))
            model = root / 'custom.onnx'
            metadata = export(root / 'run' / 'best.pt', root / 'data', model, samples=1)
            self.assertEqual(metadata['input']['range'], [0, 255])
            self.assertLess(metadata['parity']['opencv_max_abs_error'], .001)
            models = [('custom', model), ('identical_copy', model)]
            result = compare(root / 'data', models, root / 'comparison', warmup=1)
            self.assertEqual(result['split'], 'validation')
            self.assertEqual(result['models'][0]['predictions'], result['models'][1]['predictions'])
            self.assertTrue((root / 'comparison' / 'summary.csv').is_file())
            self.assertFalse(result['models'][0]['metrics']['complete_eight_classes'])
            with self.assertRaisesRegex(ValueError, 'Export exists'):
                export(root / 'run' / 'best.pt', root / 'data', model)
            sidecar = model.with_suffix('.onnx.json')
            metadata['labels'].reverse()
            sidecar.write_text(json.dumps(metadata), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'metadata/label/data mismatch'):
                compare(root / 'data', [('bad', model)], root / 'invalid')


if __name__ == '__main__':
    unittest.main()
