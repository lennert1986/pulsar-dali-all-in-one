import threading
import unittest
from unittest.mock import Mock
from reconnect import Reconnect
class Tests(unittest.TestCase):
    def setUp(self):
        self.registry={"stable-id":dict(remote_controller_id="pulsar-b",host="192.168.1.10",
            port=8443,fingerprint="ab"*32,token="cd"*32,name="Lager",last_error="timeout")}
        self.d=Mock(enabled=True)
        self.d.status.return_value={"candidates":[dict(controller_id="pulsar-b",host="192.168.1.20",port=8443)]}
        self.save=Mock()
        self.request=Mock(side_effect=self.probe)
        self.worker=Reconnect(self.d,lambda:self.registry,self.save,threading.RLock(),self.request,Mock())
    def probe(self,item,*args,**kwargs):
        self.assertEqual(item["fingerprint"],"ab"*32)
        self.assertEqual(item["token"],"cd"*32)
        self.assertEqual(args,("GET","/api/status"))
        if item["host"]=="192.168.1.20":
            return dict(ok=True,controller_id="pulsar-b")
        raise OSError("offline")
    def test_recover_preserves_registry_and_credentials(self):
        self.worker.step()
        self.save.assert_called_once()
        self.assertEqual(list(self.registry),["stable-id"])
        self.assertEqual(self.registry["stable-id"]["host"],"192.168.1.20")
        self.assertEqual(self.registry["stable-id"]["name"],"Lager")
        self.assertEqual(self.registry["stable-id"]["last_error"],"")
        self.worker.step()
        self.save.assert_called_once()
    def test_existing_address_still_works(self):
        self.request.side_effect=lambda *a,**kw:dict(ok=True,controller_id="pulsar-b")
        self.worker.step()
        self.save.assert_not_called()
        self.assertEqual(self.registry["stable-id"]["host"],"192.168.1.10")
    def test_spoofed_identity(self):
        self.request.side_effect=lambda *a,**kw:dict(ok=True,controller_id="fake")
        self.worker.step()
        self.save.assert_not_called()
    def test_invalid_cert(self):
        self.request.side_effect=ValueError("TLS fingerprint mismatch")
        self.worker.step()
        self.save.assert_not_called()
    def test_ambiguous(self):
        self.d.status.return_value["candidates"].append(dict(controller_id="pulsar-b",host="192.168.1.21",port=8443))
        self.request.side_effect=lambda item,*a,**kw:dict(ok=item["host"]!="192.168.1.10",controller_id="pulsar-b")
        self.worker.step()
        self.save.assert_not_called()
    def test_concurrent_removal(self):
        def probe(item,*a,**kw):
            if item["host"]=="192.168.1.20":
                self.registry.clear()
                return dict(ok=True,controller_id="pulsar-b")
            raise OSError()
        self.request.side_effect=probe
        self.worker.step()
        self.save.assert_not_called()
        self.assertFalse(self.registry)
    def test_concurrent_update(self):
        def probe(item,*a,**kw):
            if item["host"]=="192.168.1.20":
                self.registry["stable-id"]["token"]="new-token"
                return dict(ok=True,controller_id="pulsar-b")
            raise OSError()
        self.request.side_effect=probe
        self.worker.step()
        self.save.assert_not_called()
        self.assertEqual(self.registry["stable-id"]["token"],"new-token")
    def test_dns_unchanged(self):
        self.registry["stable-id"]["host"]="pulsar.local"
        self.worker.step()
        self.request.assert_not_called()
if __name__=="__main__":unittest.main()
