"""Import the frozen common CSV split without filtering, shuffling or resplitting."""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from .common import CSV_PROTOCOL, LABELS, sha256, write_json

CSV_NAMES = ('Neutral', 'Happiness', 'Surprise', 'Sadness', 'Anger', 'Disgust', 'Fear', 'Contempt')
LOCK = Path(__file__).with_name('common_csv_lock.json')


def prepare_csv(source, output, lock_path=LOCK):
    source, output = Path(source), Path(output)
    if output.exists():
        raise ValueError('Use a new prepared directory; never overwrite an experiment')
    lock = json.loads(Path(lock_path).read_text(encoding='utf-8'))
    sources = {name: sha256(source / name) for name in ('train.csv', 'val.csv', 'test.csv')}
    if sources != lock['sources']:
        raise ValueError('CSV hashes differ from the agreed dataset. Do not silently accept a new split.')
    buckets, seen, pixels_seen, dhashes = {}, set(), set(), defaultdict(list)
    for split, filename in (('train', 'train.csv'), ('validation', 'val.csv'), ('test', 'test.csv')):
        rows = []
        with (source / filename).open(newline='', encoding='utf-8-sig') as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != ['image_id', 'pixels', 'label_id', 'label_name', 'soft_label']:
                raise ValueError(f'Unexpected CSV columns: {filename}')
            for line, row in enumerate(reader, 2):
                tokens = row['pixels'].split()
                values = np.array([int(t) for t in tokens], dtype=np.int64)
                if values.shape != (2304,) or (values < 0).any() or (values > 255).any():
                    raise ValueError(f'Invalid pixels at {filename}:{line}')
                identity = hashlib.sha256(' '.join(tokens).encode()).hexdigest()
                image = values.astype(np.uint8).reshape(48, 48)
                pixel_hash = hashlib.sha256(image.tobytes()).hexdigest()
                if identity != row['image_id'] or identity in seen or pixel_hash in pixels_seen:
                    raise ValueError(f'Invalid or duplicate image at {filename}:{line}')
                seen.add(identity)
                pixels_seen.add(pixel_hash)
                target = np.array([float(t) for t in row['soft_label'].split()], dtype=np.float64)
                label = int(row['label_id'])
                if (target.shape != (8,) or not np.isfinite(target).all() or (target < 0).any()
                        or abs(target.sum() - 1) > 1e-5 or not 0 <= label < 8
                        or target.argmax() != label or np.count_nonzero(target == target.max()) != 1
                        or row['label_name'] != CSV_NAMES[label]):
                    raise ValueError(f'Invalid label at {filename}:{line}')
                target = (target / target.sum()).astype(np.float32)
                rows.append((image, target, identity))
                small = cv2.resize(image, (9, 8), interpolation=cv2.INTER_AREA)
                key = np.packbits(small[:, 1:] > small[:, :-1]).tobytes()
                dhashes[key].append((split, identity, image))
        if len(rows) != lock['counts'][split]:
            raise ValueError(f'Unexpected row count: {filename}')
        buckets[split] = rows
    near = []
    for group in dhashes.values():
        for i, (left_split, left_id, left) in enumerate(group):
            for right_split, right_id, right in group[i+1:]:
                if left_split != right_split:
                    mad = float(np.abs(left.astype(np.int16) - right.astype(np.int16)).mean())
                    if mad <= 15:
                        near.append(dict(left_split=left_split, left_id=left_id,
                                         right_split=right_split, right_id=right_id, mad=mad))
    identity_data = dict(protocol=CSV_PROTOCOL, sources=sources, labels=list(LABELS))
    fingerprint = hashlib.sha256(json.dumps(identity_data, sort_keys=True).encode()).hexdigest()
    manifest = dict(schema=1, **identity_data, fingerprint=fingerprint,
        split_method='provider custom stratified 70/15/15 seed 42; membership imported verbatim',
        split_reproduced_from_source=False, evaluation_target='argmax_of_shared_soft_label',
        has_cross_split_duplicates=False, cross_split_duplicate_groups=[],
        near_duplicate_check=dict(method='equal 64bit dHash INTER_AREA 9x8 and raw MAD<=15',
                                  cross_split_pairs=near, subject_disjoint_verified=False),
        original_checkpoint_reuse_allowed=False, splits={})
    output.mkdir(parents=True, exist_ok=False)
    for split, rows in buckets.items():
        images, targets, ids = zip(*rows)
        path = output / f'{split}.npz'
        np.savez_compressed(path, images=np.stack(images), targets=np.stack(targets), ids=np.array(ids))
        counts = Counter(int(t.argmax()) for t in targets)
        manifest['splits'][split] = dict(raw=len(rows), accepted=len(rows), rejected={},
            class_counts={label: counts[i] for i, label in enumerate(LABELS)}, sha256=sha256(path))
    write_json(output / 'manifest.json', manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = prepare_csv(args.source, args.output)
    print(json.dumps(dict(fingerprint=result['fingerprint'], splits=result['splits'],
        cross_split_near_pairs=len(result['near_duplicate_check']['cross_split_pairs'])), indent=2), flush=True)


if __name__ == '__main__':
    main()
