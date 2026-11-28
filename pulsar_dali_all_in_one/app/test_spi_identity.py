import unittest,struct
from spi_identity import identify,jedec,density
class Fake:
    def __init__(self,raw=b"\xef\x40\x17",sf=True):
        self.raw=raw;self.sf=sf;self.calls=[];self.closed=False
    def id(self):self.calls.append("id");return self.raw
    def sfdp(self,a,n):
        self.calls.append((a,n))
        if not self.sf:return bytes(n)
        return {(0,8):b"SFDP\x06\x01\x00\xff",(8,8):b"\x00\x06\x01\x09\x30\x00\x00\xff",(52,4):struct.pack("<I",0x03ffffff)}[(a,n)]
    def close(self):self.closed=True
class Test(unittest.TestCase):
    def test_known(self):
        f=Fake();r=identify(lambda:f)
        self.assertEqual(r["jedec_id"],"EF 40 17")
        self.assertEqual(r["manufacturer"],"Winbond")
        self.assertEqual(r["jedec_capacity_bytes"],8388608)
        self.assertEqual(r["sfdp_capacity_bytes"],8388608)
        self.assertFalse(r["capacity_mismatch"]);self.assertFalse(r["payload_read"]);self.assertTrue(f.closed)
        self.assertEqual(f.calls,["id","id",(0,8),(8,8),(52,4)])
    def test_unknown(self):
        for raw in (b"\xff\xff\xff",b"\0\0\0",b"\x7f\x40\x17"):
            f=Fake(raw);self.assertEqual(identify(lambda:f)["status"],"no_valid_id");self.assertEqual(f.calls,["id","id"])
        f=Fake(b"\x99\x40\x17");r=identify(lambda:f)
        self.assertEqual(r["sfdp_status"],"not_probed_unknown_family");self.assertNotIn("jedec_capacity_bytes",r)
    def test_no_sfdp(self):
        f=Fake(sf=False);self.assertEqual(identify(lambda:f)["sfdp_status"],"not_detected")
    def test_density(self):
        self.assertEqual(density(struct.pack("<I",0x8000001a)),8388608)
        self.assertIsNone(density(b"\xff"*4))
        self.assertIsNone(density(struct.pack("<I",0x800000ff)))
    def test_errors(self):
        def missing():raise FileNotFoundError()
        def denied():raise PermissionError()
        self.assertEqual(identify(missing)["status"],"device_missing")
        self.assertEqual(identify(denied)["status"],"permission_denied")
        f=Fake();f.sfdp=lambda *a: (_ for _ in ()).throw(OSError())
        self.assertEqual(identify(lambda:f)["status"],"communication_error");self.assertTrue(f.closed)
if __name__=="__main__":unittest.main()
