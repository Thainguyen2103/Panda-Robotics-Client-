"""Camera capture, inference scheduling, rendering and publication."""
import base64
import logging
import sys
import threading
import time

from config import settings
from server.vision.engine import LOG, VisionEngine, cv2, empty_result
from server.vision.features import ARM_EDGES
from server.vision.signals import HAND_EDGES


class LatestFrame:
    """Single-slot mailbox: slow inference never queues old frames."""
    def __init__(self):
        self.lock = threading.Lock()
        self.frame,self.timestamp,self.sequence = None,0.,0

    def put(self, frame):
        with self.lock:
            self.frame,self.timestamp = frame,time.monotonic()
            self.sequence += 1

    def get(self):
        with self.lock:
            return self.frame,self.timestamp,self.sequence


def camera_source():
    source = settings.VISION_SOURCE
    return int(source) if str(source).isdigit() else source


def start_vision(callback, stop_event=None, publish=None):
    """Capture frames, run inference and publish stable robot/dashboard output."""
    if publish is None:
        from server.mqtt_bridge import publish
    stop = stop_event if stop_event is not None else threading.Event()
    mailbox = LatestFrame()
    result_lock = threading.Lock()
    latest = empty_result("starting")
    last_good_inference = time.monotonic()

    def emit(result):
        nonlocal latest,last_good_inference
        with result_lock:
            latest = result
            if result.get("frame_time",0):
                last_good_inference = time.monotonic()
        try:
            publish(settings.TOPIC_VISION_STATUS,result)
            publish("panda/user_status",result)
            callback(result["person_detected"],result["emotion"],result["action"])
        except Exception:
            LOG.exception("Vision output failed")

    def capture():
        cap = None
        try:
            while not stop.is_set():
                if cap is None:
                    if cv2 is None:
                        stop.wait(1)
                        continue
                    cap = cv2.VideoCapture(camera_source())
                    if not cap.isOpened():
                        cap.release()
                        cap = None
                        stop.wait(2)
                        continue
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH,settings.VISION_WIDTH)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT,settings.VISION_HEIGHT)
                    cap.set(cv2.CAP_PROP_BUFFERSIZE,1)
                ok,frame = cap.read()
                if not ok or frame is None:
                    mailbox.put(None)
                    cap.release()
                    cap = None
                    stop.wait(1)
                    continue
                scale = min(1.,settings.VISION_WIDTH/frame.shape[1],settings.VISION_HEIGHT/frame.shape[0])
                if scale < 1:
                    frame = cv2.resize(frame,(max(1,int(frame.shape[1]*scale)),max(1,int(frame.shape[0]*scale))))
                mailbox.put(frame)
                stop.wait(.001)
        except Exception:
            LOG.exception("Camera capture failed")
            mailbox.put(None)
        finally:
            if cap is not None:
                cap.release()

    def infer():
        # Resolve through the public facade so existing integrations that inject
        # a test/dummy engine via ``server.vision.VisionEngine`` keep working.
        facade = sys.modules.get("server.vision")
        engine_type = getattr(facade, "VisionEngine", VisionEngine)
        engine = engine_type()
        sequence = -1
        try:
            while not stop.is_set():
                began = time.monotonic()
                frame,timestamp,current = mailbox.get()
                if frame is not None and current != sequence and began-timestamp <= settings.VISION_STALE_SEC:
                    sequence = current
                    try:
                        result = engine.process(frame)
                        result["frame_time"] = timestamp
                        if time.monotonic()-timestamp <= settings.VISION_STALE_SEC:
                            emit(result)
                    except Exception:
                        LOG.exception("Vision frame failed")
                        engine.reset()
                elif frame is None or began-timestamp > settings.VISION_STALE_SEC:
                    engine.reset()
                stop.wait(max(.01,1/max(1,settings.VISION_AI_FPS)-(time.monotonic()-began)))
        finally:
            close = getattr(engine,"close",None)
            if close:
                close()

    workers = [threading.Thread(target=fn,daemon=True,name=name)
               for fn,name in ((capture,"vision-camera"),(infer,"vision-ai"))]
    for worker in workers:
        worker.start()
    last_sequence,last_offline = -1,-float("inf")
    try:
        while not stop.is_set():
            began = time.monotonic()
            frame,timestamp,sequence = mailbox.get()
            with result_lock:
                result = dict(latest)
                inference_age = began-last_good_inference
            camera_lost = frame is None or began-timestamp > settings.VISION_STALE_SEC
            if camera_lost or inference_age > settings.VISION_STALE_SEC:
                if began-last_offline >= 1:
                    emit(empty_result("camera_unavailable" if camera_lost else "inference_stale"))
                    last_offline = began
            if frame is not None and sequence != last_sequence and not camera_lost:
                last_sequence = sequence
                display = frame.copy()
                if began-result.get("frame_time",0) <= .5:
                    for hand in result.get("hands",[]):
                        if began-hand["timestamp"] > .5: continue
                        points = [(int(v[0]*display.shape[1]),int(v[1]*display.shape[0])) for v in hand["landmarks"]]
                        for a,b in HAND_EDGES: cv2.line(display,points[a],points[b],(80,220,120),1)
                        for p in points: cv2.circle(display,p,2,(80,255,180),-1)
                    for obj in result.get("objects",[]):
                        if began-obj["timestamp"] > 1.5: continue
                        x,y,w,h = obj["box"]
                        x,y,w,h = int(x*display.shape[1]),int(y*display.shape[0]),int(w*display.shape[1]),int(h*display.shape[0])
                        cv2.rectangle(display,(x,y),(x+w,y+h),(220,180,80),1)
                        cv2.putText(display,obj["label"],(x,max(14,y-4)),cv2.FONT_HERSHEY_SIMPLEX,.4,(220,180,80),1)
                    if settings.VISION_DRAW_SKELETON and began-result.get("pose_time",0) <= .5:
                        joints = result.get("upper_body_joints",{})
                        def point(joint):
                            return (int(joint["x"]*display.shape[1]),int(joint["y"]*display.shape[0]))
                        for a,b in ARM_EDGES:
                            if joints.get(a,{}).get("visible") and joints.get(b,{}).get("visible"):
                                cv2.line(display,point(joints[a]),point(joints[b]),(255,200,0),2)
                        for joint in joints.values():
                            if joint["visible"]:
                                cv2.circle(display,point(joint),4,(0,220,255),-1)
                    for key,color in (("face_box",(0,255,0)),("person_box",(255,180,0))):
                        if result.get(key):
                            x,y,w,h = map(int,result[key])
                            cv2.rectangle(display,(x,y),(x+w,y+h),color,2)
                width = min(480,display.shape[1])
                display = cv2.resize(display,(width,max(1,round(display.shape[0]*width/display.shape[1]))))
                ok,encoded = cv2.imencode(".jpg",display,[cv2.IMWRITE_JPEG_QUALITY,60])
                if ok:
                    publish(settings.TOPIC_CAMERA,base64.b64encode(encoded).decode("ascii"))
            stop.wait(max(.001,1/max(1,settings.VISION_STREAM_FPS)-(time.monotonic()-began)))
    finally:
        stop.set()
        for worker in workers:
            worker.join(timeout=2)


def main():
    if hasattr(sys.stdout,"reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8",errors="replace")
    logging.basicConfig(level=logging.INFO)
    start_vision(lambda detected,emotion,action:None)


if __name__ == "__main__":
    main()
