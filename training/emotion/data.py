"""Validate FER2013 pixels + FER+ votes; preserve official row/split identity."""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
from itertools import zip_longest
import json
import re
from pathlib import Path

import cv2
import numpy as np

from .common import LABELS, PROTOCOL, SPLITS, sha256, write_json

VOTE_COLUMNS = ('neutral', 'happiness', 'surprise', 'sadness', 'anger',
                'disgust', 'fear', 'contempt', 'unknown', 'NF')


def vote_target(votes):
    """Own shared-v1 policy, not a reproduction of CNTK's top-75% filter."""
    votes = np.asarray(votes, dtype=np.float64)
    if (votes.shape != (10,) or not np.isfinite(votes).all()
            or (votes < 0).any() or (votes != np.floor(votes)).any()):
        raise ValueError('Expected ten nonnegative integer vote counts')
    votes = np.where(votes > 1, votes, 0)
    if votes.sum() == 0:
        return None, 'no_votes_after_singletons'
    emotions = votes[:8]
    if votes[8:].max() >= emotions.max():
        return None, 'unknown_or_nonface'
    if emotions.sum() <= .5 * votes.sum():
        return None, 'insufficient_emotion_votes'
    if np.count_nonzero(emotions == emotions.max()) != 1:
        return None, 'tied_top_emotion'
    return (emotions / emotions.sum()).astype(np.float32), None


def prepare(fer2013, ferplus, output):
    """Parse everything before writing; fail on shifted, missing or corrupt rows."""
    sources = {'fer2013': sha256(fer2013), 'ferplus': sha256(ferplus)}
    buckets = {name: [] for name in SPLITS.values()}
    rejected = {name: Counter() for name in SPLITS.values()}
    hashes = defaultdict(list)
    raw_counts = Counter()
    annotation_names = Counter()
    with Path(fer2013).open(newline='', encoding='utf-8-sig') as images, \
            Path(ferplus).open(newline='', encoding='utf-8-sig') as labels:
        image_rows, label_rows = csv.DictReader(images), csv.DictReader(labels)
        if not {'Usage', 'pixels'}.issubset(image_rows.fieldnames or []):
            raise ValueError('FER2013 must have Usage and pixels columns')
        if not {'Usage', 'Image name', *VOTE_COLUMNS}.issubset(label_rows.fieldnames or []):
            raise ValueError('FER+ must have Usage, Image name and ten vote columns')
        row_count = 0
        for index, (image, label) in enumerate(zip_longest(image_rows, label_rows)):
            row_count += 1
            if image is None or label is None:
                raise ValueError(f'CSV row counts differ at row {index}')
            usage = image['Usage'].strip()
            if usage not in SPLITS or usage != label['Usage'].strip():
                raise ValueError(f'Usage mismatch or unknown split at row {index}')
            # Row order aligns the CSVs. Published FER+ image names are NOT
            # guaranteed to equal the CSV row index (first divergence: row 60).
            identity = f'fer{index:07d}.png'
            annotation_name = label['Image name'].strip()
            if annotation_name:
                if not re.fullmatch(r'fer\d{7}\.png', annotation_name):
                    raise ValueError(f'Invalid FER+ image name at row {index}')
                # The official annotation CSV itself repeats four filenames.
                # Keep row alignment and independent row IDs; report repetitions.
                annotation_names[annotation_name] += 1
            split = SPLITS[usage]
            raw_counts[split] += 1
            try:
                tokens = image['pixels'].split()
                if len(tokens) != 48 * 48:
                    raise ValueError('expected 2304 pixels')
                pixels = np.array([int(token) for token in tokens], dtype=np.int64)
                if (pixels < 0).any() or (pixels > 255).any():
                    raise ValueError('pixel outside 0..255')
                target, reason = vote_target([float(label[key]) for key in VOTE_COLUMNS])
            except (ValueError, TypeError) as exc:
                raise ValueError(f'Invalid data at row {index}: {exc}') from exc
            if not label['Image name'].strip():
                rejected[split]['missing_image_annotation'] += 1
                continue
            if reason:
                rejected[split][reason] += 1
                continue
            pixels = pixels.astype(np.uint8).reshape(48, 48)
            digest = hashlib.sha256(pixels.tobytes()).hexdigest()
            hashes[digest].append((split, identity))
            buckets[split].append((pixels, target, identity))
    if any(not rows for rows in buckets.values()):
        raise ValueError('Every official split must contain at least one accepted sample')
    duplicates = [dict(pixel_sha256=digest, samples=[dict(split=s, id=i) for s, i in rows])
                  for digest, rows in hashes.items() if len({s for s, _ in rows}) > 1]
    identity_data = dict(protocol=PROTOCOL, sources=sources, labels=LABELS)
    fingerprint = hashlib.sha256(json.dumps(identity_data, sort_keys=True).encode()).hexdigest()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    summary = dict(schema=1, **identity_data, fingerprint=fingerprint, raw_rows=row_count,
                   repeated_annotation_names={name: count for name, count in annotation_names.items() if count > 1},
                   evaluation_target='unique_argmax_of_filtered_votes',
                   cross_split_duplicate_groups=duplicates,
                   has_cross_split_duplicates=bool(duplicates), splits={})
    for split, rows in buckets.items():
        pixels, targets, ids = zip(*rows)
        targets = np.stack(targets)
        path = output / f'{split}.npz'
        np.savez_compressed(path, images=np.stack(pixels), targets=targets, ids=np.array(ids))
        summary['splits'][split] = dict(raw=raw_counts[split], accepted=len(rows),
            rejected=dict(rejected[split]),
            class_counts=dict(zip(LABELS, np.bincount(targets.argmax(1), minlength=8).tolist())),
            sha256=sha256(path))
    write_json(output / 'manifest.json', summary)
    return summary


def load_split(root, split):
    root = Path(root)
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    if manifest['protocol'] != PROTOCOL or manifest['labels'] != list(LABELS):
        raise ValueError('Unsupported dataset protocol or label order')
    path = root / f'{split}.npz'
    if sha256(path) != manifest['splits'][split]['sha256']:
        raise ValueError(f'Dataset checksum mismatch: {split}')
    with np.load(path, allow_pickle=False) as bundle:
        images, targets, ids = (bundle[key].copy() for key in ('images', 'targets', 'ids'))
    if (images.dtype != np.uint8 or images.shape != (len(ids), 48, 48)
            or targets.shape != (len(ids), 8) or not np.isfinite(targets).all()
            or (targets < 0).any() or not np.allclose(targets.sum(1), 1)):
        raise ValueError('Invalid prepared dataset arrays')
    return images, targets, ids, manifest


def resize_faces(images):
    """Identical detector-free resizing for training and baseline comparison."""
    return np.stack([cv2.resize(image, (64, 64), interpolation=cv2.INTER_AREA)
                     for image in images])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fer2013', type=Path, required=True)
    parser.add_argument('--ferplus', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New directory, never overwrite')
    args = parser.parse_args()
    result = prepare(args.fer2013, args.ferplus, args.output)
    print(json.dumps({key: result[key] for key in ('fingerprint', 'splits', 'has_cross_split_duplicates')}, indent=2))


if __name__ == '__main__':
    main()
