import threading,unittest
from test_lab import run,install
class Transport:
    bus_number=1; ready=True
    def transact(self,command,sequence,data="",blink=True):
        return "02010E" if command=="GVER" else "0042"
install(Transport,lambda c,s,d:f"{c}{s:04X}{d}\n".encode())
class Fake:
    controller_id="test"; scan_running=False
    def __init__(self):
        self.settings=type("Settings",(),{"local_dali_enabled":True})()
        self.operation_lock=threading.RLock(); self.cache_lock=threading.RLock()
        self.transports={1:Transport()}; self.gear={1:{7:{"ha_uid":"stable","random_address":42}}}
        self.control_devices={1:{2:{"instances":[{"instance":0}]}}}; self.calls=[]
    def gver(self,b): return self.transports[b].transact("GVER",1)
    def _assert_unique_address(self,b,a): return 42
    def _s1or(self,b,d):
        self.calls.append(("query",d)); self.transports[b].transact("S1OR",2,f"{d:04X}")
        return {0xA5:0x42,0xA8:0,0x99:8,0xF9:0x62,0xF8:0x20,0xC5:31}.get(d>>8,1)
    def _s1on(self,b,d): self.calls.append(("volatile",d)); self.transports[b].transact("S1ON",3,f"{d:04X}")
    def query(self,b,a,n): return self._s1or(b,0x900F)
    def _dali2_query_device(self,*a): return 1
    def _dali2_query_instance(self,*a): return 2
    def _control_device_address(self,a):return (a<<1)|1
    def _s2or(self,b,op,inst,addr):
        self.calls.append(("feedback",op,inst,addr))
        return {0x4F:7,0x4E:255,0x4D:255,0x4C:254,0x4A:0,0x4B:63,0x49:1}.get(op)
class LabTest(unittest.TestCase):
    def req(self,c,mode,**kw):
        return run(c,dict(controller_id="test",bus=1,address=7,uid="stable",mode=mode,**kw))
    def test_trace_and_fade(self):
        c=Fake(); r=self.req(c,"fade")
        self.assertEqual(r["checks"][3]["value"],{"fade_time":4,"fade_rate":2})
        self.assertEqual(r["telegram_log"][0]["command"],"GVER")
        self.assertEqual(r["telegram_log"][1]["response_payload"],"0042")
        self.assertFalse(any(k=="volatile" for k,v in c.calls))
    def test_identity(self):
        c=Fake(); c.gear[1][7]["random_address"]=41
        r=self.req(c,"fade")
        self.assertEqual(r["checks"][-1]["status"],"error")
        self.assertFalse(c.calls)
    def test_memory(self):
        c=Fake(); r=self.req(c,"memory",bank=202,offset=4,count=2,confirm_volatile=True)
        self.assertEqual(r["memory"]["bytes"],[31,31])
        self.assertFalse(r["memory"]["decoded"])
        self.assertTrue(all(k=="query" or v&255 in (0xA3,0xC3) for k,v in c.calls))
    def test_confirmation(self):
        c=Fake()
        with self.assertRaises(ValueError): self.req(c,"capabilities")
        self.assertFalse(c.calls)
    def test_capabilities(self):
        c=Fake(); r=self.req(c,"capabilities",confirm_volatile=True)
        self.assertTrue(any(x["test"]=="DT8 capabilities" and x["value"]["rgbwaf_channels"]==3 for x in r["checks"]))
        self.assertTrue(all(k=="query" or v==0x08C1 for k,v in c.calls))
    def test_wrong_controller(self):
        c=Fake()
        with self.assertRaises(ValueError): run(c,{"controller_id":"wrong","mode":"communication","bus":1})
    def test_input(self):
        c=Fake()
        r=run(c,dict(controller_id="test",bus=1,address=2,instance=0,mode="input"))
        self.assertTrue(r["summary"]["pass"]>=17)
        self.assertIn(("feedback",0x4F,0x20,5),c.calls)
        self.assertTrue(any(x["test"]=="Feedback features" and x["value"]["colour"] for x in r["checks"]))
    def test_reject_reset(self):
        with self.assertRaises(ValueError): self.req(Fake(),"reset")
if __name__=="__main__": unittest.main()
