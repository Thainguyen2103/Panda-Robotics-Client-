import unittest
from unittest.mock import patch
import numpy as np
from server.vision_signals import EyeState, distance_estimate, finger_gesture, combined_actions, nearby_objects
from server.vision_features import ExpressionState
from server.vision import VisionEngine


class SignalTests(unittest.TestCase):
    def geometry(self,ear=.3): return dict(ear_left=ear,ear_right=ear,iris_horizontal=[.5,.5])
    def pose(self): return dict(pitch=0,yaw=0,roll=0)

    def test_blink_and_prolonged_closure(self):
        state = EyeState()
        state.update(self.geometry(),self.pose(),0)
        state.update(self.geometry(.1),self.pose(),.1)
        r=state.update(self.geometry(),self.pose(),.3)
        self.assertEqual(r['blink_count_60s'],1)
        for t in np.arange(.4,2.2,.1): r=state.update(self.geometry(.1),self.pose(),float(t))
        self.assertEqual(r['state'],'prolonged_closure')
        self.assertTrue(r['possible_drowsiness'])
        self.assertEqual(r['blink_count_60s'],1)
        self.assertEqual(r['gaze'],'unknown')

    def test_gaze_and_missing_data(self):
        state=EyeState()
        self.assertEqual(state.update(self.geometry(),self.pose(),0)['gaze'],'toward_camera')
        g=self.geometry();g['iris_horizontal']=[.2,.8]
        self.assertEqual(state.update(g,self.pose(),.1)['gaze'],'away')
        g=self.geometry();g['iris_vertical']=[.2,.2]
        self.assertEqual(state.update(g,self.pose(),.2)['gaze'],'away')
        self.assertEqual(state.update(None,None,.3)['state'],'unknown')
        self.assertIsNone(state.update(self.geometry(),self.pose(),2)['blink_rate_per_min'])

    def test_blink_rate_waits_for_observation_and_flags_low_sampling(self):
        state=EyeState()
        for i in range(211): r=state.update(self.geometry(.1 if i in (10,11) else .3),self.pose(),i*.1)
        self.assertIsNotNone(r['blink_rate_per_min'])
        self.assertEqual(r['quality'],'limited_sampling')
        self.assertEqual(r['blink_count_60s'],1)

    def test_calibrated_distance_scales_with_resolution(self):
        with patch('config.settings.VISION_DISTANCE_SCALE_CM',15):
            a=distance_estimate([0,0,160,200],640,self.pose())
            b=distance_estimate([0,0,320,400],1280,self.pose())
        self.assertEqual(a['cm'],60)
        self.assertEqual(a,b)
        self.assertIsNone(distance_estimate([0,0,160,200],640,dict(pitch=0,yaw=40))['cm'])

    def test_smile_bypasses_incorrect_neutral_and_releases(self):
        state=ExpressionState()
        probs=np.array([.94,.01,.01,.01,.01,.01,.005,.005])
        state.update(probs,{'smile':.8},0)
        self.assertEqual(state.update(probs,{'smile':.8},.2)['emotion'],'happy')
        self.assertEqual(probs[0],.94)
        state.update(probs,{},.3)
        self.assertEqual(state.update(probs,{},.7)['emotion'],'neutral')
        state.reset()
        self.assertEqual(state.update(None,{'jaw_open':.9},0)['emotion'],'unknown','mouth opening alone is not surprise')

    def test_actions_do_not_overwrite_each_other(self):
        hands=[dict(side='left',gesture='victory',associated=True),dict(side='right',gesture='thumbs_up',associated=True)]
        result=combined_actions('head_shake','hand_raised',hands)
        self.assertEqual(len(result),4)
        self.assertEqual({x['channel'] for x in result},{'head','arms','left_hand','right_hand'})
        hands[0]['associated']=False
        self.assertEqual(len(combined_actions('unknown','unknown',hands)),1)

    def test_strong_brow_expression_requires_sustained_evidence(self):
        for cues,label in (({'brow_down':.7,'eye_squint':.5},'angry'),({'brow_inner_up':.6,'mouth_frown':.4},'sad')):
            state=ExpressionState()
            probs=np.array([.94,.01,.01,.01,.01,.01,.005,.005])
            self.assertEqual(state.update(probs,cues,0)['emotion'],'unknown')
            self.assertEqual(state.update(probs,cues,.2)['emotion'],'unknown')
            self.assertEqual(state.update(probs,cues,.7)['emotion'],label)

    def test_object_proximity_is_not_a_grasp_claim(self):
        objects=[dict(label='cup',box=[.2,.2,.1,.1])]
        r=nearby_objects(objects,[dict(side='left',associated=True,landmarks=[[.25,.25,0]])])
        self.assertEqual(r[0]['near_hands'],['left'])
        self.assertNotIn('holding',r[0])

    def hand(self,extended):
        p=np.zeros((21,3))
        # Wrist below the palm; folded fingers terminate toward the wrist.
        for base,x in zip((5,9,13,17),(-.3,0,.3,.55)):
            p[base]=[x,-1,0]
            p[base+1]=[x,-1.5,0]
            p[base+2]=[x,-1.8 if base in extended else -1.25,0]
            p[base+3]=[x,-2.1 if base in extended else -.9,0]
        p[1],p[2],p[3],p[4]=[-.2,-.4,0],[-.4,-.7,0],[-.3,-.8,0],[0,-.6,0]
        return p

    def test_victory_and_thumbs_up_fingers(self):
        self.assertEqual(finger_gesture(self.hand({5,9})),'victory')
        p=self.hand(set())
        p[1],p[2],p[3],p[4]=[-.5,-.3,0],[-.6,-.7,0],[-.7,-1.1,0],[-.8,-1.6,0]
        self.assertEqual(finger_gesture(p),'thumbs_up')
        self.assertEqual(finger_gesture(np.zeros((21,3))),'unknown')

    def test_scheduler_shares_budget_and_skips_face_models_when_absent(self):
        engine=VisionEngine.__new__(VisionEngine)
        engine.models={name:object() for name in ('identity','emotion','pose','hands','objects')}
        engine.master=np.ones(128)
        for key in ('identity','emotion','pose','hands','objects'): setattr(engine,key+'_time',-float('inf'))
        selected=[]
        for _ in range(5):
            stage=engine._schedule(10,True)
            selected.append(stage)
            setattr(engine,stage+'_time',10)
        self.assertEqual(set(selected),set(engine.models))
        engine.identity_time=engine.emotion_time=-float('inf')
        self.assertIsNone(engine._schedule(10,False))


if __name__=='__main__': unittest.main()
