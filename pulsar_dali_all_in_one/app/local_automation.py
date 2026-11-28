"""Opt-in local zone automation; no broker or HA dependency.
Schedules use explicit IANA time zone; timers use monotonic time.
Only individually verified ordinary gear, no emergency or broadcast writes.
"""
import json,os,threading,time,secrets
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import button_bindings as bb

PATH=Path("/data/local_automation.json")
MAX_RULES=32
def integer(v,lo,hi):
    if type(v) is not int or not lo<=v<=hi:raise ValueError("Invalid automation value")
    return v
def boolean(v):
    if type(v) is not bool:raise ValueError("Expected boolean")
    return v
def load():
    try:
        x=json.loads(PATH.read_text())
        if not isinstance(x,dict):raise ValueError("Invalid rule store")
        return x
    except FileNotFoundError:return {}
def save(rows):
    tmp=PATH.with_suffix(".tmp")
    with tmp.open("w") as f:
        os.fchmod(f.fileno(),0o600);json.dump(rows,f);f.flush();os.fsync(f.fileno())
    tmp.replace(PATH)
def minute(v):
    if not isinstance(v,str) or len(v)!=5 or v[2]!=":":raise ValueError("Use HH:MM")
    h,m=map(int,v.split(":"))
    return integer(h,0,23)*60+integer(m,0,59)
def in_window(dt,days,start,end):
    n=dt.hour*60+dt.minute
    if start==end:return dt.weekday() in days
    if start<end:return dt.weekday() in days and start<=n<end
    return (dt.weekday() in days and n>=start) or ((dt.weekday()-1)%7 in days and n<end)
def ordinary_targets(c,b,kind,target):
    members=bb.targets(c,b,kind,target)
    with c.cache_lock:
        for a,uid,random in members:
            g=c.gear[b][a]
            types=g.get("device_types") or [g.get("device_type")]
            if not types or any(t not in (0,2,3,4,5,6,7,8,9) for t in types):
                raise ValueError("Emergency or unknown gear is not eligible")
    return [list(m) for m in members]
def sensor(c,b,ref,typ):
    if ref is None:return None
    if not isinstance(ref,dict):raise ValueError("Invalid sensor")
    a=integer(ref.get("address"),0,63);n=integer(ref.get("instance"),0,31)
    info=bb.source(c,b,a,n,False)
    if info.get("instance_type")!=typ or not info.get("enabled"):raise ValueError("Sensor type or enabled state invalid")
    return dict(address=a,instance=n)
def validate(c,d):
    b=integer(d.get("bus"),1,3)
    kind=d.get("target_kind");target=d.get("target")
    if kind=="group":target=integer(target,0,15)
    elif kind!="gear" or not isinstance(target,str) or not target:raise ValueError("Choose target")
    name=d.get("name")
    if not isinstance(name,str) or not name.strip() or len(name)>80:raise ValueError("Invalid name")
    zone=d.get("timezone","Europe/Copenhagen")
    if not isinstance(zone,str) or len(zone)>64:raise ValueError("Invalid time zone")
    ZoneInfo(zone)
    days=d.get("days",[0,1,2,3,4,5,6])
    if not isinstance(days,list) or not days or len(days)>7:raise ValueError("Choose weekdays")
    days=sorted(set(integer(x,0,6) for x in days))
    minimum=integer(d.get("min_level",20),1,254);maximum=integer(d.get("max_level",254),minimum,254)
    r=dict(name=name.strip(),bus=b,target_kind=kind,target=target,
           members=ordinary_targets(c,b,kind,target),
           enabled=boolean(d.get("enabled",False)),timezone=zone,days=days,
           schedule=boolean(d.get("schedule",False)),start=minute(d.get("start","07:00")),end=minute(d.get("end","16:00")),
           day_level=integer(d.get("day_level",180),0,254),night_level=integer(d.get("night_level",0),0,254),
           vacancy_level=integer(d.get("vacancy_level",0),0,254),
           occupancy=sensor(c,b,d.get("occupancy"),3),daylight=sensor(c,b,d.get("daylight"),4),
           hold=integer(d.get("hold",900),5,86400),sensor_timeout=integer(d.get("sensor_timeout",120),10,3600),
           setpoint=integer(d.get("setpoint",128),1,254),deadband=integer(d.get("deadband",8),1,100),
           min_level=minimum,max_level=maximum,step=integer(d.get("step",5),1,30),
           fallback=d.get("fallback","hold"),fallback_level=integer(d.get("fallback_level",180),0,254),
           override_seconds=integer(d.get("override_seconds",1800),0,86400))
    if r["fallback"] not in ("hold","level"):raise ValueError("Invalid fallback")
    if not (r["schedule"] or r["occupancy"] or r["daylight"]):raise ValueError("Select automation function")
    if r["daylight"] and not r["min_level"]<=r["day_level"]<=r["max_level"]:raise ValueError("Day level outside regulation limits")
    bb.read_levels(c,b,r)
    return r
def check_overlap(rows,r,exclude):
    members={(r["bus"],x[0]) for x in r["members"]}
    for k,other in rows.items():
        if k!=exclude and members & {(other["bus"],x[0]) for x in other["members"]}:
            raise ValueError("Target overlaps another rule; use one zone per gear")
def live_sensor(c,b,ref,typ):
    a,n=ref["address"],ref["instance"]
    info=bb.source(c,b,a,n,False)
    if c._dali2_query_instance(b,a,n,0x80)!=typ or c._dali2_query_instance(b,a,n,0x86)!=255:
        raise ValueError("Sensor missing or disabled")
    # Read resolution live; do not confuse relative input with lux.
    resolution=c._dali2_query_instance(b,a,n,0x81)
    if type(resolution) is not int or not 1<=resolution<=32:raise ValueError("Invalid resolution")
    raw=c._read_input_value(b,a,n,resolution)
    if type(raw) is not int or raw<0:raise ValueError("Sensor no reply")
    if typ==3:
        if raw not in (0,0x55,0xAA,0xFF):raise ValueError("Invalid occupancy value")
        return bool(raw&0xAA)
    if raw>(1<<resolution)-1:raise ValueError("Invalid relative light value")
    return round(raw*254/((1<<resolution)-1))

def desired(r,state,mono,wall,occupied,light,actual):
    """Pure decision: override > schedule > presence > daylight > base."""
    if state.get("override_until",0)>mono:return None,"manual_override"
    if r["schedule"]:
        if wall.year<2020:return None,"clock_invalid"
        dt=wall.astimezone(ZoneInfo(r["timezone"]))
        if not in_window(dt,r["days"],r["start"],r["end"]):
            return r["night_level"],"outside_schedule"
    if r["occupancy"]:
        if occupied is None:
            return (r["fallback_level"] if r["fallback"]=="level" else None),"occupancy_error"
        if occupied:state["last_occupied"]=mono
        if not occupied and mono-state.get("last_occupied",-1e12)>=r["hold"]:
            return r["vacancy_level"],"vacant"
    if r["daylight"]:
        if light is None:return (r["fallback_level"] if r["fallback"]=="level" else None),"daylight_error"
        if not actual:return None,"no_target"
        level=max(actual)
        if level==0:level=r["day_level"]
        elif light<r["setpoint"]-r["deadband"]:level+=r["step"]
        elif light>r["setpoint"]+r["deadband"]:level-=r["step"]
        return max(r["min_level"],min(r["max_level"],level)),"daylight"
    return r["day_level"],"occupied" if r["occupancy"] else "schedule"

class Engine:
    def __init__(self,c,log,o=None):
        self.c=c;self.log=log;self.o=bb.options() if o is None else o
        self.enabled=bool(self.o.get("local_automation_enabled",False) and c.settings.local_dali_enabled)
        self.lock=threading.RLock();self.stop_event=threading.Event();self.thread=None
        self.runtime={};self.round=0;self.own=threading.local()
    def start(self):
        if self.enabled:
            self.thread=threading.Thread(target=self.run,daemon=True,name="local-automation");self.thread.start()
    def stop(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=2)
    def snapshot(self):
        with self.lock:
            rows=load();now=time.monotonic()
            return dict(automation_enabled=self.enabled,automation_rules=[
                dict(r,id=k,runtime=dict(status=self.runtime.get(k,{}).get("status","pending" if r["enabled"] else "disabled"),
                      override_remaining=max(0,round(self.runtime.get(k,{}).get("override_until",0)-now))))
                for k,r in sorted(rows.items())])
    def external(self,b,addresses=None):
        # Called only after successful ordinary command, not during own writes.
        if not self.enabled or getattr(self.own,"active",False):return
        with self.lock:
            for k,r in load().items():
                if r["enabled"] and r["bus"]==b and (addresses is None or any(x[0] in addresses for x in r["members"])):
                    s=self.runtime.setdefault(k,{})
                    if r["override_seconds"]:s["override_until"]=time.monotonic()+r["override_seconds"]
    def action(self,d):
        if d.get("controller_id")!=self.c.controller_id:raise ValueError("Controller mismatch")
        action=d.get("action")
        if action=="automation_list":return self.snapshot()
        if d.get("confirm") is not True:raise ValueError("Explicit confirmation required")
        with self.c.operation_lock,self.lock:
            rows=load();k=d.get("id")
            if action=="automation_save":
                if not self.enabled or self.c.scan_running:raise ValueError("Enable local automation; finish scan first")
                if k is None:
                    if len(rows)>=MAX_RULES:raise ValueError("Rule limit")
                    k=secrets.token_hex(8)
                elif k not in rows:raise ValueError("Unknown rule")
                r=validate(self.c,d);check_overlap(rows,r,k);rows[k]=r;save(rows);self.runtime.pop(k,None)
            elif k not in rows:raise ValueError("Unknown rule")
            elif action=="automation_remove":
                del rows[k];save(rows);self.runtime.pop(k,None)
            elif action=="automation_enable":
                v=boolean(d.get("enabled"))
                if v and not self.enabled:raise ValueError("Local automation disabled")
                rows[k]["enabled"]=v;save(rows);self.runtime.pop(k,None)
            elif action=="automation_override":
                if not self.enabled or not rows[k]["enabled"]:raise ValueError("Rule disabled")
                seconds=integer(d.get("seconds"),0,86400)
                self.runtime.setdefault(k,{})["override_until"]=time.monotonic()+seconds
            else:raise ValueError("Unknown automation action")
            return dict(id=k,**self.snapshot())
    def tick(self):
        c=self.c
        if not self.enabled or not c.operation_lock.acquire(blocking=False):return
        try:
            if c.scan_running or self.stop_event.is_set():return
            with self.lock:
                rows=[(k,r) for k,r in sorted(load().items()) if r["enabled"]]
                if not rows:return
                k,r=rows[self.round%len(rows)];self.round+=1
                s=self.runtime.setdefault(k,{})
                now=time.monotonic()
                if s.get("override_until",0)>now:s["status"]="manual_override";return
                if now<s.get("retry_at",0):return
                try:
                    if ordinary_targets(c,r["bus"],r["target_kind"],r["target"])!=r["members"]:raise ValueError("Target changed")
                    levels=bb.read_levels(c,r["bus"],r)
                    vals=[]
                    for field,typ in (("occupancy",3),("daylight",4)):
                        ref=r[field]
                        if ref is None:vals.append(None);continue
                        try:
                            v=live_sensor(c,r["bus"],ref,typ);s[field]=(v,now);vals.append(v)
                        except Exception:
                            old=s.get(field)
                            vals.append(old[0] if old and now-old[1]<=r["sensor_timeout"] else None)
                    target,status=desired(r,s,now,datetime.now(ZoneInfo("UTC")),*vals,[v for a,v in levels])
                    s["status"]=status
                    if target is not None:
                        self.own.active=True
                        try:
                            for a,v in levels:
                                if v!=target:c.set_level(r["bus"],a,target)
                        finally:self.own.active=False
                except Exception as exc:
                    s["status"]="error: "+str(exc)[:160];s["retry_at"]=now+30
        finally:c.operation_lock.release()
    def run(self):
        while not self.stop_event.wait(3):
            try:self.tick()
            except Exception as exc:self.log("Local automation deferred: "+str(exc));self.stop_event.wait(10)

def install(cls):
    for name in ("set_level","set_group_level","broadcast_level","broadcast_command","broadcast_scene"):
        old=getattr(cls,name)
        def wrap(method,kind):
            def call(self,bus_number,*args,**kwargs):
                with self.operation_lock:
                    return locked(self,bus_number,*args,**kwargs)
            def locked(self,b,*args,**kwargs):
                r=method(self,b,*args,**kwargs)
                engine=getattr(self,"automation_engine",None)
                if engine and r.get("ok"):
                    addresses=None
                    if kind=="set_level":addresses=[args[0] if args else kwargs.get("address")]
                    elif kind=="set_group_level":
                        group=args[0] if args else kwargs.get("group")
                        with self.cache_lock:addresses=[a for a,g in self.gear.get(b,{}).items() if group in g.get("groups",[])]
                    try:engine.external(b,addresses)
                    except (OSError,ValueError):pass
                return r
            return call
        setattr(cls,name,wrap(old,name))
    old=cls.snapshot
    def snapshot(self):
        s=old(self);engine=getattr(self,"automation_engine",None)
        if engine:
            try:s.update(engine.snapshot())
            except (OSError,ValueError):s.update(automation_enabled=False,automation_rules=[],automation_error="Invalid rule store")
        return s
    cls.snapshot=snapshot
