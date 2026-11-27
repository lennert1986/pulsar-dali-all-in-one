import unittest,time
from maintenance import candidates
from mqtt_bridge import catalog,request
class Tests(unittest.TestCase):
    def snap(self):
        return {"controller_id":"test","buses":{"1":{"online":True}},"gear":[{"bus":1,"address":0,"online":True,"ha_uid":"stable","random_address":42,"actual_level":127,"device_types":[8],"color_temp_kelvin":3000,"min_kelvin":2700,"max_kelvin":6500,"last_memory_bank":202}]}
    def test_jobs(self):
        s=self.snap();now=time.time()
        jobs=candidates(s,{},now,{})
        self.assertEqual({x[2]["action"] for x in jobs},{"memory","inspect"})
        self.assertEqual(len(jobs),2)
        jobs=candidates(s,{"d4i_poll_enabled":True},now,{})
        self.assertTrue(any(x[2]["bank"]==202 for x in jobs))
        s["gear"][0]["address_conflict"]=True
        self.assertFalse(candidates(s,{},now,{}))
    def test_busy(self):
        s=self.snap();s["scan_running"]=True
        self.assertFalse(candidates(s,{},time.time(),{}))
    def test_color_identity(self):
        s=self.snap()
        def light(flag): return next(e for e in catalog(s,"Test","homeassistant","av",flag).values() if e["comp"]=="light")
        old=light(False);new=light(True)
        self.assertEqual(old["config"]["unique_id"],new["config"]["unique_id"])
        self.assertEqual(new["config"]["supported_color_modes"],["color_temp"])
        path,d,t=request(new["route"],"light",'{"state":"ON","color_temp":333}')
        self.assertEqual(path,"/api/lab/run");self.assertEqual(d["uid"],"stable")
        self.assertEqual(d["kelvin"],3003)
    def test_rgb(self):
        s=self.snap();g=s["gear"][0];g.pop("color_temp_kelvin");g["rgbwaf"]=[254,0,127]
        e=next(e for e in catalog(s,"Test","homeassistant","av",True).values() if e["comp"]=="light")
        self.assertEqual(e["config"]["supported_color_modes"],["rgb"])
        self.assertEqual(request(e["route"],"light",'{"state":"ON","color":{"r":255,"g":0,"b":128}}')[1]["rgbwaf"],[254,0,127])
if __name__=="__main__": unittest.main()
