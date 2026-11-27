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


class IdentityTests(unittest.TestCase):
    def test_real_gear(self):
        from advanced import decode_identity
        m=[159,None,2,6,87,48,74,170,149,48,0,255,3,200,106,253,21,152,10,1,0,8,8,255,0,1,0]
        r=decode_identity(m,8)
        self.assertEqual(r["gtin"],"06971542121109")
        self.assertEqual(r["identification_raw"],"FF03C86AFD15980A")
        self.assertEqual(r["driver_firmware"],"48.0")
        self.assertEqual(r["iec102"],"2.0")
    def test_missing_bytes(self):
        from advanced import decode_energy,decode_identity
        m=[None]*27;m[2]=2
        self.assertEqual(decode_identity(m,8),{"last_memory_bank":2})
        self.assertEqual(decode_energy([None]*16,202),{})
if __name__=="__main__": unittest.main()
