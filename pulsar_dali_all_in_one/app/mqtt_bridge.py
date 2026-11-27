"""MQTT Discovery for local and TLS-pinned remote Pulsar controllers."""
import hashlib,json,os,queue,re,threading,time,urllib.request
from pathlib import Path
import paho.mqtt.client as mqtt

PARAMS={"min_level":"Minimum level","max_level":"Maximum level","power_on_level":"Power-on level","system_failure_level":"System failure level","fade_time":"Fade time code","fade_rate":"Fade rate code","extended_fade_time":"Extended fade code"}
EVENTS=["button_pressed","button_released","short_press","double_press","long_press_start","long_press_repeat","long_press_stop","button_free","button_stuck","button_event"]
def key(s):
    s=str(s)
    return re.sub(r"[^a-zA-Z0-9_-]","_",s)[:80]+"_"+hashlib.sha256(s.encode()).hexdigest()[:10]
def js(x): return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"))
def options():
    try: return json.loads(Path("/data/options.json").read_text())
    except (OSError,ValueError): return {}
def broker(o):
    if o.get("mqtt_host"):
        return dict(host=o["mqtt_host"],port=o.get("mqtt_port",1883),username=o.get("mqtt_username"),password=o.get("mqtt_password"),ssl=o.get("mqtt_tls",False))
    req=urllib.request.Request("http://supervisor/services/mqtt",headers={"Authorization":"Bearer "+os.environ["SUPERVISOR_TOKEN"]})
    with urllib.request.urlopen(req,timeout=5) as r: return json.load(r)["data"]

def catalog(s,name,prefix,bridge_av):
    cid=str(s["controller_id"]); root="pulsar_dali_aio/"+key(cid); out={}
    gear=s.get("gear",[]); buses=s.get("buses",{}); busy=s.get("scan_running",False)
    index={(g["bus"],g["address"]):g for g in gear}
    def bus_ok(b):
        x=buses.get(str(b),{})
        return x.get("online") and x.get("uart_ready",True)
    def good(g):
        return g and g.get("online") and not g.get("address_conflict") and bus_ok(g["bus"])
    def dev(suffix,label,model):
        return dict(identifiers=[cid+":"+suffix],name=name+" "+label,manufacturer="Pulsar DALI",model=model)
    def add(comp,suffix,device,label,ok,state=None,route=None,**extra):
        uid=key(cid+":"+suffix); base=root+"/"+key(suffix); topic=prefix+"/"+comp+"/"+uid+"/config"
        av=base+"/availability"
        c=dict(name=label,unique_id=uid,device=device,availability=[{"topic":bridge_av},{"topic":av}],availability_mode="all")
        c.update(extra)
        if comp not in ("scene","button"): c["state_topic"]=base+"/state"
        if route: c["command_topic"]=base+"/set"
        out[topic]=dict(config=c,av=av,ok=bool(ok and not busy),state=state,route=route,comp=comp,state_topic=base+"/state",cmd=base+"/set" if route else None)
    def light(suffix,device,label,ok,level,route,on=None):
        valid=isinstance(level,int) and 0<=level<=254
        add("light",suffix,device,label,ok and valid,dict(state="ON" if (level if on is None else on) else "OFF",brightness=level) if valid else None,route,schema="json",brightness=True,brightness_scale=254,supported_color_modes=["brightness"],optimistic=False,retain=False)
    for g in gear:
        b,a=g["bus"],g["address"]; uid=str(g.get("ha_uid") or f"{b}_{a}"); suf="gear_"+uid
        d=dev(suf,f"DALI {b} - {a}","Control gear"); ok=good(g); level=g.get("actual_level")
        if g.get("name"): d["name"]=name+" "+g["name"]
        if g.get("driver_firmware"): d["sw_version"]=g["driver_firmware"]
        if g.get("driver_hardware"): d["hw_version"]=g["driver_hardware"]
        if g.get("identification_raw"): d["serial_number"]=g["identification_raw"]
        route=dict(kind="gear",bus=b,address=a,uid=uid)
        if g.get("entity_kind")=="switch":
            add("switch",suf+"_switch",d,"Relay",ok and level is not None,"ON" if level else "OFF",route,retain=False)
        else: light(suf+"_light",d,"Light",ok,level,route)
        for param,label in PARAMS.items():
            value=g.get(param)
            if value is not None:
                maximum={"min_level":254,"max_level":254,"fade_time":15,"fade_rate":15,"extended_fade_time":79}.get(param,255)
                minimum=1 if param=="fade_rate" else 0
                add("number",suf+"_"+param,d,label,ok,str(value),dict(route,kind="parameter",parameter=param,maximum=maximum,minimum=minimum),min=minimum,max=maximum,step=1,mode="box",entity_category="config",enabled_by_default=False,retain=False)
        for field,label,unit,device_class,state_class,bank in (
            ("gtin","GTIN",None,None,None,None),("identification_raw","Identification",None,None,None,None),
            ("driver_firmware","Driver firmware",None,None,None,None),
            ("energy_kwh","Sampled active energy","kWh","energy","total_increasing",202),
            ("power_w","Sampled active power","W","power","measurement",202),
            ("gear_operation_seconds","Sampled gear operation time","s","duration","total_increasing",205),
            ("gear_start_counter","Sampled gear starts",None,None,"total_increasing",205),
            ("gear_temperature_c","Sampled gear temperature","°C","temperature","measurement",205),
            ("light_on_seconds","Sampled light on time","s","duration","total_increasing",206),
            ("light_temperature_c","Sampled light temperature","°C","temperature","measurement",206),
            ("battery_percent","Last read emergency battery","%","battery",None,None),
            ("emergency_failure","Last read emergency failure byte",None,None,None,None)):
            value=g.get(field)
            if value is not None:
                extra=dict(entity_category="diagnostic",enabled_by_default=False)
                if unit: extra["unit_of_measurement"]=unit
                if device_class: extra["device_class"]=device_class
                if state_class: extra["state_class"]=state_class
                fresh=bank is None or time.time()-g.get("sampled_bank_"+str(bank),0)<900
                add("sensor",suf+"_"+field,d,label,ok and fresh,str(value),**extra)
        for action,label,bank in [("inspect","Read advanced properties",None),("memory","Read identification",0)]+[
            ("memory",f"Read memory bank {n}",n) for n in (202,205,206) if g.get("last_memory_bank",0)>=n]:
            add("button",suf+"_read_"+str(bank if bank is not None else action),d,label,ok,
                route=dict(route,kind="advanced_read",action=action,bank=bank,controller_id=cid),
                payload_press="PRESS",entity_category="config",enabled_by_default=False)
        for field in ("control_gear_failure","lamp_failure","limit_error"):
            value=g.get(field)
            add("binary_sensor",suf+"_"+field,d,field.replace("_"," ").capitalize(),ok and value is not None,None if value is None else "ON" if value else "OFF",device_class="problem",entity_category="diagnostic",enabled_by_default=False)
        add("button",suf+"_identify",d,"Identify",ok,route=dict(route,kind="identify"),payload_press="PRESS",entity_category="config",enabled_by_default=False)
    for g in s.get("groups",[]):
        b,n=g["bus"],g["group"]; suf=f"group_{b}_{n}"; members=g.get("members",[])
        ok=bool(members) and all(good(index.get((b,a))) for a in members)
        light(suf,dev(suf,f"DALI {b} - Group {n}","Group"),"Light",ok,g.get("actual_level"),dict(kind="group",bus=b,group=n),g.get("is_on"))
    for g in s.get("scenes",[]):
        b,n=g["bus"],g["scene"]; suf=f"scene_{b}_{n}"; members=g.get("members",[])
        ok=bool(members) and all(good(index.get((b,a))) for a in members) and not any(x.get("address_conflict") for x in gear if x["bus"]==b)
        add("scene",suf,dev(suf,f"DALI {b} - Scene {n}","Scene"),"Activate",ok,route=dict(kind="scene",bus=b,scene=n),payload_on="ON")
    devices={(x["bus"],x["address"]):x for x in s.get("control_devices",[])}
    for i in s.get("input_instances",[]):
        b,a,n=i["bus"],i["address"],i["instance"]; t=i.get("instance_type"); suf=f"input_{b}_{a}_{n}"
        d=dev(f"input_{b}_{a}",f"DALI {b} - Input {a}","DALI-2 input")
        ok=bus_ok(b) and devices.get((b,a),{}).get("online")
        if t==1: add("event",suf,d,f"Button {n}",ok,event_types=EVENTS,device_class="button")
        elif t==3:
            v=i.get("occupied")
            add("binary_sensor",suf,d,f"Occupancy {n}",ok and v is not None,None if v is None else "ON" if v else "OFF",device_class="occupancy")
        elif t in (2,4):
            v=i.get("relative_illuminance" if t==4 else "absolute_input",i.get("input_value"))
            add("sensor",suf,d,f"{'Relative illuminance' if t==4 else 'Input value'} {n}",ok and v is not None,None if v is None else str(v),state_class="measurement")
    add("button","scan",dev("controller","Controller","Pulsar DALI"),"Scan all buses",any(bus_ok(b) for b in (1,2,3)),route=dict(kind="scan"),payload_press="PRESS",entity_category="config")
    return out

def request(route,comp,payload):
    k=route["kind"]
    if k=="scan" and payload=="PRESS": return "/api/scan",{"buses":[1,2,3]},300
    d={"bus":route["bus"]}
    if k in ("gear","parameter","identify"): d["address"]=route["address"]
    if k in ("gear","group"):
        if comp=="switch":
            if payload not in ("ON","OFF"): raise ValueError("Invalid switch")
            level=254 if payload=="ON" else 0
        else:
            c=json.loads(payload)
            if c["state"] not in ("ON","OFF"): raise ValueError("Invalid state")
            v=c.get("brightness",254)
            if type(v)!=int or not 0<=v<=254: raise ValueError("Invalid brightness")
            level=max(1,v) if c["state"]=="ON" else 0
        d["level"]=level
        if k=="group": d["group"]=route["group"]
        return "/api/"+k+"/control",d,15
    if k=="parameter":
        v=float(payload)
        if not v.is_integer() or not route.get("minimum",0)<=v<=route["maximum"]: raise ValueError("Invalid parameter")
        d.update(parameter=route["parameter"],value=int(v))
        return "/api/gear/config",d,30
    if k=="advanced_read" and payload=="PRESS":
        d.update(mode="advanced",action=route["action"],uid=route["uid"],address=route["address"],controller_id=route["controller_id"],bank=route.get("bank"))
        return "/api/lab/run",d,60
    if k=="identify" and payload=="PRESS": return "/api/gear/identify",d,15
    if k=="scene" and payload=="ON":
        d["scene"]=route["scene"]; return "/api/scene/activate",d,15
    raise ValueError("Invalid command")

class Bridge:
    def __init__(self,controller,settings,log,registry,remote_request):
        self.ctl=controller; self.settings=settings; self.log=log; self.registry=registry; self.remote_request=remote_request
        self.o=options(); self.enabled=self.o.get("mqtt_enabled",True); self.discovery=self.o.get("mqtt_auto_discovery",True)
        self.prefix=self.o.get("mqtt_discovery_prefix","homeassistant").strip("/")
        if not self.prefix or any(c in self.prefix for c in "#+\x00"): self.prefix="homeassistant"
        self.av="pulsar_dali_aio/bridge/"+key(controller.controller_id)+"/availability"
        self.stop_event=threading.Event(); self.connected=threading.Event(); self.force=threading.Event()
        self.routes={}; self.sent={}; self.cursors={}; self.q=queue.Queue(128); self.client=None
        self.error=""; self.counts=(0,0); self.path=Path("/data/mqtt_discovery.json")
        try: self.known=json.loads(self.path.read_text())
        except (OSError,ValueError): self.known={}
        if not isinstance(self.known,dict): self.known={}
    def status(self):
        return dict(enabled=self.enabled,connected=self.connected.is_set(),controllers=self.counts[0],entities=self.counts[1],error=self.error)
    def start(self):
        if self.enabled:
            for fn in (self.run,self.worker): threading.Thread(target=fn,daemon=True,name="MQTT-"+fn.__name__).start()
    def stop(self):
        self.stop_event.set()
        if self.client:
            try:
                if self.connected.is_set(): self.client.publish(self.av,"offline",qos=1,retain=True).wait_for_publish(2)
                self.client.disconnect(); self.client.loop_stop()
            except Exception: pass
        self.connected.clear()
    def connect(self):
        cfg=broker(self.o)
        if hasattr(mqtt,"CallbackAPIVersion"): c=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id=key(self.ctl.controller_id)[:64],clean_session=True)
        else: c=mqtt.Client(client_id=key(self.ctl.controller_id)[:64],clean_session=True)
        if cfg.get("username"): c.username_pw_set(cfg["username"],cfg.get("password"))
        if cfg.get("ssl"): c.tls_set()
        c.will_set(self.av,"offline",qos=1,retain=True)
        c.on_connect=self.on_connect; c.on_disconnect=self.on_disconnect; c.on_message=self.on_message
        c.reconnect_delay_set(1,30); c.connect_async(cfg["host"],int(cfg["port"]),20)
        self.client=c; c.loop_start()
    def on_connect(self,c,u,f,rc,properties=None):
        if rc!=0: self.error="MQTT connection refused"; return
        c.subscribe("pulsar_dali_aio/+/+/set"); c.subscribe(self.prefix+"/status")
        self.routes={}; self.force.set(); self.connected.set(); self.error=""
        c.publish(self.av,"online",qos=1,retain=True)
        self.log("MQTT connected")
    def on_disconnect(self,c,u,*args):
        self.connected.clear(); self.routes={}
        while True:
            try: self.q.get_nowait()
            except queue.Empty: break
    def on_message(self,c,u,m):
        if m.topic==self.prefix+"/status":
            if m.payload==b"online": self.force.set()
            return
        if m.retain or not self.connected.is_set() or len(m.payload)>1024 or m.topic not in self.routes: return
        try: self.q.put_nowait((time.monotonic(),m.topic,m.payload.decode()))
        except (queue.Full,UnicodeError): pass
    def publish(self,t,v,retain=True,force=False):
        if not self.connected.is_set(): return False
        p=v if isinstance(v,str) else js(v)
        if retain and not force and self.sent.get(t)==p: return True
        info=self.client.publish(t,p,qos=1 if retain else 0,retain=retain)
        if info.rc!=mqtt.MQTT_ERR_SUCCESS: return False
        if retain: self.sent[t]=p
        return True
    def targets(self):
        d={}
        if (self.settings.local_dali_enabled or getattr(self.settings,"hardware_error","")) and self.o.get("mqtt_publish_local",True): d["local"]=("Local Pulsar",None)
        seen={self.ctl.controller_id}
        if self.o.get("mqtt_publish_remote",True):
            for rid,x in sorted(self.registry().items()):
                cid=x.get("remote_controller_id")
                if not cid or cid in seen: continue
                seen.add(cid); d[rid]=(x.get("name") or "Remote Pulsar",x)
        return d
    def snapshot(self,target):
        if target[1] is None:
            if getattr(self.settings,"hardware_error",""): raise RuntimeError("Local hardware unavailable")
            return self.ctl.snapshot()
        x=self.remote_request(target[1],"GET","/api/devices",timeout=5)
        if x.get("controller_id")!=target[1].get("remote_controller_id"): raise RuntimeError("Remote controller identity mismatch")
        return x
    def run(self):
        while not self.stop_event.is_set():
            if self.client is None:
                try: self.connect()
                except Exception:
                    self.error="MQTT broker unavailable - check settings"
                    self.stop_event.wait(10); continue
            if not self.connected.wait(2): continue
            force=self.force.is_set()
            if force: self.force.clear(); self.sent.clear(); self.cursors.clear()
            routes={}; count=0; online=0
            try:
                targets=self.targets()
                for rid in list(self.known):
                    if rid not in targets and self.discovery:
                        for t,av in self.known[rid].items(): self.publish(av,"offline"); self.publish(t,"")
                        del self.known[rid]; self.cursors.pop(rid,None)
                for rid,target in targets.items():
                    try:
                        s=self.snapshot(target); entries=catalog(s,target[0],self.prefix,self.av)
                        known=self.known.setdefault(rid,{})
                        for t,e in entries.items():
                            if self.discovery and self.publish(t,e["config"],force=force): known[t]=e["av"]
                            self.publish(e["av"],"online" if e["ok"] else "offline",force=force)
                            if e["state"] is not None: self.publish(e["state_topic"],e["state"],force=force)
                            if e["cmd"] and e["ok"]: routes[e["cmd"]]=(rid,t)
                        if self.discovery and not s.get("scan_running"):
                            for t in list(known):
                                if t not in entries and self.publish(known[t],"offline") and self.publish(t,""): del known[t]
                        latest=int(s.get("event_latest_id",0)); since=self.cursors.get(rid)
                        self.cursors[rid]=latest
                        if since is not None and latest>since:
                            try:
                                r=self.ctl.events_since(since,0) if target[1] is None else self.remote_request(target[1],"GET",f"/api/events?since={since}&wait=0",timeout=5)
                                for ev in r.get("events",[]):
                                    if ev.get("instance_type")!=1: continue
                                    suf=f"input_{ev['bus']}_{ev['address']}_{ev['instance']}"
                                    e=entries.get(self.prefix+"/event/"+key(str(s["controller_id"])+":"+suf)+"/config")
                                    typ=ev.get("event_type","button_event")
                                    if e and e["ok"] and typ in EVENTS: self.publish(e["state_topic"],dict(event_type=typ),retain=False)
                                self.cursors[rid]=int(r.get("latest_id",latest))
                            except Exception: pass
                        count+=len(entries); online+=1
                    except Exception:
                        self.cursors.pop(rid,None)
                        for av in self.known.get(rid,{}).values(): self.publish(av,"offline")
                self.routes=routes if self.connected.is_set() else {}
                self.counts=(online,count)
                tmp=self.path.with_suffix(".tmp"); tmp.write_text(js(self.known)); os.chmod(tmp,0o600); tmp.replace(self.path)
            except Exception: self.error="MQTT discovery refresh failed"; self.routes={}
            self.stop_event.wait(1)
    def worker(self):
        while not self.stop_event.is_set():
            try: stamp,topic,payload=self.q.get(timeout=.5)
            except queue.Empty: continue
            if not self.connected.is_set() or time.monotonic()-stamp>10: continue
            r=self.routes.get(topic)
            if not r: continue
            rid,t=r
            try:
                target=self.targets()[rid]; s=self.snapshot(target)
                e=catalog(s,target[0],self.prefix,self.av).get(t)
                if not e or not e["ok"] or not self.connected.is_set() or time.monotonic()-stamp>10: continue
                path,data,timeout=request(e["route"],e["comp"],payload)
                if target[1] is None:
                    req=urllib.request.Request("http://127.0.0.1:8099"+path,data=js(data).encode(),headers={"Content-Type":"application/json"},method="POST")
                    with urllib.request.urlopen(req,timeout=timeout) as response: result=json.load(response)
                else: result=self.remote_request(target[1],"POST",path,data,timeout=timeout)
                if not result.get("ok"): raise RuntimeError("Command rejected")
            except Exception: self.log("MQTT command failed or rejected")
