"""Calculate camera distance scale from a measured reference, without saving images."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--distance-cm',type=float,required=True,help='Measured distance from face to camera')
    parser.add_argument('--face-width-px',type=float,required=True,help='face_box width from vision status at that distance')
    parser.add_argument('--frame-width-px',type=float,default=640)
    args=parser.parse_args()
    if not (0 < args.distance_cm < 1000 and 0 < args.face_width_px <= args.frame_width_px):
        parser.error('Require a positive distance and a valid face/frame width')
    scale=args.distance_cm*args.face_width_px/args.frame_width_px
    print(f"Set VISION_DISTANCE_SCALE_CM = {scale:.5f} in config/settings.py")
    print('Reference applies to the same person/camera field of view; repeat after camera zoom changes.')


if __name__=='__main__':main()
