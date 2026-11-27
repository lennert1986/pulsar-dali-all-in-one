import unittest
from mqtt_bridge import catalog,request
from pulsar_dali_control import Settings,ActivityLEDs,PulsarDali
class Tests(unittest.TestCase):
    def test_remote_only(self):
        s=Settings(local_dali_enabled=False,led_enabled=False)
        c=PulsarDali(s,ActivityLEDs(s),"test")
        self.assertEqual(c.transports,{})
        self.assertEqual(c.snapshot()["gear"],[])
        with self.assertRaises(RuntimeError): c.scan([1])
        c.close()
    def test_catalog(self):
        s={"controller_id":"test","buses":{"1":{"online":True,"uart_ready":True}},"gear":[{"bus":1,"address":7,"ha_uid":"stable","online":True,"actual_level":127,"entity_kind":"light"}]}
        def entry(): return next(e for e in catalog(s,"Test","homeassistant","av").values() if e["comp"]=="light")
        a=entry()
        self.assertTrue(a["ok"])
        self.assertEqual(request(a["route"],"light",'{"state":"ON","brightness":100}')[1]["level"],100)
        s["gear"][0]["address"]=9
        self.assertEqual(entry()["config"]["unique_id"],a["config"]["unique_id"])
        self.assertEqual(entry()["route"]["address"],9)
        s["gear"][0]["address_conflict"]=True
        self.assertFalse(entry()["ok"])
if __name__=="__main__": unittest.main()
