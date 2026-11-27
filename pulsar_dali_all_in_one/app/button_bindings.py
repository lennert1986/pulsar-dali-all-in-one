"""Opt-in local push-button bindings and visible feedback without MQTT.
All bus actions share operation_lock. No automatic persistent DALI writes.
"""
import json
import os
from pathlib import Path
import threading
import time
import feedback

PATH=Path("/data/button_bindings.json")
OPTIONS=Path("/data/options.json")
ACTIONS=("none","toggle","on","off","dim_up","dim_down")
MODES=("none","follow","inverse")
def options():
    try:return json.loads(OPTIONS.read_text())
    except (OSError,ValueError):return {}
def load(path=None):
    path=PATH if path is None else Path(path)
    try:
        data=json.loads(path.read_text())
        if not isinstance(data,dict):raise ValueError("Invalid bindings")
        return data
    except FileNotFoundError:return {}
def save(data,path=None):
    path=PATH if path is None else Path(path)
    tmp=path.with_suffix(".tmp")
    with tmp.open("w") as f:
        os.fchmod(f.fileno(),0o600)
        json.dump(data,f)
    tmp.replace(path)
def key(b,a,n):return f"{b}:{a}:{n}"
def intfield(v,lo,hi):
    if type(v) is not int or not lo<=v<=hi:raise ValueError("Invalid binding number")
    return v
def source(c,b,a,n,button=True):
    with c.cache_lock:
        dev=c.control_devices.get(b,{}).get(a,{})
        info=next((dict(i) for i in dev.get("instances",[]) if i.get("instance")==n),None)
    if not dev.get("online") or dev.get("address_conflict") or not info or info.get("address_conflict"):
        raise ValueError("Input device unavailable or conflicted")
    if button and (info.get("instance_type")!=1 or info.get("event_scheme")!=2 or not info.get("enabled")):
        raise ValueError("Enable push button and device/instance event scheme 2 first")
    return info
def live_source(c,b,a,n):
    source(c,b,a,n)
    if c._dali2_query_instance(b,a,n,0x80)!=1 or c._dali2_query_instance(b,a,n,0x8B)!=2 or c._dali2_query_instance(b,a,n,0x86)!=255:
        raise ValueError("Push-button instance changed or disabled")
def targets(c,b,kind,target):
    with c.cache_lock:
        rows=[dict(x,address=a) for a,x in c.gear.get(b,{}).items() if
              (kind=="gear" and x.get("ha_uid")==target) or (kind=="group" and target in x.get("groups",[]))]
    if not rows or len(rows)>16 or any(not x.get("online") or x.get("address_conflict") or not x.get("ha_uid") or x.get("random_address") is None for x in rows):
        raise ValueError("Target missing, conflicted, offline or group exceeds 16 gear")
    return sorted([(x["address"],x["ha_uid"],x["random_address"]) for x in rows])
def read_levels(c,b,binding):
    rows=targets(c,b,binding["target_kind"],binding["target"])
    if [list(x) for x in rows]!=binding["members"]:raise ValueError("Target membership or identity changed; re-save binding")
    result=[]
    for a,uid,random in rows:
        if c._assert_unique_address(b,a)!=random:raise ValueError("Physical target identity changed")
        v=c.query(b,a,"actual_level")
        if type(v) is not int or not 0<=v<=254:raise ValueError("No valid live level")
        result.append((a,v))
    return result
def config(c,b,a,n,d):
    k=key(b,a,n); rows=load()
    if d["action"]=="binding_read":return dict(binding=rows.get(k),enabled=bool(options().get("local_button_bindings_enabled",False)))
    if d.get("enabled") is False:
        rows.pop(k,None);save(rows);return dict(binding=None)
    if d.get("enabled") is not True:raise ValueError("Explicit binding enable required")
    if not options().get("local_button_bindings_enabled",False):raise ValueError("Enable local_button_bindings_enabled in add-on settings")
    live_source(c,b,a,n)
    kind=d.get("target_kind")
    target=d.get("target")
    if kind=="group":target=intfield(target,0,15)
    elif kind!="gear" or not isinstance(target,str) or not target:raise ValueError("Invalid target")
    short=d.get("short_action","none");long=d.get("long_action","none");mode=d.get("feedback_mode","none")
    if short not in ACTIONS or long not in ACTIONS or mode not in MODES:raise ValueError("Unknown binding action")
    if short==long=="none" and mode=="none":raise ValueError("Select at least one action")
    # Event filter and source addressing must be configured before enabling.
    if mode!="none":feedback.steady(c,b,a,n)
    members=targets(c,b,kind,target)
    item=dict(target_kind=kind,target=target,short_action=short,long_action=long,feedback_mode=mode,
              members=[list(x) for x in members],created=time.time())
    read_levels(c,b,item)
    if len(rows)>=32 and k not in rows:raise ValueError("At most 32 local bindings")
    rows[k]=item;save(rows);return dict(binding=item)
def state(c,b,a,n):
    info=source(c,b,a,n,False)
    if c._dali2_query_device(b,a,0x30) is None:raise ValueError("Input device offline")
    return info
def mqtt_command(c,b,a,n,value):
    if not options().get("feedback_mqtt_enabled",False):raise ValueError("MQTT feedback disabled")
    if load().get(key(b,a,n),{}).get("feedback_mode","none")!="none":raise ValueError("Automatic feedback owns this LED")
    state(c,b,a,n)
    feedback.steady(c,b,a,n)
    return feedback.command(c,b,a,n,value)
def enrich(snapshot):
    try: rows=load(); o=options()
    except (OSError,ValueError):rows={};o={}
    snapshot["feedback_mqtt_enabled"]=bool(o.get("feedback_mqtt_enabled",False))
    snapshot["local_button_bindings_enabled"]=bool(o.get("local_button_bindings_enabled",False))
    for item in snapshot.get("input_instances",[]):
        binding=rows.get(key(item["bus"],item["address"],item["instance"]))
        if binding:item["local_binding"]=binding
    return snapshot

class Worker:
    def __init__(self,c,log,o=None):
        self.c=c;self.log=log;self.o=options() if o is None else o
        self.stop_event=threading.Event();self.thread=None
        self.cursor=0;self.next_sync=0;self.round=0;self.last={};self.repeat={}
    def start(self):
        if not self.c.settings.local_dali_enabled or not self.o.get("local_button_bindings_enabled",False):return
        self.cursor=self.c.events_since(0,0)["latest_id"]
        self.thread=threading.Thread(target=self.run,daemon=True,name="local-button-bindings");self.thread.start()
    def stop(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=2)
    def event(self,e,rows):
        if e.get("instance_type")!=1 or e.get("event_type") not in ("short_press","long_press_start","long_press_repeat"):return
        if not 0<=time.time()-e.get("timestamp",0)<=3:return
        b,a,n=(e.get(k) for k in ("bus","address","instance"));k=key(b,a,n);item=rows.get(k)
        if not item or e["timestamp"]<item["created"]:return
        typ=e["event_type"];action=item["short_action"] if typ=="short_press" else item["long_action"]
        if action=="none" or (typ=="long_press_repeat" and action not in ("dim_up","dim_down")):return
        now=time.monotonic()
        if now-self.repeat.get(k,-100)<0.4:return
        self.repeat[k]=now
        c=self.c;live_source(c,b,a,n)
        levels=read_levels(c,b,item)
        on=any(v>0 for _,v in levels)
        for addr,v in levels:
            level={"toggle":0 if on else 254,"on":254,"off":0,"dim_up":min(254,v+20),"dim_down":max(0,v-20)}[action]
            if level!=v:c.set_level(b,addr,level)
        self.next_sync=0
    def sync(self,rows):
        active_rows=[(k,v) for k,v in sorted(rows.items()) if v.get("feedback_mode") in ("follow","inverse")]
        if not active_rows:return
        k,item=active_rows[self.round%len(active_rows)];self.round+=1
        b,a,n=map(int,k.split(":"));c=self.c
        live_source(c,b,a,n)
        on=any(v>0 for _,v in read_levels(c,b,item))
        desired=bool(on if item["feedback_mode"]=="follow" else not on)
        now=time.monotonic()
        prior=self.last.get(k)
        # Reassert periodically (e.g. power cycle), not on every poll.
        if prior and prior[0]==desired and now-prior[1]<60:return
        feedback.steady(c,b,a,n)
        r=feedback.command(c,b,a,n,int(desired))
        if r["target_responded"] and (not desired or r["readback_verified"]):self.last[k]=(desired,now)
    def step(self):
        c=self.c
        report=c.events_since(self.cursor,0);self.cursor=report["latest_id"]
        if not c.operation_lock.acquire(blocking=False):return
        try:
            if c.scan_running or self.stop_event.is_set():return
            rows=load()
            # Bounded processing; never replay a queue after a scan/restart.
            for e in report["events"][-8:]:
                try:self.event(e,rows)
                except Exception as exc:self.log("Local button action deferred: "+str(exc))
            now=time.monotonic()
            if now>=self.next_sync:
                self.next_sync=now+3
                try:self.sync(rows)
                except Exception as exc:self.log("Feedback sync deferred: "+str(exc))
        finally:c.operation_lock.release()
    def run(self):
        while not self.stop_event.wait(.2):
            try:self.step()
            except Exception:self.stop_event.wait(2)
