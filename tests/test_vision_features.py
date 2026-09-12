import unittest
import numpy as np
from server.vision_features import ExpressionState, HeadMotion, emotion_candidate, expression_intensities, upper_body
from server.vision import StableLabel, ArmGestures


class FeatureTests(unittest.TestCase):
    def test_moderate_nod_and_shake(self):
        for axis,label in (("pitch","head_nod"),("yaw","head_shake")):
            motion = HeadMotion()
            found = []
            for i,value in enumerate([0,4,10,16,14,7,0,-2,0]):
                angles = dict(pitch=0.,yaw=0.,roll=0.)
                angles[axis] = value
                found.append(motion.update(angles,i*.12))
            self.assertIn(label,found)

    def test_jitter_and_one_way_turn_are_not_gestures(self):
        for values in ([0,1,-1,2,0,-2,1]*3,range(20)):
            motion = HeadMotion()
            for i,value in enumerate(values):
                self.assertEqual(motion.update(dict(pitch=value,yaw=0,roll=0),i*.1),"unknown")

    def test_lost_landmarks_clear_motion(self):
        motion = HeadMotion()
        for i,value in enumerate([0,10,20]):
            motion.update(dict(pitch=value,yaw=0,roll=0),i*.15)
        motion.update(None,.5)
        self.assertEqual(motion.update(dict(pitch=0,yaw=0,roll=0),.6),"unknown")

    def test_subtle_emotion_needs_two_sources(self):
        cases = ((3,"sad",dict(brow_inner_up=.4,mouth_frown=.2)),
                 (4,"angry",dict(brow_down=.5,eye_squint=.2)),
                 (5,"disgust",dict(nose_sneer=.5,upper_lip_raise=.3)),
                 (6,"fear",dict(brow_outer_up=.4,eye_wide=.3,jaw_open=.3)),
                 (7,"contempt",dict(smile_left=.6,smile_right=.1)))
        for index,label,cues in cases:
            probs = np.zeros(8)
            probs[0],probs[index],probs[2] = .52,.28,.20
            self.assertEqual(emotion_candidate(probs,{})[0],"unknown")
            self.assertEqual(emotion_candidate(probs,cues),(label,5,"fer+landmarks"))
            self.assertEqual(float(probs[index]),.28)
        probs = np.array([.05,.8,.05,.03,.03,.02,.01,.01])
        self.assertEqual(emotion_candidate(probs,dict(brow_down=.9,eye_squint=.8))[0],"happy")

    def test_all_non_neutral_landmark_intensities_are_exposed(self):
        cues = dict(smile=.7,jaw_open=.6,eye_wide=.6,brow_outer_up=.6,
                    brow_down=.7,eye_squint=.5,brow_inner_up=.6,mouth_frown=.5,
                    nose_sneer=.6,upper_lip_raise=.5,mouth_stretch=.6,
                    smile_left=.7,smile_right=.1)
        values = expression_intensities(cues)
        self.assertEqual(set(values),{"happy","surprised","sad","angry","disgust","fear","contempt"})
        self.assertTrue(all(0 < value <= 1 for value in values.values()))

    def test_confident_fer_emotion_is_not_overridden_by_noisy_landmarks(self):
        state = ExpressionState()
        probs = np.array([.03,.03,.03,.03,.75,.05,.05,.03])
        noisy = dict(smile=.9,jaw_open=.9,eye_wide=.9,brow_outer_up=.9)
        state.update(probs,noisy,0)
        result = state.update(probs,noisy,.4)
        self.assertEqual(result["emotion"],"angry")
        self.assertEqual(result["emotion_source"],"fer")

    def test_label_holds_brief_uncertainty_but_expires(self):
        label = StableLabel(count=2,hold=2)
        label.update("sad")
        self.assertEqual(label.update("sad"),"sad")
        self.assertEqual(label.update("unknown"),"sad")
        self.assertEqual(label.update("unknown"),"sad")
        self.assertEqual(label.update("unknown"),"unknown")
        label.reset()
        self.assertEqual(label.update("unknown"),"unknown")

    def test_upper_body_visibility_and_angle(self):
        points = np.zeros((17,3))
        points[5],points[7],points[9] = (100,100,1),(100,200,1),(200,200,1)
        joints,angles = upper_body(points,(480,640,3))
        self.assertEqual(angles["left"],90.)
        self.assertIsNone(angles["right"])
        self.assertAlmostEqual(joints["left_wrist"]["x"],200/640,places=4)
        self.assertFalse(joints["right_wrist"]["visible"])
        self.assertIsNone(joints["right_wrist"]["x"])

    def test_wave_uses_elbow_motion_and_ignores_body_translation(self):
        gestures = ArmGestures()
        def points(offset,wrist_delta):
            p = np.zeros((17,3))
            p[5],p[6] = (100+offset,150,1),(200+offset,150,1)
            p[7],p[9] = (100+offset,120,1),(100+offset+wrist_delta,70,1)
            return p
        for i,offset in enumerate([0,30,-30,30,-30,30]):
            self.assertNotEqual(gestures.update(points(offset,0),i*.2),"waving")
        gestures.reset()
        labels = [gestures.update(points(0,x),i*.2) for i,x in enumerate([0,20,40,20,0,20,40])]
        self.assertIn("waving",labels)


if __name__ == "__main__":
    unittest.main()
