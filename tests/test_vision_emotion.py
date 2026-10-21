"""Regression cases for ambiguity, neutral interruptions and actual FER input."""
import unittest
from unittest.mock import patch

import numpy as np

from config import settings
from server.vision.face.analysis import (
    EMOTIONS, ExpressionState, combined_emotion_scores, emotion_candidate,
    expression_decision, expression_intensities,
)
from server.vision.pipeline.engine import cv2, emotion_input_blob
from tools.evaluate_emotions import classification_metrics


class EmotionTests(unittest.TestCase):
    def test_evaluation_counts_unknown_as_miss_and_reports_partial_classes(self):
        result = classification_metrics(['happy','happy','sad','neutral'],['happy','unknown','happy','neutral'])
        self.assertEqual(result['accuracy'],.5)
        self.assertEqual(result['coverage'],.75)
        self.assertEqual(result['confusion_matrix']['happy']['unknown'],1)
        self.assertEqual(result['per_class']['happy']['precision'],.5)
        self.assertEqual(result['per_class']['happy']['recall'],.5)
        self.assertEqual(result['per_class']['sad']['recall'],0.)
        self.assertEqual(result['macro_classes'],3)
        self.assertAlmostEqual(result['macro_f1'],.5)
        self.assertFalse(result['complete_eight_classes'])

    def test_each_class_can_be_confirmed_by_decisive_fer(self):
        for index,label in enumerate(EMOTIONS):
            with self.subTest(label=label):
                probs = np.full(8,.02)
                probs[index] = .86
                state = ExpressionState()
                self.assertEqual(state.update(probs,{},0)['emotion'],'unknown')
                result = state.update(probs,{},.7)
                self.assertEqual(result['emotion'],label)
                self.assertEqual(result['emotion_source'],'fer')

    def test_neutral_dominant_model_allows_distinct_sustained_landmarks(self):
        cases = dict(happy=dict(smile=.8,smile_left=.8,smile_right=.8),
            surprised=dict(jaw_open=.7,eye_wide=.6,brow_outer_up=.5),
            angry=dict(brow_down=.7,eye_squint=.5),
            sad=dict(brow_inner_up=.6,mouth_frown=.4),
            disgust=dict(nose_sneer=.6,upper_lip_raise=.5),
            fear=dict(brow_inner_up=.5,eye_wide=.5,mouth_stretch=.6,jaw_open=.4),
            contempt=dict(smile=.55,smile_left=.9,smile_right=.2))
        probs = np.array([.94,.01,.01,.01,.01,.01,.005,.005])
        for label,cues in cases.items():
            with self.subTest(label=label):
                state = ExpressionState()
                state.update(probs,cues,0,fer_fresh=False)
                self.assertEqual(state.update(probs,cues,.7,fer_fresh=False)['emotion'],label)
        self.assertEqual(probs[0],.94,'fusion must not rewrite FER output')

    def test_subtle_supported_third_choice_is_not_discarded(self):
        probs = np.array([.56,.01,.23,.02,.16,.01,.005,.005])
        self.assertEqual(emotion_candidate(probs,dict(brow_down=.45,mouth_press=.2)),('angry',5,'fer+landmarks'))

    def test_competing_landmarks_do_not_pick_first_rule(self):
        cues = dict(brow_down=.6,eye_squint=.3,brow_inner_up=.5,mouth_frown=.25)
        # Angry/sad have almost equal strengths relative to their thresholds.
        self.assertEqual(expression_decision(None,cues)[0],'unknown')

    def test_jaw_brows_or_squint_alone_do_not_create_expression(self):
        for cues in (dict(jaw_open=.9),dict(brow_down=.9),dict(eye_squint=.9),dict(brow_inner_up=.9)):
            self.assertEqual(expression_decision(None,cues)[0],'unknown')

    def test_cached_neutral_does_not_replace_expression(self):
        state = ExpressionState()
        probs = np.array([.94,.01,.01,.01,.01,.01,.005,.005])
        state.update(probs,dict(smile=.8),0,fer_fresh=False)
        state.update(probs,dict(smile=.8),.2,fer_fresh=False)
        state.update(probs,{},.3,fer_fresh=False)
        self.assertEqual(state.update(probs,{},1.,fer_fresh=False)['emotion'],'happy')
        self.assertEqual(state.update(probs,{},1.3,fer_fresh=False)['emotion'],'unknown')

    def test_long_gap_cannot_confirm_an_old_candidate(self):
        state = ExpressionState()
        probs = np.array([.02,.86,.02,.02,.02,.02,.02,.02])
        state.update(probs,{},0)
        self.assertEqual(state.update(probs,{},2)['emotion'],'unknown')
        self.assertEqual(state.update(probs,{},2.4)['emotion'],'happy')

    def test_a_cached_first_observation_cannot_start_confirmation(self):
        state = ExpressionState()
        probs = np.array([.02,.86,.02,.02,.02,.02,.02,.02])
        state.update(probs,{},0,fer_fresh=False)
        self.assertEqual(state.update(probs,{},.5,fer_fresh=True)['emotion'],'unknown')
        self.assertEqual(state.update(probs,{},.9,fer_fresh=True)['emotion'],'happy')

    def test_bad_probabilities_and_cues_are_safe_and_do_not_mutate(self):
        for probs in ([],[1,2],np.full(8,np.nan),np.zeros(8),[-1,1,0,0,0,0,0,0]):
            self.assertEqual(ExpressionState().update(probs,{},0)['emotion'],'unknown')
            self.assertEqual(combined_emotion_scores(probs,{}),{})
        scores = expression_intensities(dict(brow_down=-1,eye_squint=2,smile=float('nan')))
        self.assertTrue(all(np.isfinite(v) and 0 <= v <= 1 for v in scores.values()))
        probs = np.array([.56,.01,.23,.02,.16,.01,.005,.005])
        original = probs.copy()
        combined_emotion_scores(probs,dict(brow_down=.45,mouth_press=.2))
        np.testing.assert_array_equal(probs,original)

    @unittest.skipIf(cv2 is None,'OpenCV required')
    def test_blob_preserves_trained_pixel_range_and_shape(self):
        blob = emotion_input_blob(np.full((200,240,3),180,np.uint8),[30,20,130,160])
        self.assertEqual(blob.shape,(1,1,64,64))
        self.assertEqual(blob.dtype,np.float32)
        np.testing.assert_array_equal(blob,180.)

    @unittest.skipIf(cv2 is None,'OpenCV required')
    def test_eye_roll_is_corrected_and_invalid_eyes_fall_back(self):
        frame = np.zeros((200,200,3),np.uint8)
        face = np.array([25,25,150,150,60,75,140,105,100,110,80,140,120,140,.99])
        for point in ((60,75),(140,105)):
            cv2.circle(frame,point,6,(255,255,255),-1)
        aligned = emotion_input_blob(frame,face)[0,0]
        ly,lx = np.where(aligned[:,:32] > 100)
        ry,rx = np.where(aligned[:,32:] > 100)
        self.assertLess(abs(ly.mean()-ry.mean()),1.)
        with patch.object(settings,'VISION_EMOTION_ALIGN_ROLL',False):
            unaligned = emotion_input_blob(frame,face)
        face[4:8] = 0
        np.testing.assert_array_equal(emotion_input_blob(frame,face),unaligned)


if __name__ == '__main__':
    unittest.main()
