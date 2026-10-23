"""Small CNN trained from random weights; raw 0..255 NCHW -> eight logits."""
import numpy as np
import torch
from torch import nn
from torch.utils.data import Dataset
from torchvision.transforms import InterpolationMode
from torchvision.transforms import functional as TF

from .data import resize_faces

ARCHITECTURE = 'fer-cnn-v1'


class EmotionCNN(nn.Module):
    def __init__(self):
        super().__init__()
        layers = []
        incoming = 1
        for outgoing in (32, 64, 128, 256):
            layers.extend([nn.Conv2d(incoming, outgoing, 3, padding=1, bias=False),
                           nn.BatchNorm2d(outgoing), nn.ReLU(),
                           nn.Conv2d(outgoing, outgoing, 3, padding=1, bias=False),
                           nn.BatchNorm2d(outgoing), nn.ReLU(), nn.MaxPool2d(2)])
            incoming = outgoing
        self.features = nn.Sequential(*layers)
        self.pool = nn.AdaptiveAvgPool2d(1)
        self.classifier = nn.Sequential(nn.Flatten(), nn.Dropout(.35), nn.Linear(256, 8))

    def forward(self, pixels):
        # Embedded in exported ONNX, so live Vision keeps supplying raw pixels.
        normalized = pixels / 127.5 - 1.
        return self.classifier(self.pool(self.features(normalized)))


class FaceDataset(Dataset):
    def __init__(self, images, targets, mode='soft', augment=False):
        self.images = resize_faces(images)
        self.targets = np.asarray(targets, dtype=np.float32)
        self.mode, self.augment = mode, augment

    def __len__(self):
        return len(self.images)

    def __getitem__(self, index):
        pixels = torch.from_numpy(self.images[index].copy()).unsqueeze(0).float()
        if self.augment:
            if torch.rand(()).item() < .5:
                pixels = pixels.flip(-1)
            angle = torch.empty(()).uniform_(-12, 12).item()
            translate = torch.randint(-3, 4, (2,)).tolist()
            scale = torch.empty(()).uniform_(.95, 1.05).item()
            pixels = TF.affine(pixels, angle, translate, scale, [0., 0.],
                               interpolation=InterpolationMode.BILINEAR, fill=127.5)
            brightness = torch.empty(()).uniform_(.85, 1.15).item()
            pixels = (pixels * brightness).clamp(0, 255)
        target = torch.from_numpy(self.targets[index].copy())
        if self.mode == 'hard':
            target = torch.nn.functional.one_hot(target.argmax(), 8).float()
        return pixels, target
