import tempfile,unittest
from pathlib import Path
from hardware_profile import resolve,ftdi_interfaces,G4
class Profiles(unittest.TestCase):
    def test_g4(self):
        r=resolve({},model="Raspberry Pi Compute Module 4",present=lambda p:p in G4)
        self.assertEqual(r["hardware_profile"],"vertex_g4")
        self.assertEqual(r["i2c_bus"],1)
        self.assertEqual(r["dali3_device"],G4[2])
    def test_g3_interface_order(self):
        g={"usb-1":{0:["/dev/ttyUSB8"],1:["/dev/ttyUSB3"],2:["/dev/ttyUSB6"],3:["/dev/ttyUSB0"]}}
        r=resolve({},model="Raspberry Pi Compute Module 3 Plus",groups=g,present=lambda p:True)
        self.assertEqual(r["hardware_profile"],"vertex_g3")
        self.assertEqual(r["i2c_bus"],0)
        self.assertEqual([r["dali%d_device"%i] for i in (1,2,3)],["/dev/ttyUSB8","/dev/ttyUSB3","/dev/ttyUSB6"])
    def test_ambiguity(self):
        g={"one":{0:["/dev/ttyUSB0"],1:["/dev/ttyUSB1"],2:["/dev/ttyUSB2"]},"two":{0:["/dev/ttyUSB4"]}}
        r=resolve({"hardware_model":"vertex_g3"},groups=g,present=lambda p:True)
        self.assertFalse(r["local_dali_enabled"])
        self.assertEqual(r["hardware_profile"],"unavailable")
        self.assertTrue(r["hardware_error"])
    def test_missing(self):
        r=resolve({"hardware_model":"vertex_g4"},present=lambda p:False)
        self.assertFalse(r["local_dali_enabled"])
        self.assertFalse(r["led_enabled"])
    def test_master(self):
        r=resolve({"hardware_model":"remote_only"},present=lambda p:self.fail("must not probe"))
        self.assertFalse(r["local_dali_enabled"])
        self.assertEqual(r["hardware_profile"],"remote_only")
    def test_custom_legacy(self):
        r=resolve({"dali1_device":"/dev/ttyUSB8","dali2_device":"/dev/ttyUSB9","dali3_device":"/dev/ttyUSB10","i2c_bus":0},model="unknown",present=lambda p:True)
        self.assertEqual(r["hardware_profile"],"manual")
        self.assertEqual(r["i2c_bus"],0)
    def test_sysfs(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); tty=root/"tty"; tty.mkdir()
            usb=root/"usb"/"1-2"; usb.mkdir(parents=True)
            (usb/"idVendor").write_text("0403\n"); (usb/"idProduct").write_text("6011\n")
            for n,port in [(0,"ttyUSB9"),(1,"ttyUSB4"),(2,"ttyUSB7")]:
                iface=usb/("1-2:1.%d"%n); iface.mkdir()
                (iface/"bInterfaceNumber").write_text("%02x\n"%n)
                serial=iface/port; serial.mkdir()
                entry=tty/port; entry.mkdir(); (entry/"device").symlink_to(serial)
            g=ftdi_interfaces(tty,"/dev",present=lambda p:True)
            self.assertEqual(list(g.values())[0][1],["/dev/ttyUSB4"])
            r=resolve({"hardware_model":"vertex_g3"},groups=g,present=lambda p:True)
            self.assertEqual(r["dali1_device"],"/dev/ttyUSB9")
if __name__=="__main__": unittest.main()
