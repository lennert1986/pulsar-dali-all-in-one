import threading
import unittest
from feedback import query,decode,active,inspect,command
from advanced import execute
class Fake:
    controller_id="test"
    scan_running=False
    def __init__(self):
        self.cache_lock=threading.RLock()
        self.operation_lock=threading.RLock()
        self.settings=type("Settings",(),{"local_dali_enabled":True})()
        self.control_devices={1:{2:{"online":True,"instances":[{"instance":3,"instance_type":1}]}}}
        self.frames=[]
        self.cap=7
        self.raw_active=255
    def _control_device_address(self,a):return (a<<1)|1
    def _dali2_query_device(self,*a):return 0
    def _s2or(self,b,op,inst,addr):
        self.frames.append(("query",b,op,inst,addr))
        return {0x4F:self.cap,0x4E:self.raw_active,0x4D:255,0x4C:200,0x4A:0,0x4B:63,0x49:1}.get(op)
    def _s2on(self,b,op,inst,addr):
        self.frames.append(("once",b,op,inst,addr))
        self.raw_active=255 if op==0x10 else None
class Tests(unittest.TestCase):
    def req(self,c,action,**kw):
        return execute(c,dict(controller_id="test",bus=1,address=2,instance=3,action=action,**kw))
    def test_exact_address_and_read_queries(self):
        c=Fake();r=self.req(c,"feedback_read")
        self.assertTrue(r["feedback_features"]["visible"])
        self.assertTrue(r["feedback_features"]["colour"])
        self.assertEqual(r["active_brightness"],200)
        self.assertEqual(r["inactive_brightness"],0)
        self.assertEqual([x[2] for x in c.frames],[0x4F,0x4E,0x4D,0x4C,0x4A,0x4B,0x49])
        self.assertTrue(all(x[0]=="query" and x[3:]==(0x23,5) for x in c.frames))
    def test_activation_and_stop(self):
        c=Fake()
        r=self.req(c,"feedback",value=1,confirm=True,test_bus=True)
        self.assertTrue(r["readback_verified"])
        self.assertIn(("once",1,0x10,0x23,5),c.frames)
        c.frames.clear()
        r=self.req(c,"feedback",value=0,confirm=True,test_bus=True)
        self.assertEqual([x for x in c.frames if x[0]=="once"],[("once",1,0x11,0x23,5)])
        self.assertIsNone(r["feedback_active"])
        self.assertFalse(r["readback_verified"])
        self.assertTrue(r["target_responded"])
    def test_confirmation(self):
        c=Fake()
        for opts in ({},{"confirm":True},{"test_bus":True}):
            with self.assertRaises(ValueError):self.req(c,"feedback",value=1,**opts)
        self.assertFalse(c.frames)
    def test_unsupported_unknown_audible(self):
        for cap in (None,0,8,9,255):
            c=Fake();c.cap=cap
            with self.assertRaises(ValueError):self.req(c,"feedback",value=1,confirm=True,test_bus=True)
            self.assertTrue(all(x[0]=="query" for x in c.frames))
        c=Fake();c.cap=None
        self.assertIsNone(self.req(c,"feedback_read")["feedback_features"])
    def test_conflict_and_address(self):
        c=Fake();c.control_devices[1][2]["address_conflict"]=True
        with self.assertRaises(ValueError):self.req(c,"feedback",value=1,confirm=True,test_bus=True)
        self.assertFalse(c.frames)
        with self.assertRaises(ValueError):query(c,1,2,32,0x4F)
    def test_active_reply(self):
        self.assertIsNone(active(None))
        self.assertTrue(active(255))
        with self.assertRaises(ValueError):active(0)
if __name__=="__main__":unittest.main()
