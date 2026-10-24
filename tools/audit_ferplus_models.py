"""Verify every example and evaluation row from original pixels and ONNX."""
import argparse, csv, hashlib, io, json, sys, urllib.request
from collections import Counter
from pathlib import Path
import cv2
import numpy as np
import onnxruntime as ort
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from training.emotion.data import VOTE_COLUMNS, vote_target
from training.emotion.metrics import classification_metrics

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--fer2013',type=Path,required=True)
parser.add_argument('--source-report',type=Path,required=True)
parser.add_argument('--model-dir',type=Path,required=True)
parser.add_argument('--baseline',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
out=args.output
if out.exists() and any(out.iterdir()):raise ValueError('Use a new empty output directory')
out.mkdir(parents=True,exist_ok=True)
base=args.model_dir
old=json.loads(args.source_report.read_text(encoding='utf-8'));manifest=old['dataset_manifest'];labels=old['labels']
source=args.fer2013
assert hashlib.sha256(source.read_bytes()).hexdigest()==manifest['sources']['fer2013']
annotation_bytes=urllib.request.urlopen('https://raw.githubusercontent.com/microsoft/FERPlus/master/fer2013new.csv',timeout=30).read()
assert hashlib.sha256(annotation_bytes).hexdigest()==manifest['sources']['ferplus']
ann=list(csv.DictReader(io.StringIO(annotation_bytes.decode('utf-8-sig'))))
wanted={int(p['id'][3:-4]):p for p in old['models'][0]['predictions']}
images=[];samples=[]
with source.open(newline='',encoding='utf-8-sig') as stream:
    for i,row in enumerate(csv.DictReader(stream)):
        if i not in wanted:continue
        assert row['Usage']==ann[i]['Usage']=='PrivateTest'
        votes=[int(ann[i][key]) for key in VOTE_COLUMNS]
        target,reason=vote_target(votes)
        assert reason is None and labels[int(target.argmax())]==wanted[i]['expected']
        pixels=np.fromstring(row['pixels'],sep=' ',dtype=np.uint8).reshape(48,48)
        images.append(pixels)
        samples.append({'row_index':i,'row_id':wanted[i]['id'],'annotation_name':ann[i]['Image name'],
            'pixel_sha256':hashlib.sha256(pixels.tobytes()).hexdigest(),'votes':votes,
            'target':target.tolist(),'expected':int(target.argmax()),'predictions':[]})
assert [s['row_id'] for s in samples]==[p['id'] for p in old['models'][0]['predictions']]
images=np.stack(images)
np.savez_compressed(out/'test-images.npz',images=images)
excluded={p['id'] for group in manifest['cross_split_duplicate_groups'] if any(s['split'] in ('train','validation') for s in group['samples']) for p in group['samples'] if p['split']=='test'}
keep=[i for i,s in enumerate(samples) if s['row_id'] not in excluded]
results=[];cv2.setNumThreads(2)
for model_index,name in enumerate(('pretrained','hard-seed42','soft-seed42')):
    path=args.baseline if model_index==0 else base/(name+'.onnx')
    assert hashlib.sha256(path.read_bytes()).hexdigest()==old['models'][model_index]['sha256']
    net=cv2.dnn.readNetFromONNX(str(path)); logits_all=[]
    for i,image in enumerate(images):
        face=(np.asarray(Image.fromarray(image).resize((64,64),Image.Resampling.LANCZOS)) if model_index==0
              else cv2.resize(image,(64,64),interpolation=cv2.INTER_AREA))
        blob=face.astype(np.float32)[None,None]
        net.setInput(blob);logits=net.forward().reshape(-1)
        assert logits.size==8 and np.isfinite(logits).all()
        probs=np.exp(logits-logits.max());probs/=probs.sum()
        samples[i]['predictions'].append({'class_id':int(probs.argmax()),'scores':probs.tolist()})
        logits_all.append(logits.copy())
        if (i+1)%1000==0:print(name,i+1,'/',len(images),flush=True)
    # Same fixed 32-sample runtime check for all three artifacts.
    options=ort.SessionOptions();options.intra_op_num_threads=2
    session=ort.InferenceSession(str(path),sess_options=options,providers=['CPUExecutionProvider'])
    disagreement=0;maximum=0.
    for i in np.random.default_rng(42).choice(len(images),32,replace=False):
        face=(np.asarray(Image.fromarray(images[i]).resize((64,64),Image.Resampling.LANCZOS)) if model_index==0
              else cv2.resize(images[i],(64,64),interpolation=cv2.INTER_AREA))
        output=session.run(None,{session.get_inputs()[0].name:face.astype(np.float32)[None,None]})[0].reshape(-1)
        maximum=max(maximum,float(abs(output-logits_all[i]).max()))
        disagreement+=int(output.argmax()!=logits_all[i].argmax())
    metrics={}
    for split,indices in [('full',list(range(len(images)))),('no_exact_overlap',keep)]:
        metrics[split]=classification_metrics([samples[i]['expected'] for i in indices],[samples[i]['predictions'][model_index]['class_id'] for i in indices])
    original_changes=sum(samples[i]['predictions'][model_index]['class_id']!=labels.index(p['predicted']) for i,p in enumerate(old['models'][model_index]['predictions']))
    if model_index>0:assert original_changes==0
    results.append({'name':name,'metrics':metrics,'sha256':old['models'][model_index]['sha256'],
        'resize':'PIL LANCZOS' if model_index==0 else 'OpenCV INTER_AREA',
        'opencv_ort_32_samples':{'disagreements':disagreement,'max_abs_logit_error':maximum},
        'changed_vs_old_report':original_changes})
counts=Counter();candidates={}
for i in keep:
    s=samples[i];pattern=''.join('1' if p['class_id']==s['expected'] else '0' for p in s['predictions'])
    counts[pattern]+=1;candidates.setdefault(pattern,[]).append(i)
chosen=[]
for pattern,description in [('011','A sai B và C đúng'),('100','A đúng B và C sai'),('001','Chỉ C đúng'),('000','Cả ba sai')]:
    pool=candidates.get(pattern,[])
    if not pool:continue
    idx=sorted(pool,key=lambda i:(-samples[i]['votes'][samples[i]['expected']]/max(1,sum(samples[i]['votes'])) ,samples[i]['row_index']))[0]
    s=samples[idx];s['case_pattern']=pattern;s['case_description']=description
    Image.fromarray(images[idx]).save(out/(s['row_id']+'.png'))
    chosen.append(s)
result={'date':'2026-10-24','labels':labels,'manifest':manifest,'source_report_sha256':hashlib.sha256(args.source_report.read_bytes()).hexdigest(),
    'runtime':{'opencv':cv2.__version__,'onnxruntime':ort.__version__,'backend':'OpenCV CPU','threads':2},
    'full_samples':len(images),'subset_samples':len(keep),'excluded_samples':len(excluded),'results':results,
    'correctness_patterns_subset':dict(sorted(counts.items())),'examples':chosen,
    'example_selection':'Within each specified correctness pattern on the no-exact-overlap subset, highest original FER+ reference-vote fraction, then smallest zero-based CSV row index.'}
(out/'audit.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
with (out/'predictions.jsonl').open('w',encoding='utf-8') as stream:
    for s in samples:stream.write(json.dumps(s,ensure_ascii=False)+'\n')
print('PATTERNS',counts,flush=True)
for s in chosen:print('EXAMPLE',s['row_id'],s['case_description'],'reference',labels[s['expected']],s['votes'],[(labels[p['class_id']],round(max(p['scores'])*100,2)) for p in s['predictions']],flush=True)
print('AUDIT COMPLETE',out/'audit.json',flush=True)
