import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from pairing import Service,code
FP="ab"*32
PID="12"*16
SECRET="34"*32
def payload():return dict(id=PID,secret=SECRET,requester="pulsar-a",target="pulsar-b")
class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/"grants.json"
        self.b=Service("pulsar-b",self.path)
    def tearDown(self):self.tmp.cleanup()
    def start(self):
        self.b.allow(True)
        self.b.receive("start",payload(),"192.168.1.1",FP)
    def test_explicit_approval_revocation(self):
        with self.assertRaises(ValueError):self.b.receive("start",payload(),"192.168.1.1",FP)
        self.start()
        self.assertEqual(self.b.status(True)["incoming"][0]["code"],code(SECRET,PID,"pulsar-a","pulsar-b",FP))
        self.assertEqual(self.b.receive("finish",payload(),"192.168.1.1",FP)["state"],"pending")
        self.b.decision(PID,True)
        result=self.b.receive("finish",payload(),"192.168.1.1",FP)
        token=result["token"]
        self.assertTrue(self.b.authorized("Bearer "+token))
        self.assertNotIn(token,self.path.read_text())
        self.assertTrue(Service("pulsar-b",self.path).authorized("Bearer "+token))
        self.b.revoke(PID)
        self.assertFalse(self.b.authorized("Bearer "+token))
    def test_wrong_secret_host_cert(self):
        self.start()
        self.b.decision(PID,True)
        for data,host,fp in [(dict(payload(),secret="56"*32),"192.168.1.1",FP),(payload(),"192.168.1.2",FP),(payload(),"192.168.1.1","cd"*32)]:
            with self.assertRaises(ValueError):self.b.receive("finish",data,host,fp)
        self.assertNotEqual(code(SECRET,PID,"pulsar-a","pulsar-b",FP),code(SECRET,PID,"pulsar-a","pulsar-b","cd"*32))
        self.assertFalse(self.path.exists())
    def test_denial_expiry(self):
        self.start()
        self.b.decision(PID,False)
        self.assertEqual(self.b.receive("finish",payload(),"192.168.1.1",FP)["state"],"denied")
        self.b.incoming[PID]["expires"]=0
        with self.assertRaises(ValueError):self.b.receive("finish",payload(),"192.168.1.1",FP)
    def test_service_pair(self):
        a=Service("pulsar-a",Path(self.tmp.name)/"a.json")
        self.b.allow(True)
        def fake(host,action,data,pin=None):
            if pin is not None:self.assertEqual(pin,FP)
            return self.b.receive(action,data,"192.168.1.1",FP),FP
        with patch("pairing.wire",side_effect=fake):
            pid=a.begin(dict(host="192.168.1.2",port=8443,controller_id="pulsar-b"),"Lager")
            self.assertEqual(a.status(False)["outgoing"][0]["code"],self.b.status(True)["incoming"][0]["code"])
            self.assertEqual(a.finish(pid,lambda *x:self.fail())["state"],"pending")
            self.b.decision(pid,True)
            saved=[]
            self.assertEqual(a.finish(pid,lambda i,t:saved.append((i,t)))["state"],"complete")
            self.assertTrue(self.b.authorized("Bearer "+saved[0][1]))
            self.assertFalse(a.status(False)["outgoing"])
    def test_close(self):
        self.start()
        self.b.close()
        with self.assertRaises(ValueError):self.b.receive("finish",payload(),"192.168.1.1",FP)
    def test_only_one_master_and_legacy_blocked(self):
        self.start()
        other=dict(payload(),id="ab"*16,requester="pulsar-c")
        self.b.receive("start",other,"192.168.1.3",FP)
        self.b.decision(PID,True)
        with self.assertRaises(ValueError):self.b.decision(other["id"],True)
        self.assertFalse(self.b.authorized("Bearer legacy","legacy",True))
        token=self.b.receive("finish",payload(),"192.168.1.1",FP)["token"]
        self.assertFalse(self.b.authorized("Bearer legacy","legacy",True))
        with self.assertRaises(ValueError):self.b.allow(True)
        with self.assertRaises(ValueError):self.b.receive("start",other,"192.168.1.3",FP)
        self.assertTrue(self.b.authorized("Bearer "+token,host="192.168.1.44"))
        self.assertEqual(self.b.status(True)["grants"][0]["host"],"192.168.1.44")
        self.b.revoke(PID)
        self.b.allow(True)
        self.b.receive("start",other,"192.168.1.3",FP)
        self.b.decision(other["id"],True)
        token2=self.b.receive("finish",other,"192.168.1.3",FP)["token"]
        self.assertTrue(self.b.authorized("Bearer "+token2))
        self.assertFalse(self.b.authorized("Bearer "+token))
    def test_legacy_opt_in_and_conflicting_grants(self):
        from pairing import digest
        self.assertFalse(self.b.authorized("Bearer legacy","legacy"))
        self.assertTrue(self.b.authorized("Bearer legacy","legacy",True))
        self.b.save({PID:dict(hash=digest(SECRET),controller_id="a",host="192.168.1.1"),
                     "cd"*16:dict(hash=digest(FP),controller_id="c",host="192.168.1.3")})
        self.assertTrue(self.b.status(True)["master_conflict"])
        self.assertFalse(self.b.authorized("Bearer "+SECRET))
        self.assertFalse(self.b.authorized("Bearer "+FP))
        self.assertFalse(self.b.authorized("Bearer legacy","legacy",True))
        self.b.revoke("cd"*16)
        self.assertTrue(self.b.authorized("Bearer "+SECRET))
if __name__=="__main__":unittest.main()
