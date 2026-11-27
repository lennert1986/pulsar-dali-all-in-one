import unittest,threading
from advanced import frame,decode_energy,decode_diagnostics,fade,color_set,commission_one,execute,memory,types
class Fake:
    def __init__(self):
        self.frames=[]; self.cache_lock=threading.RLock(); self.operation_lock=threading.RLock()
        self.gear={1:{7:{"ha_uid":"stable","online":True,"random_address":42,"device_type":6}}}
        self.controller_id="test"; self.scan_running=False
        self.settings=type("S",(),{"local_dali_enabled":True})()
        self.reply={0xA5:0x42,0xA8:0,0x99:6}
        self.control_devices={1:{}}
    def _s1on(self,b,d): self.frames.append(("once",b,d))
    def _s1tn(self,b,d): self.frames.append(("twice",b,d))
    def _s1or(self,b,d):
        self.frames.append(("query",b,d))
        return self.reply.get(d>>8)
    def _assert_unique_address(self,b,a): return 42
    def _save_cache(self): pass
class Tests(unittest.TestCase):
    def test_fade(self):
        c=Fake(); r=fade(c,1,7,"fade_time",4)
        self.assertEqual(r["fade_time"],4)
        self.assertIn(("once",1,0x04A3),c.frames)
        self.assertIn(("twice",1,0x2E0F),c.frames)
        with self.assertRaises(RuntimeError): fade(c,1,7,"fade_time",5)
    def test_wrong_controller(self):
        c=Fake()
        with self.assertRaises(ValueError): execute(c,{"controller_id":"wrong","bus":1,"action":"reset"})
        self.assertEqual(c.frames,[])
    def test_wrong_uid(self):
        c=Fake()
        with self.assertRaises(ValueError): execute(c,{"controller_id":"test","bus":1,"action":"fade","address":7,"uid":"other"})
        self.assertEqual(c.frames,[])
    def test_energy(self):
        m=[0]*16; m[3]=1; m[4]=0; m[5:11]=(123456).to_bytes(6,"big"); m[11]=255; m[12:16]=(325).to_bytes(4,"big")
        r=decode_energy(m,202)
        self.assertAlmostEqual(r["energy_kwh"],123.456)
        self.assertEqual(r["power_w"],32.5)
        m[12:16]=[255]*4
        self.assertNotIn("power_w",decode_energy(m,202))
    def test_unsupported(self):
        self.assertEqual(decode_energy([0]*16,202),{})
        c=Fake()
        with self.assertRaises(ValueError): color_set(c,1,7,{"kelvin":3000})
    def test_reset_confirmation(self):
        c=Fake()
        with self.assertRaises(ValueError): execute(c,{"controller_id":"test","bus":1,"address":7,"uid":"stable","action":"reset"})
        self.assertFalse(any(x[0]=="twice" for x in c.frames))
if __name__=="__main__": unittest.main()
