import unittest,tempfile
from pathlib import Path
from unittest.mock import patch
import hardware_diagnostics as hw
class Tests(unittest.TestCase):
    def test_luks_allowlist(self):
        sample="""LUKS header information
Version:        2
UUID:           12345678-1234-1234-1234-123456789abc
Data segments:
  0: crypt
        cipher: aes-xts-plain64
Keyslots:
  0: luks2
        Key: 512 bits
        PBKDF: argon2id
        Salt: MUST_NOT_LEAK
        AF hash: sha256
Tokens:
  0: secret token
Digests:
  0: pbkdf2
        Digest: MUST_NOT_LEAK
"""
        x=hw.parse_luks(sample)
        self.assertEqual(x["version"],2)
        self.assertEqual(x["ciphers"],["aes-xts-plain64"])
        self.assertEqual(x["key_bits_reported"],[512])
        self.assertEqual(x["keyslots"],1)
        self.assertEqual(x["kdf"],["argon2id"])
        self.assertNotIn("MUST_NOT_LEAK",str(x))
        self.assertNotIn("secret token",str(x))
    def test_luks1(self):
        x=hw.parse_luks("Version: 1\nCipher name: aes\nCipher mode: xts-plain64\nMK bits: 512\nMK digest: secret\n")
        self.assertEqual(x,dict(version=1,cipher_name="aes",cipher_mode="xts-plain64",key_bits=512))
    def test_unavailable(self):
        with patch.object(hw,"entries",return_value=[]):
            self.assertEqual(hw.spi()["devices"],[])
            self.assertFalse(hw.spi()["payload_read"])
            self.assertEqual(hw.partitions()["encryption"],[])
            self.assertEqual(hw.emmc(),[])
            self.assertEqual(hw.rtc(),[])
    def test_monitor(self):
        class C:
            controller_id="test"
            settings=type("S",(),{"hardware_model":"remote_only"})()
            def snapshot(self):return {"buses":{"1":{"online":True,"uart_ready":True,"firmware":"2.1.14","token":"secret"}}}
        m=hw.Monitor(C(),lambda s:None)
        self.assertTrue(m.status()["pending"])
        with patch.object(hw,"entries",return_value=[]),patch.object(hw,"cpu_sample",return_value=(100,50)):
            m.step()
        self.assertEqual(m.status()["controller_id"],"test")
        self.assertEqual(m.status()["buses"]["1"]["firmware"],"2.1.14")
        self.assertNotIn("token",m.status()["buses"]["1"])
if __name__=="__main__":unittest.main()
