import unittest
from front_panel import Debounce,PINS
class Tests(unittest.TestCase):
    def test_pins(self):
        self.assertEqual(PINS["vertex_g4"],{"status_red":5,"status_green":6,"network_red":7,"network_blue":3,"network_green":2})
    def test_press(self):
        d=Debounce()
        for v,t in [(False,0),(False,.1),(True,.2),(True,.3),(False,.7)]:self.assertIsNone(d.update(v,t))
        self.assertEqual(d.update(False,.8)[0],"short")
    def test_held_on_boot(self):
        d=Debounce()
        for v,t in [(True,0),(True,.1),(False,3),(False,3.1)]:self.assertIsNone(d.update(v,t))
if __name__=="__main__":unittest.main()
