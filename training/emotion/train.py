"""Train B/C using validation only; atomically checkpoint at epoch boundaries."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import subprocess

os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG', ':4096:8')
import cv2
import numpy as np
import torch
from torch.utils.data import DataLoader

from .common import LABELS, PROTOCOL, write_json
from .data import load_split
from .metrics import classification_metrics
from .model import ARCHITECTURE, EmotionCNN, FaceDataset


def seed_everything(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark = False


def rng_state(generator):
    state = np.random.get_state()
    return dict(python=random.getstate(), numpy=[state[0], state[1].tolist(), *state[2:]],
                torch=torch.get_rng_state(), loader=generator.get_state(),
                cuda=torch.cuda.get_rng_state_all() if torch.cuda.is_available() else [])


def restore_rng(state, generator):
    random.setstate(state['python'])
    array = state['numpy']
    np.random.set_state((array[0], np.array(array[1], dtype=np.uint32), *array[2:]))
    torch.set_rng_state(state['torch'].cpu())
    generator.set_state(state['loader'].cpu())
    if torch.cuda.is_available() and state['cuda']:
        torch.cuda.set_rng_state_all([item.cpu() for item in state['cuda']])


def save_checkpoint(path, state):
    temporary = path.with_name(path.name + '.tmp')
    torch.save(state, temporary)
    os.replace(temporary, path)


def load_checkpoint(path):
    checkpoint = torch.load(path, map_location='cpu', weights_only=True)
    if (checkpoint['architecture'] != ARCHITECTURE or checkpoint['labels'] != list(LABELS)
            or checkpoint['protocol'] != PROTOCOL):
        raise ValueError('Checkpoint architecture/labels/protocol mismatch')
    return checkpoint


def epoch_pass(model, loader, device, optimizer=None):
    model.train(optimizer is not None)
    losses, expected, predicted = [], [], []
    with torch.set_grad_enabled(optimizer is not None):
        for pixels, targets in loader:
            pixels, targets = pixels.to(device), targets.to(device)
            logits = model(pixels)
            loss = -(targets * logits.log_softmax(1)).sum(1).mean()
            if not torch.isfinite(loss):
                raise RuntimeError('Nonfinite loss; refusing to save a corrupt run')
            if optimizer is not None:
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                optimizer.step()
            losses.append((float(loss.detach().cpu()), len(pixels)))
            expected.extend(targets.argmax(1).detach().cpu().tolist())
            predicted.extend(logits.argmax(1).detach().cpu().tolist())
    metrics = classification_metrics(expected, predicted)
    metrics['loss'] = sum(loss * count for loss, count in losses) / sum(count for _, count in losses)
    return metrics


def train(args):
    if min(args.epochs, args.batch_size, args.patience, args.threads) < 1 or args.lr <= 0:
        raise ValueError('Epochs, batch size, patience, threads and learning rate must be positive')
    if args.session_epochs is not None and args.session_epochs < 1:
        raise ValueError('session-epochs must be positive')
    output = Path(args.output)
    if not args.resume and output.exists() and any(output.iterdir()):
        raise ValueError('Run directory already contains files. Use --resume or a new directory.')
    torch.set_num_threads(args.threads)
    seed_everything(args.seed)
    device = torch.device(args.device or ('cuda' if torch.cuda.is_available() else 'cpu'))
    train_images, train_targets, _, manifest = load_split(args.data, 'train')
    val_images, val_targets, _, _ = load_split(args.data, 'validation')
    config = dict(architecture=ARCHITECTURE, mode=args.mode, seed=args.seed,
        epochs=args.epochs, batch_size=args.batch_size, lr=args.lr,
        weight_decay=args.weight_decay, patience=args.patience, augment=not args.no_augment,
        dataset_fingerprint=manifest['fingerprint'])
    # No workers: Python/torch augmentation RNG resumes exactly at epoch boundaries.
    generator = torch.Generator().manual_seed(args.seed)
    train_loader = DataLoader(FaceDataset(train_images, train_targets, args.mode, not args.no_augment),
        batch_size=args.batch_size, shuffle=True, num_workers=0, generator=generator)
    val_loader = DataLoader(FaceDataset(val_images, val_targets, 'soft'),
        batch_size=args.batch_size, shuffle=False, num_workers=0)
    model = EmotionCNN().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)
    history, best_score, best_epoch, bad_epochs, start = [], -1., 0, 0, 0
    if args.resume:
        state = load_checkpoint(output / 'last.pt')
        if state['config'] != config:
            raise ValueError('Resume config or dataset changed. Start a separate experiment.')
        # last.pt is committed first. Repair a session interrupted before best.pt
        # was updated, using the complete model/optimizer/RNG state in last.pt.
        best_path = output / 'best.pt'
        if state['best_epoch'] == state['epoch']:
            if not best_path.exists() or load_checkpoint(best_path)['epoch'] != state['best_epoch']:
                save_checkpoint(best_path, state)
        if not best_path.exists() or load_checkpoint(best_path)['epoch'] != state['best_epoch']:
            raise ValueError('Resume needs the matching best.pt from this run')
        model.load_state_dict(state['model'])
        optimizer.load_state_dict(state['optimizer'])
        scheduler.load_state_dict(state['scheduler'])
        restore_rng(state['rng'], generator)
        history, best_score, best_epoch, bad_epochs, start = (state[key] for key in
            ('history', 'best_score', 'best_epoch', 'bad_epochs', 'epoch'))
    output.mkdir(parents=True, exist_ok=True)
    try:
        revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True,
                                            stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        revision = None
    environment = dict(torch=str(torch.__version__), numpy=np.__version__, opencv=cv2.__version__,
        device=str(device), device_name=torch.cuda.get_device_name(device) if device.type == 'cuda' else 'CPU',
        threads=args.threads, git_revision=revision)
    write_json(output / 'config.json', dict(config=config, environment=environment,
                                          dataset_manifest=manifest))
    stop = min(args.epochs, start + args.session_epochs) if args.session_epochs else args.epochs
    for epoch in range(start, stop):
        if bad_epochs >= args.patience:
            break
        training = epoch_pass(model, train_loader, device, optimizer)
        validation = epoch_pass(model, val_loader, device)
        row = dict(epoch=epoch + 1, lr=optimizer.param_groups[0]['lr'],
                   train=training, validation=validation)
        history.append(row)
        score = validation['macro_f1']
        improved = score > best_score
        if improved:
            best_score, bad_epochs = score, 0
            best_epoch = epoch + 1
        else:
            bad_epochs += 1
        scheduler.step()
        state = dict(schema=1, architecture=ARCHITECTURE, labels=list(LABELS), protocol=PROTOCOL,
            config=config, model=model.state_dict(), optimizer=optimizer.state_dict(),
            scheduler=scheduler.state_dict(), rng=rng_state(generator), epoch=epoch + 1,
            history=history, best_score=best_score, best_epoch=best_epoch,
            bad_epochs=bad_epochs, environment=environment)
        save_checkpoint(output / 'last.pt', state)
        if improved:
            save_checkpoint(output / 'best.pt', state)
        write_json(output / 'history.json', history)
        print(json.dumps(dict(epoch=epoch + 1, train_loss=training['loss'],
            val_loss=validation['loss'], val_macro_f1=score, best=best_score)), flush=True)
    write_json(output / 'status.json', dict(epochs_completed=len(history), best_validation_macro_f1=best_score,
        status='complete' if len(history) >= args.epochs or bad_epochs >= args.patience else 'resumable',
        updated_utc=datetime.now(timezone.utc).isoformat(), test_used=False))
    return history


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=('hard', 'soft'), required=True)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--epochs', type=int, default=80)
    parser.add_argument('--batch-size', type=int, default=128)
    parser.add_argument('--lr', type=float, default=.001)
    parser.add_argument('--weight-decay', type=float, default=.0001)
    parser.add_argument('--patience', type=int, default=12)
    parser.add_argument('--device', default=None, help='Default: CUDA when available, otherwise CPU')
    parser.add_argument('--threads', type=int, default=2)
    parser.add_argument('--no-augment', action='store_true')
    parser.add_argument('--resume', action='store_true', help='Continue OUTPUT/last.pt')
    parser.add_argument('--session-epochs', type=int, help='Stop after this many epochs this session; resume later')
    return parser.parse_args(argv)


if __name__ == '__main__':
    train(parse_args())
