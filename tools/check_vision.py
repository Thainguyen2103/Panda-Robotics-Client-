"""Local vision diagnostic: no MQTT, no robot commands, no saved camera images."""
import argparse
import json
from pathlib import Path
import sys
import time
from collections import Counter

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from server.vision import VisionEngine, cv2, camera_source
from config import settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera",action="store_true",help="Use configured camera instead of a blank image")
    parser.add_argument("--frames",type=int,default=30)
    args = parser.parse_args()
    if args.frames < 1:
        parser.error("--frames must be positive")
    engine = VisionEngine()
    if cv2 is None:
        print(json.dumps({"errors":engine.errors}))
        return 1
    blank = np.zeros((settings.VISION_HEIGHT,settings.VISION_WIDTH,3),dtype=np.uint8)
    # Warm up model graphs; exclude one-time initialization from timings.
    engine.process(blank)
    engine.reset()
    cap = cv2.VideoCapture(camera_source()) if args.camera else None
    timings,faces,actions = [],0,Counter()
    head_frames = cue_frames = joint_frames = 0
    began = time.monotonic()
    try:
        if cap is not None and not cap.isOpened():
            print("Camera unavailable")
            return 1
        for _ in range(args.frames):
            frame = blank
            if cap is not None:
                ok,frame = cap.read()
                if not ok:
                    print("Camera read failed")
                    return 1
                scale = min(1.,settings.VISION_WIDTH/frame.shape[1],settings.VISION_HEIGHT/frame.shape[0])
                if scale < 1:
                    frame = cv2.resize(frame,(int(frame.shape[1]*scale),int(frame.shape[0]*scale)))
            result = engine.process(frame)
            timings.append(result["inference_ms"])
            faces += int(result["face_detected"])
            actions[result["action"]] += 1
            head_frames += int(result["head_pose"] is not None)
            cue_frames += int(bool(result["expression_cues"]))
            joint_frames += int(any(j["visible"] for j in result["upper_body_joints"].values()))
            time.sleep(max(0,1/settings.VISION_AI_FPS-result["inference_ms"]/1000))
    finally:
        if cap is not None:
            cap.release()
        engine.close()
    print(json.dumps(dict(source="camera" if args.camera else "blank",frames=len(timings),
        face_frames=faces,head_pose_frames=head_frames,face_cue_frames=cue_frames,joint_frames=joint_frames,
        actions=dict(actions),median_ms=round(float(np.median(timings)),1),
        p95_ms=round(float(np.percentile(timings,95)),1),
        observed_fps=round(len(timings)/(time.monotonic()-began),1),
        models=result["models"],errors=result["errors"]),indent=2))
    return int(bool(result["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())
