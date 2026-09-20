import unittest
import threading
import time
from unittest.mock import patch
import numpy as np
from server import vision as v


def face(yaw=0.,pitch=.5):
    return np.array([0,0,160,180, 40,40,120,40,80+yaw*80,40+pitch*80,50,120,110,120,.99],dtype=np.float32)


def arms(x=30.,visible=True):
    p = np.zeros((17,3),dtype=float)
    p[5],p[6] = [100,150,1],[200,150,1]
    p[9] = [100+x,80,1 if visible else .1]
    return p


class VisionTests(unittest.TestCase):
    def test_emotion_crop_is_square_and_padded_at_frame_edge(self):
        frame = np.arange(80*100*3,dtype=np.uint8).reshape(80,100,3)
        crop = v.emotion_face_crop(frame,[-5,5,30,50])
        self.assertEqual(crop.shape[0],crop.shape[1])
        self.assertGreater(crop.shape[0],50)

    def test_waving_requires_motion_and_no_legs(self):
        classifier = v.ArmGestures()
        for i in range(12):
            label = classifier.update(arms(),i*.2)
        self.assertEqual(label,"hand_raised")
        labels = [classifier.update(arms(x),3+i*.2) for i,x in enumerate([0,40,-40,40,-40,40,-40])]
        self.assertIn("waving",labels)
        self.assertEqual(classifier.update(arms(visible=False),5),"unknown")

    def test_nod_shake_and_stationary(self):
        for kind in ("head_nod","head_shake"):
            detector = v.HeadGestures()
            labels = []
            for i,value in enumerate([0,.1,.2,.1,0,-.1,0]):
                f = face(pitch=.5+value) if kind == "head_nod" else face(yaw=value*2)
                labels.append(detector.update(f,i*.12))
            self.assertIn(kind,labels)
        detector = v.HeadGestures()
        for i in range(20):
            self.assertEqual(detector.update(face(),i*.1),"unknown")

    def test_head_translation_scale_not_gesture(self):
        detector = v.HeadGestures()
        for i in range(20):
            f = face()
            f[4:14] = f[4:14]*(1+i*.02)+i*2
            self.assertEqual(detector.update(f,i*.1),"unknown")

    def test_temporal_gap_and_low_confidence_clear(self):
        detector = v.ArmGestures()
        for i,x in enumerate([0,40,-40]):
            detector.update(arms(x),i*.2)
        self.assertNotEqual(detector.update(arms(40),4),"waving")
        stable = v.StableLabel(2)
        stable.update("happy")
        self.assertEqual(stable.update("happy"),"happy")
        self.assertEqual(stable.update("unknown"),"unknown")
        self.assertEqual(stable.update("sad"),"unknown")

    def test_mailbox_replaces_old_frame(self):
        mailbox = v.LatestFrame()
        mailbox.put("old")
        mailbox.put("new")
        self.assertEqual(mailbox.get()[0],"new")
        self.assertEqual(mailbox.get()[2],2)

    def engine(self):
        with patch.object(v.VisionEngine,"_load"), patch.object(v.BASE.__class__,"exists",return_value=False):
            return v.VisionEngine()

    def test_face_survives_missing_other_models_and_no_auto_enroll(self):
        engine = self.engine()
        class Detector:
            def setInputSize(self,size): pass
            def detect(self,frame): return None,np.array([face()])
        engine.models["face"] = Detector()
        with patch.object(np,"save") as save:
            result = engine.process(np.zeros((240,320,3),dtype=np.uint8))
        self.assertTrue(result["face_detected"])
        self.assertEqual(result["identity"],"unknown")
        self.assertFalse(result["enrolled"])
        save.assert_not_called()

    def test_absence_clears_face_and_emotion(self):
        engine = self.engine()
        engine.face_box = (0,0,100,100)
        engine.emotion_probs = np.ones(8)
        result = engine.process(np.zeros((240,320,3),dtype=np.uint8))
        self.assertFalse(result["person_detected"])
        self.assertIsNone(engine.emotion_probs)
        self.assertIsNone(result["face_box"])

    def test_pose_failure_clears_previous_action(self):
        engine = self.engine()
        engine.models["pose"] = object()
        engine.pose_box,engine.pose_action = (0,0,100,100),"waving"
        result = engine.process(np.zeros((240,320,3),dtype=np.uint8))
        self.assertEqual(result["action"],"unknown")
        self.assertFalse(result["person_detected"])
        self.assertIn("pose",result["errors"])

    def test_face_coordinates_rescaled_and_emotion_failure_isolated(self):
        engine = self.engine()
        class Detector:
            def setInputSize(self,size): self.size = size
            def detect(self,frame): return None,np.array([face()])
        engine.models["face"] = Detector()
        engine.models["emotion"] = object()
        result = engine.process(np.zeros((480,640,3),dtype=np.uint8))
        self.assertEqual(result["face_box"],[0.,0.,320.,360.])
        self.assertTrue(result["face_detected"])
        self.assertEqual(result["emotion"],"unknown")
        self.assertIn("emotion",result["errors"])

    def test_camera_pipeline_stops_releases_and_publishes(self):
        stop = threading.Event()
        class Capture:
            released = False
            def isOpened(self): return True
            def set(self,*args): pass
            def read(self):
                time.sleep(.01)
                return True,np.zeros((120,160,3),dtype=np.uint8)
            def release(self): self.released = True
        capture = Capture()
        class Engine:
            def process(self,frame): return v.empty_result()
            def reset(self): pass
        records = []
        timer = threading.Timer(3,stop.set)
        timer.start()
        def publish(topic,payload):
            records.append((topic,payload))
            if sum(topic == v.settings.TOPIC_VISION_STATUS and bool(payload.get("frame_time"))
                   for topic,payload in records if isinstance(payload,dict)) >= 3:
                stop.set()
        try:
            with patch.object(v.cv2,"VideoCapture",return_value=capture),patch.object(v,"VisionEngine",Engine):
                v.start_vision(lambda *args:None,stop_event=stop,publish=publish)
        finally:
            timer.cancel()
        self.assertTrue(capture.released)
        self.assertTrue(any(topic == v.settings.TOPIC_CAMERA for topic,_ in records))
        self.assertGreaterEqual(sum(topic == v.settings.TOPIC_VISION_STATUS for topic,_ in records),3)

    def test_missing_camera_reports_absence(self):
        stop = threading.Event()
        class Capture:
            def isOpened(self): return False
            def release(self): pass
        class Engine:
            def reset(self): pass
        records = []
        def publish(topic,payload):
            if topic == v.settings.TOPIC_VISION_STATUS:
                records.append(payload)
                stop.set()
        with patch.object(v.cv2,"VideoCapture",return_value=Capture()),patch.object(v,"VisionEngine",Engine):
            v.start_vision(lambda *args:None,stop_event=stop,publish=publish)
        self.assertEqual(records[0]["status"],"camera_unavailable")
        self.assertFalse(records[0]["person_detected"])

    def test_emotion_cache_does_not_count_repeated_frames_as_evidence(self):
        engine = self.engine()
        class Detector:
            def setInputSize(self,size): pass
            def detect(self,frame): return None,np.array([face()])
        class Emotion:
            calls = 0
            def setInput(self,blob): pass
            def forward(self):
                self.calls += 1
                return np.array([[0,10,0,0,0,0,0,0]],dtype=np.float32)
        engine.models.update(face=Detector(),emotion=Emotion())
        frame = np.zeros((240,320,3),dtype=np.uint8)
        for t in [0,.01,.02,.03]:
            self.assertEqual(engine.process(frame,now=t)["emotion"],"unknown")
        self.assertEqual(engine.models["emotion"].calls,1)
        engine.process(frame,now=1)
        self.assertEqual(engine.process(frame,now=2)["emotion"],"happy")
        engine.models.pop("face")
        self.assertEqual(engine.process(frame,now=2.01)["emotion"],"unknown")
        self.assertEqual(engine.emotion_result["emotion"],"unknown")


if __name__ == "__main__":
    unittest.main()
