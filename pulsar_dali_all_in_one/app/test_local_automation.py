import tempfile,unittest,threading,time
from pathlib import Path
from unittest.mock import patch
from datetime import datetime,timezone
import local_automation as la
from test_button_bindings import Fake as Base

class Fake(Base):
    def __init__(self):
        super().__init__()
        self.gear[1][7]["device_type"]=6
        self.control_devices[1][2]["instances"][0].update(instance_type=3,enabled=True)
        self.occupied=255
    def _dali2_query_instance(self,b,a,n,op):
        return {0x80:3,0x86:255,0x81:8,0x8C:self.occupied}.get(op)

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=patch.object(la,"PATH",Path(self.tmp.name)/"rules.json");self.path.start()
        self.c=Fake()
        self.e=la.Engine(self.c,lambda s:None,{"local_automation_enabled":True})
    def tearDown(self):
        self.path.stop();self.tmp.cleanup()
    def data(self,**kw):
        return dict(dict(controller_id="test",action="automation_save",confirm=True,name="Room",bus=1,target_kind="gear",target="lamp",enabled=True,occupancy={"address":2,"instance":3},hold=10),**kw)
    def test_schedule(self):
        mon=datetime(2026,11,30,22,tzinfo=timezone.utc)
        tue=datetime(2026,12,1,1,tzinfo=timezone.utc)
        self.assertTrue(la.in_window(mon,[0],22*60,6*60))
        self.assertTrue(la.in_window(tue,[0],22*60,6*60))
        self.assertFalse(la.in_window(tue,[1],22*60,6*60))
    def test_engine(self):
        k=self.e.action(self.data())["id"]
        self.e.tick();self.assertEqual(self.c.commands,[180])
        self.assertEqual(self.e.snapshot()["automation_rules"][0]["runtime"]["status"],"occupied")
        self.e.action(dict(controller_id="test",action="automation_override",id=k,seconds=1800,confirm=True))
        self.c.level=50;self.e.tick();self.assertEqual(self.c.commands,[180])
        self.e.action(dict(controller_id="test",action="automation_override",id=k,seconds=0,confirm=True))
        self.e.tick();self.assertEqual(self.c.commands,[180,180])
        self.e.external(1,[7]);self.assertGreater(self.e.snapshot()["automation_rules"][0]["runtime"]["override_remaining"],0)
        self.e.action(dict(controller_id="test",action="automation_enable",id=k,enabled=False,confirm=True))
        self.assertFalse(la.load()[k]["enabled"])
    def test_vacancy_and_sensor_failure(self):
        r=la.validate(self.c,self.data())
        s={};wall=datetime.now(timezone.utc)
        self.assertEqual(la.desired(r,s,100,wall,True,None,[0]),(180,"occupied"))
        self.assertEqual(la.desired(r,s,105,wall,False,None,[180]),(180,"occupied"))
        self.assertEqual(la.desired(r,s,111,wall,False,None,[180]),(0,"vacant"))
        self.assertEqual(la.desired(r,s,112,wall,None,None,[180]),(None,"occupancy_error"))
        r.update(fallback="level",fallback_level=100)
        self.assertEqual(la.desired(r,s,112,wall,None,None,[180]),(100,"occupancy_error"))
    def test_priority_and_daylight(self):
        r=la.validate(self.c,self.data())
        r.update(daylight={"address":3,"instance":0},min_level=20,max_level=200,step=5)
        s={};wall=datetime.now(timezone.utc)
        self.assertEqual(la.desired(r,s,10,wall,True,100,[180]),(185,"daylight"))
        self.assertEqual(la.desired(r,s,11,wall,True,200,[180]),(175,"daylight"))
        self.assertEqual(la.desired(r,s,12,wall,True,128,[180]),(180,"daylight"))
        s["override_until"]=100
        self.assertEqual(la.desired(r,s,13,wall,True,0,[180]),(None,"manual_override"))
    def test_conflict_and_emergency(self):
        self.e.action(self.data())
        with self.assertRaises(ValueError):self.e.action(self.data(name="Overlap"))
        self.c.gear[1][7]["device_types"]=[1,6]
        with self.assertRaises(ValueError):la.validate(self.c,self.data())
    def test_identity_change(self):
        self.e.action(self.data())
        self.c.gear[1][7]["random_address"]=99
        self.e.tick();self.assertEqual(self.c.commands,[])
        self.assertTrue(self.e.snapshot()["automation_rules"][0]["runtime"]["status"].startswith("error"))
    def test_opt_in_and_confirm(self):
        e=la.Engine(self.c,lambda s:None,{})
        with self.assertRaises(ValueError):e.action(self.data())
        with self.assertRaises(ValueError):self.e.action(self.data(confirm=False))
        self.assertFalse(la.load())

if __name__=="__main__":unittest.main()
