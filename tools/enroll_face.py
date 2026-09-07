"""Explicit enrollment from at least 3 single-person photos; never enroll on startup."""
import argparse
from pathlib import Path
import sys
import os
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server.vision import BASE, cv2
from config import settings
import numpy as np


def main():
    parser = argparse.ArgumentParser(description="Register the robot owner from frontal face photos")
    parser.add_argument("photos",nargs="+",help="At least 3 sharp, well-lit photos of the same person")
    parser.add_argument("--replace",action="store_true",help="Replace existing owner embedding")
    args = parser.parse_args()
    target = BASE/"master_face.npy"
    if target.exists() and not args.replace:
        parser.error("An owner already exists; pass --replace to register again")
    if len(set(map(str,map(Path,args.photos)))) < 3:
        parser.error("Provide at least 3 different photos")
    if cv2 is None:
        parser.error("OpenCV is not installed")
    detector = cv2.FaceDetectorYN_create(str(BASE/"face_detection_yunet_2023mar.onnx"),"",(320,320),.9)
    recognizer = cv2.FaceRecognizerSF_create(str(BASE/"face_recognition_sface_2021dec.onnx"),"")
    features = []
    for filename in args.photos:
        frame = cv2.imdecode(np.fromfile(filename,dtype=np.uint8),cv2.IMREAD_COLOR)
        if frame is None:
            parser.error(f"Cannot read {filename}")
        detector.setInputSize((frame.shape[1],frame.shape[0]))
        _,faces = detector.detect(frame)
        if faces is None or len(faces) != 1 or min(faces[0,2:4]) < 80:
            parser.error(f"{filename}: require exactly one face at least 80 px wide/high")
        crop = recognizer.alignCrop(frame,faces[0])
        if cv2.Laplacian(cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY),cv2.CV_64F).var() < 40:
            parser.error(f"{filename}: face is too blurry")
        feature = recognizer.feature(crop).reshape(-1)
        feature = feature/max(float(np.linalg.norm(feature)),1e-8)
        if any(float(np.dot(feature,other)) < settings.VISION_IDENTITY_THRESHOLD for other in features):
            parser.error("Photos do not consistently match the same person")
        features.append(feature)
    mean = np.mean(features,axis=0)
    mean = (mean/np.linalg.norm(mean)).astype(np.float32).reshape(1,128)
    # Replace only after all photos have passed; original enrollment survives failures.
    descriptor,temp = tempfile.mkstemp(dir=BASE,suffix=".npy")
    try:
        with os.fdopen(descriptor,"wb") as output:
            np.save(output,mean,allow_pickle=False)
        os.replace(temp,target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    print("Owner registered. Restart vision to load the new embedding.")


if __name__ == "__main__":
    main()
