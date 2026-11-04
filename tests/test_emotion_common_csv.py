import csv
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from training.emotion.common import sha256, write_json, CSV_PROTOCOL
from training.emotion.common_csv import prepare_csv
from training.emotion.data import load_split

class CommonCsvTests(unittest.TestCase):
    def fixture(self, root, duplicate=False):
        src=root/'csv';src.mkdir()
        for i,name in enumerate(('train.csv','val.csv','test.csv')):
            pixels=' '.join([str(10 if duplicate else 10+i)]*2304)
            identity=__import__('hashlib').sha256(pixels.encode()).hexdigest()
            with (src/name).open('w',newline='',encoding='utf-8') as f:
                w=csv.writer(f);w.writerow(['image_id','pixels','label_id','label_name','soft_label'])
                w.writerow([identity,pixels,0,'Neutral','0.666667 0.333333 0 0 0 0 0 0'])
        lock=root/'lock.json';write_json(lock,dict(sources={n:sha256(src/n) for n in ('train.csv','val.csv','test.csv')},counts=dict(train=1,validation=1,test=1)))
        return src,lock
    def test_import_preserves_ids_targets_and_protocol(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);src,lock=self.fixture(root);out=root/'prepared'
            m=prepare_csv(src,out,lock)
            images,targets,ids,_=load_split(out,'test')
            self.assertEqual(m['protocol'],CSV_PROTOCOL)
            self.assertEqual(images[0,0,0],12)
            with (src/'test.csv').open() as stream:
                self.assertEqual(ids[0], next(csv.DictReader(stream))['image_id'])
            np.testing.assert_allclose(targets.sum(1),1)
    def test_changed_source_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);src,lock=self.fixture(root)
            with (src/'test.csv').open('a') as f:f.write('\n')
            with self.assertRaisesRegex(ValueError,'hashes'):prepare_csv(src,root/'out',lock)
            self.assertFalse((root/'out').exists())
    def test_cross_split_duplicate_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);src,lock=self.fixture(root,True)
            with self.assertRaisesRegex(ValueError,'duplicate'):prepare_csv(src,root/'out',lock)

    def test_new_protocol_train_resume_export_and_predictions(self):
        from training.emotion.train import train, parse_args, load_checkpoint
        from training.emotion.export import export
        from training.emotion.evaluate import compare
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);src,lock=self.fixture(root);data=root/'data'
            prepare_csv(src,data,lock)
            args=['--data',str(data),'--output',str(root/'run'),'--mode','soft',
                  '--epochs','2','--device','cpu','--threads','1']
            train(parse_args([*args,'--session-epochs','1']))
            train(parse_args([*args,'--resume']))
            state=load_checkpoint(root/'run'/'best.pt')
            self.assertEqual(state['protocol'],CSV_PROTOCOL)
            model=root/'model.onnx'
            meta=export(root/'run'/'best.pt',data,model,samples=1)
            self.assertEqual(meta['protocol'],CSV_PROTOCOL)
            compare(data,[('new',model)],root/'report',warmup=0)
            with (root/'report'/'predictions.csv').open() as stream:
                rows=list(csv.DictReader(stream))
            self.assertEqual(len(rows),1)
            self.assertAlmostEqual(sum(float(rows[0]['p_'+label]) for label in
                ('neutral','happy','surprised','sad','angry','disgust','fear','contempt')),1)

if __name__=='__main__':unittest.main()
