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
if __name__=="__main__":unittest.main()
