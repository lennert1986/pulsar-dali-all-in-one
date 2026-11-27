import tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
import button_bindings as bb
from test_feedback import Fake as FeedbackFake
class Fake(FeedbackFake):
    def __init__(self):
        super().__init__()
        self.control_devices[1][2]["instances"][0].update(enabled=True,event_scheme=2,event_filter=20)
        self.gear={1:{7:dict(ha_uid="lamp",random_address=42,online=True,groups=[1])}}
        self.level=0
        self.commands=[]
    def _dali2_query_instance(self,b,a,n,op):return {0x80:1,0x8B:2,0x86:255}.get(op)
    def _assert_unique_address(self,b,a):return self.gear[b][a]["random_address"]
    def query(self,b,a,param):return self.level
    def set_level(self,b,a,v):self.commands.append(v);self.level=v
    def events_since(self,*a):return dict(latest_id=0,events=[])
class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.c=Fake()
        self.path=patch.object(bb,"PATH",Path(self.tmp.name)/"bindings.json");self.path.start()
        self.opts=patch.object(bb,"options",return_value=dict(local_button_bindings_enabled=True,feedback_mqtt_enabled=True));self.opts.start()
        self.worker=bb.Worker(self.c,lambda s:None)
    def tearDown(self):
        self.opts.stop();self.path.stop();self.tmp.cleanup()
    def bind(self,mode="follow",kind="gear",target="lamp"):
        return bb.config(self.c,1,2,3,dict(action="binding_set",enabled=True,target_kind=kind,target=target,short_action="toggle",long_action="dim_up",feedback_mode=mode))
    def event(self,typ="short_press",stamp=None):
        return dict(bus=1,address=2,instance=3,instance_type=1,event_type=typ,timestamp=time.time() if stamp is None else stamp)
    def test_local_binding_persistence_and_feedback(self):
        self.bind()
        rows=bb.load();self.assertEqual(rows["1:2:3"]["target"],"lamp")
        self.worker.event(self.event(),rows);self.assertEqual(self.c.commands,[254])
        self.worker.sync(rows);self.assertIn(("once",1,0x10,0x23,5),self.c.frames)
        self.c.level=0 # external control, independent of cached command
        self.worker.sync(rows);self.assertIn(("once",1,0x11,0x23,5),self.c.frames)
        self.worker.sync(rows)
        self.assertEqual(sum(x==("once",1,0x11,0x23,5) for x in self.c.frames),1)
    def test_reject_stale_and_changed_targets(self):
        self.bind(kind="group",target=1)
        rows=bb.load();self.worker.event(self.event(stamp=time.time()-5),rows)
        self.assertEqual(self.c.commands,[])
        self.c.gear[1][7]["random_address"]=43
        with self.assertRaises(ValueError):self.worker.event(self.event(),rows)
        self.assertEqual(self.c.commands,[])
    def test_mqtt_ownership(self):
        self.bind()
        with self.assertRaises(ValueError):bb.mqtt_command(self.c,1,2,3,1)
        bb.config(self.c,1,2,3,dict(action="binding_set",enabled=False))
        self.assertTrue(bb.mqtt_command(self.c,1,2,3,1)["readback_verified"])
        self.assertEqual(bb.load(),{})
    def test_inactive_options(self):
        with patch.object(bb,"options",return_value={}):
            with self.assertRaises(ValueError):self.bind()
            with self.assertRaises(ValueError):bb.mqtt_command(self.c,1,2,3,1)
if __name__=="__main__":unittest.main()
