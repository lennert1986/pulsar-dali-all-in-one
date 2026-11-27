"""Advanced DALI operations using the existing S1/S2 transport.

Experimental. Never auto-run commissioning, reset or emergency tests.
All new operations are serialized with scans and ordinary commands.
"""
import json
import math
import time
from pathlib import Path

FADES = {"fade_time": (0x2E,0xA5,0,15), "fade_rate": (0x2F,0xA5,1,15),
         "extended_fade_time": (0x30,0xA8,0,0x4F)}
DT1 = {"battery_raw":0xF1,"duration_result":0xF3,"emergency_mode":0xFA,
       "emergency_failure":0xFC,"emergency_status":0xFD}
BANKS = (0,1,202,203,204,205,206,207)
BASIC = ("min_level","max_level","power_on_level","system_failure_level")
INPUT_FIELDS = {
    "enabled":None,"event_filter":None,"event_priority":None,"event_scheme":None,
    "primary_group":None,"group_1":None,"group_2":None,
    "short_timer":1,"double_timer":1,"repeat_timer":1,"stuck_timer":1,
    "report_timer_302":2,"deadtime_timer_302":2,
    "hold_timer":3,"report_timer_303":3,"deadtime_timer_303":3,
    "report_timer_304":4,"hysteresis":4,"deadtime_timer_304":4,"hysteresis_min":4,
}

def integer(v, lo, hi, name):
    if type(v) is not int or not lo <= v <= hi:
        raise ValueError(f"{name} must be an integer in {lo}..{hi}")
    return v

def frame(a, opcode):
    return (opcode << 8) | ((a << 1) | 1)

def query(c,b,a,op):
    return c._s1or(b,frame(a,op))

def optional(fn):
    try:
        return fn()
    except Exception as exc:
        # A missing answer is normal for optional features; other errors must
        # not be converted to a plausible numerical value.
        if getattr(exc,"code",None) == "03":
            return None
        raise

def dtr(c,b,n,v):
    c._s1on(b,(v << 8) | (0xA3,0xC3,0xC5)[n])

def ext(c,b,a,dt,op,mode="query"):
    c._s1on(b,(dt << 8)|0xC1)
    if mode=="query":
        return c._s1or(b,frame(a,op))
    return (c._s1tn if mode=="twice" else c._s1on)(b,frame(a,op))

def types(c,b,a):
    first=query(c,b,a,0x99)
    if first is None:
        return []
    if first != 255:
        return [first]
    out=[]
    for _ in range(64):
        v=query(c,b,a,0xA7)
        if v is None or v==255 or v in out:
            break
        out.append(v)
    return out

def gear(c,b,a,uid,check=True):
    with c.cache_lock:
        g=dict(c.gear.get(b,{}).get(a,{}))
    if not g or not uid or g.get("ha_uid")!=uid:
        raise ValueError("Gear missing or identity changed; reload snapshot")
    if not g.get("online") or g.get("address_conflict"):
        raise ValueError("Gear is offline or conflicted")
    if check:
        actual=c._assert_unique_address(b,a)
        known=g.get("random_address")
        if known is None or actual!=known:
            raise ValueError("Physical random address changed; scan and check identity")
    return g

def cache(c,b,a,values):
    with c.cache_lock:
        if a not in c.gear[b]:
            raise RuntimeError("Gear disappeared")
        c.gear[b][a].update(values)
    c._save_cache()

def read_fades(c,b,a):
    r={}
    f=query(c,b,a,0xA5)
    if f is not None:
        r.update(fade_time=f>>4,fade_rate=f&15)
    f=query(c,b,a,0xA8)
    if f is not None and f<=0x4F:
        r["extended_fade_time"]=f
    return r

def fade(c,b,a,name,value):
    opcode,read_op,lo,hi=FADES[name]
    integer(value,lo,hi,name)
    if name=="extended_fade_time" and (value&15)>4:
        raise ValueError("Reserved extended fade multiplier")
    if name=="extended_fade_time" and query(c,b,a,read_op) is None:
        raise ValueError("Extended fade time unsupported")
    dtr(c,b,0,value)
    c._s1tn(b,frame(a,opcode))
    result=read_fades(c,b,a)
    if result.get(name)!=value:
        raise RuntimeError(f"Readback mismatch for {name}: {result.get(name)}")
    cache(c,b,a,result)
    return result

def memory(c,b,a,bank,start,count):
    integer(bank,0,255,"bank"); integer(start,0,255,"start"); integer(count,1,64,"count")
    if start+count>256: raise ValueError("Memory range exceeds bank")
    # Read each location explicitly; do not rely on an auto-increment after
    # a failed reply. No EEPROM or bank-lock writes.
    dtr(c,b,1,bank)
    dtr(c,b,0,0)
    end=query(c,b,a,0xC5)
    if end is None or start>end:
        return None
    data=[]
    for n in range(start,min(start+count,end+1)):
        dtr(c,b,0,n)
        value=query(c,b,a,0xC5)
        data.append(value)
    return data

def u(data,start,n):
    part=data[start:start+n]
    if len(part)!=n or any(type(v) is not int for v in part):
        return None
    value=int.from_bytes(bytes(part),"big")
    # Mask and unavailable sentinels must not become huge measurements.
    if value >= (1<<(8*n))-2:
        return None
    return value

def scaled(data,offset,n):
    if len(data)<offset+n+1 or type(data[offset]) is not int: return None
    scale=data[offset]
    scale=scale-256 if scale>=128 else scale
    raw=u(data,offset+1,n)
    if not -6<=scale<=6 or raw is None: return None
    return raw*10.0**scale

def decode_energy(data,bank):
    # Input starts at location 0; Part 252 version 1 memory layout.
    if len(data)<16 or data[3]!=1: return {}
    suffix={202:"",203:"_apparent",204:"_loadside"}[bank]
    result={}
    energy=scaled(data,4,6); power=scaled(data,11,4)
    if bank==203:
        if energy is not None: result["apparent_energy_kvah"]=energy/1000
        if power is not None: result["apparent_power_va"]=power
    else:
        if energy is not None: result["energy"+suffix+"_kwh"]=energy/1000
        if power is not None: result["power"+suffix+"_w"]=power
    return result

def decode_diagnostics(data,bank):
    if len(data)<4 or data[3]!=1: return {}
    fields=({ "gear_operation_seconds":(4,4),"gear_start_counter":(8,3),
              "gear_temperature_raw":(27,1)}
            if bank==205 else {"light_start_counter":(7,3),"light_on_seconds":(14,4),
                               "light_temperature_raw":(32,1)} if bank==206 else {})
    return {k:v for k,(i,n) in fields.items() if (v:=u(data,i,n)) is not None}

def decode_identity(m,version):
    out={}
    if len(m)>2 and type(m[2]) is int: out["last_memory_bank"]=m[2]
    gtin=u(m,3,6)
    if gtin not in (0,None):
        s=str(gtin).zfill(14)
        if len(s)==14 and sum(int(x)*(3 if i%2==0 else 1) for i,x in enumerate(s))%10==0: out["gtin"]=s
        else: out["gtin_raw"]=s
    def pair(k,i):
        if len(m)>i+1 and all(type(x) is int and x<255 for x in m[i:i+2]): out[k]=f"{m[i]}.{m[i+1]}"
    pair("driver_firmware",9)
    n=8 if type(version) is int and version>=8 else 4 if version==1 else 0
    if n and len(m)>=11+n:
        v=m[11:11+n]
        if all(type(x) is int for x in v) and any(x!=255 for x in v) and any(v): out["identification_raw"]=bytes(v).hex().upper()
    if n==8:
        pair("driver_hardware",19)
        for k,i in (("iec101",21),("iec102",22),("iec103",23)):
            if len(m)>i and type(m[i]) is int and m[i]!=255: out[k]=f"{m[i]>>2}.{m[i]&3}"
        for k,i in (("logical_control_devices",24),("logical_control_gear",25),("logical_index",26)):
            if len(m)>i and type(m[i]) is int and m[i]<255: out[k]=m[i]
    return out

def read_memory_set(c,b,a,banks):
    data={}; out={}
    for bank in banks:
        integer(bank,0,255,"bank")
        size={0:27,1:64,202:16,203:16,204:16,205:29,206:33,207:8}.get(bank,16)
        m=memory(c,b,a,bank,0,size)
        if m is None: continue
        data[str(bank)]=m
        if bank==0: out.update(decode_identity(m,c.query(b,a,"version_number")))
        if bank==1: out["luminaire_bank1"]=m
        if bank in (202,203,204,205,206):
            # Two matching reads reduce mixed multi-byte measurements.
            # Missing/unstable samples are never converted to zero.
            again=memory(c,b,a,bank,0,size)
            if again is not None:
                fn=decode_energy if bank<=204 else decode_diagnostics
                x,y=fn(m,bank),fn(again,bank)
                out.update({k:v for k,v in x.items() if y.get(k)==v})
                if bank in (205,206):
                    for prefix in ("gear","light"):
                        raw=out.get(prefix+"_temperature_raw")
                        if raw is not None: out[prefix+"_temperature_c"]=raw-60
            out["sampled_bank_"+str(bank)]=time.time()
    out.update(memory_banks=data,data_read_at=time.time())
    return out

def color_word(c,b,a,selector,allow_zero=False):
    dtr(c,b,0,selector)
    hi=ext(c,b,a,8,0xFA)
    if hi is None: return None
    lo=query(c,b,a,0x98)
    if lo is None: return None
    v=hi*256+lo
    return v if (0 if allow_zero else 1)<=v<65535 else None

def color_byte(c,b,a,selector):
    dtr(c,b,0,selector)
    v=ext(c,b,a,8,0xFA)
    return v if v is not None and v<255 else None

def color_state(c,b,a):
    feature=ext(c,b,a,8,0xF9)
    if feature is None: return {}
    status=ext(c,b,a,8,0xF8)
    out={"colour_features":feature,"colour_status":status}
    channels=(feature>>5)&7
    out["rgbwaf_channels"]=channels if channels<=6 else 0
    if feature&1 and status is not None and status&0x10:
        x=color_word(c,b,a,0,True); y=color_word(c,b,a,1,True)
        if x is not None and y is not None and x+y<=65536: out["xy"]=[x/65536,y/65536]
    if feature&2:
        cool=color_word(c,b,a,0x80); warm=color_word(c,b,a,0x82)
        if cool and warm and cool<=warm:
            out.update(min_kelvin=round(1e6/warm),max_kelvin=round(1e6/cool))
        if status is not None and status&0x20:
            actual=color_word(c,b,a,2)
            if actual: out["color_temp_kelvin"]=round(1e6/actual)
    if status is not None and status&0x80 and 3<=channels<=6:
        vals=[color_byte(c,b,a,9+i) for i in range(channels)]
        if all(v is not None for v in vals): out["rgbwaf"]=vals
    return out

def color_set(c,b,a,data):
    caps=color_state(c,b,a)
    if not caps: raise ValueError("No DT8 colour features")
    if "xy" in data:
        if not caps.get("colour_features",0)&1: raise ValueError("XY not supported")
        xy=data["xy"]
        if not isinstance(xy,list) or len(xy)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=65534/65536 for v in xy) or sum(xy)>1:
            raise ValueError("Invalid CIE XY coordinates")
        for op,value in zip((0xE0,0xE1),xy):
            raw=round(value*65536)
            dtr(c,b,0,raw&255);dtr(c,b,1,raw>>8)
            ext(c,b,a,8,op,"once")
    elif "kelvin" in data:
        if not (caps.get("colour_features",0)&2) or not caps.get("min_kelvin") or not caps.get("max_kelvin"):
            raise ValueError("No verified Tc range")
        k=integer(data["kelvin"],caps["min_kelvin"],caps["max_kelvin"],"kelvin")
        mirek=round(1e6/k)
        dtr(c,b,0,mirek&255); dtr(c,b,1,mirek>>8)
        ext(c,b,a,8,0xE7,"once")
    elif "rgbwaf" in data:
        v=data["rgbwaf"]
        n=caps.get("rgbwaf_channels",0)
        if not isinstance(v,list) or not 3<=n<=6 or len(v)!=n:
            raise ValueError("Provide exactly the supported RGBWAF channel count")
        for value in v: integer(value,0,254,"channel")
        for i in range(3): dtr(c,b,i,v[i])
        ext(c,b,a,8,0xEB,"once")
        if n>3:
            for i in range(3): dtr(c,b,i,v[i+3] if i+3<n else 255)
            ext(c,b,a,8,0xEC,"once")
    else:
        raise ValueError("Supply xy, kelvin or rgbwaf")
    ext(c,b,a,8,0xE2,"once")
    result=color_state(c,b,a)
    with c.cache_lock:
        for k in ("color_temp_kelvin","rgbwaf","xy"): c.gear[b][a].pop(k,None)
    cache(c,b,a,result)
    if "xy" in data and ("xy" not in result or any(abs(x-y)>2/65536 for x,y in zip(data["xy"],result["xy"]))):
        raise RuntimeError("XY readback mismatch or gamut clipping")
    return result

def emergency_read(c,b,a):
    out={k:v for k,op in DT1.items() if (v:=ext(c,b,a,1,op)) is not None}
    charge=out.get("battery_raw")
    if charge is not None and charge<255: out["battery_percent"]=round(charge*100/254,1)
    return out

def inspect(c,b,a):
    dt=types(c,b,a)
    out={"device_types":dt,**read_fades(c,b,a)}
    if 6 in dt:
        curve=ext(c,b,a,6,0xEE)
        if curve is not None: out["dimming_curve"]=curve
    if 8 in dt: out.update(color_state(c,b,a))
    if 1 in dt: out.update(emergency_read(c,b,a))
    cache(c,b,a,out)
    return out

def compare(c,b):
    try: return c._s2or(b,0,3,0xC1) is not None
    except Exception as e:
        if getattr(e,"code",None)=="04": return True
        raise

def search(c,b,value):
    for i,op in enumerate((5,6,7)):
        c._s2on(b,(value>>(16-8*i))&255,op,0xC1)

def commission_one(c,b):
    # Address-space scan: collisions are occupied, transport errors abort.
    free=[]
    for a in range(64):
        try:
            if c._dali2_query_device(b,a,0x30) is None: free.append(a)
        except Exception as e:
            if getattr(e,"code",None)!="04": raise
    if not free: raise ValueError("No free DALI-2 short address")
    c._s2on(b,0,0,0xC1)
    try:
        c._s2tn(b,0x7F,1,0xC1) # Initialise only unaddressed control devices.
        c._s2tn(b,0,2,0xC1)
        time.sleep(0.2)
        search(c,b,0xFFFFFF)
        if not compare(c,b): return {"programmed":False,"reason":"No unaddressed device"}
        lo,hi=0,0xFFFFFF
        while lo<hi:
            mid=(lo+hi)//2
            search(c,b,mid)
            if compare(c,b): hi=mid
            else: lo=mid+1
        search(c,b,lo)
        # Recheck address availability before write.
        a=free[0]
        if c._dali2_query_device(b,a,0x30) is not None:
            raise RuntimeError("Target address became occupied")
        c._s2on(b,a,8,0xC1)
        if c._s2or(b,a,9,0xC1)!=255:
            raise RuntimeError("Programming not verified; rescan before repeating")
        c._s2on(b,0,4,0xC1)
    finally:
        c._s2on(b,0,0,0xC1)
    details=c._read_control_device_details(b,a)
    with c.cache_lock: c.control_devices[b][a]=details
    c._save_cache()
    return {"programmed":True,"address":a,"random_address":lo}

def input_action(c,b,a,d):
    inst=integer(d.get("instance"),0,31,"instance")
    with c.cache_lock:
        device=c.control_devices.get(b,{}).get(a,{})
        info=next((x for x in device.get("instances",[]) if x.get("instance")==inst),None)
    if not device.get("online") or info is None:
        raise ValueError("Scan the input device first")
    if c._dali2_query_device(b,a,0x30) is None:
        raise ValueError("Input device no longer responds")
    if d["action"]=="input_config":
        param=d.get("parameter")
        if param not in INPUT_FIELDS: raise ValueError("Unsupported input parameter")
        t=INPUT_FIELDS[param]
        if t is not None and info.get("instance_type")!=t:
            raise ValueError("Parameter does not match instance type")
        value=integer(d.get("value"),0,0xFFFFFF if param=="event_filter" else 255,"value")
        if param=="enabled": integer(value,0,1,"enabled")
        if param=="event_filter" and any(c._dali2_query_instance(b,a,inst,op) is None for op in (0x90,0x91,0x92)): raise ValueError("Event filter not fully readable")
        return c.set_input_config(b,a,inst,param,value)
    if d["action"]=="feedback":
        addr=c._control_device_address(a); feature=0x20|inst
        capability=c._s2or(b,0x2F,feature,addr)
        if not capability: raise ValueError("No feedback capability reported")
        enabled=integer(d.get("value"),0,1,"value")
        if enabled: c._s2on(b,0x10,feature,addr)
        else: c._s2tn(b,0x11,feature,addr)
        return {"feedback_capability":capability,"feedback_active":c._s2or(b,0x2E,feature,addr)}
    return {"input_value":c._read_input_value(b,a,inst,info.get("resolution")),"instance_type":info.get("instance_type")}

def restore_plan(c,b,a,g,d):
    filename=d.get("filename","")
    if not isinstance(filename,str) or not filename.startswith("dali-") or not filename.endswith(".json") or Path(filename).name!=filename:
        raise ValueError("Select an existing backup filename")
    backup=json.loads((Path("/data/backups")/filename).read_text())
    if backup.get("controller_id")!=c.controller_id: raise ValueError("Backup belongs to another controller")
    src_bus=integer(d.get("source_bus",b),1,3,"source_bus")
    src_a=integer(d.get("source_address",a),0,63,"source_address")
    old=next((x for x in backup["gear"] if x.get("bus")==src_bus and x.get("address")==src_a),None)
    if old is None or old.get("address_conflict"): raise ValueError("No valid backup gear")
    replacement=d.get("replacement") is True
    if not replacement and (old.get("ha_uid")!=g.get("ha_uid") or old.get("random_address")!=g.get("random_address")):
        raise ValueError("Backup identity mismatch")
    if old.get("device_type")!=g.get("device_type") or g.get("device_type") in (None,1,255): raise ValueError("Device type differs or requires specialized restore")
    plan={k:old[k] for k in BASIC if type(old.get(k)) is int}
    plan.update({k:old[k] for k in FADES if type(old.get(k)) is int})
    groups=old.get("groups") if old.get("groups_0_7") is not None and old.get("groups_8_15") is not None else None
    scenes={str(n):v for n,v in old.get("scenes",{}).items() if type(v) is int and 0<=v<=255 and str(n).isdigit() and 0<=int(n)<=15}
    if d["action"]=="restore_preview":
        return {"parameters":plan,"groups":groups,"scenes":scenes,"replacement":replacement,"source":f"{src_bus}/{src_a}","target":f"{b}/{a}"}
    if d.get("confirm") is not True: raise ValueError("Explicit restore confirmation required")
    c.create_backup([b],"before-advanced-restore")
    applied=[]
    try:
        # Widen maximum before changing minimum; physical minimum and gear
        # limits may reject values. Report partial writes, never claim rollback.
        order=["max_level","min_level","power_on_level","system_failure_level"]
        # When reducing max below the current minimum, lower min first.
        if "max_level" in plan and "min_level" in plan:
            current_min=query(c,b,a,0xA2)
            if current_min is None: raise RuntimeError("Cannot verify current minimum level")
            if plan["min_level"]>plan["max_level"]: raise ValueError("Invalid backup min/max range")
            if plan["max_level"]<current_min: order[:2]=["min_level","max_level"]
        for k in order:
            if k in plan:
                r=c.set_config(b,a,k,plan[k])
                if r.get("readback")!=plan[k]: raise RuntimeError("Readback mismatch "+k)
                applied.append(k)
        for k in FADES:
            if k in plan:
                fade(c,b,a,k,plan[k]); applied.append(k)
        if isinstance(groups,list):
            c.set_groups(b,a,groups)
            low=query(c,b,a,0xC0);high=query(c,b,a,0xC1)
            if low is None or high is None: raise RuntimeError("Group readback missing")
            actual=[i for i in range(16) if ((low|(high<<8))>>i)&1]
            if sorted(set(groups))!=actual: raise RuntimeError("Group readback mismatch")
            applied.append("groups")
        for n,v in scenes.items():
            c.set_scene_level(b,a,int(n),None if v==255 else v)
            actual=query(c,b,a,0xB0+int(n))
            if actual!=v: raise RuntimeError("Scene readback mismatch "+n)
            applied.append("scene "+n)
    except Exception as exc:
        return {"ok":False,"applied":applied,"error":str(exc)}
    return {"applied":applied,"replacement":replacement,"note":"Target short address and HA UID retained"}

def execute(c,d):
    if not isinstance(d,dict): raise ValueError("Expected object")
    if d.get("controller_id")!=c.controller_id: raise ValueError("Controller identity mismatch")
    if not c.settings.local_dali_enabled: raise ValueError("Local DALI disabled")
    b=integer(d.get("bus"),1,3,"bus")
    action=d.get("action")
    if action not in ("inspect","memory","name","basic_config","fade","curve","color","light","reset","emergency_read","emergency_test","commission_input","input_config","input_read","feedback","restore_preview","restore_apply"):
        raise ValueError("Unknown advanced operation")
    if action in ("basic_config","fade","curve","color","light","reset","emergency_test","commission_input","input_config","restore_apply") and d.get("confirm") is not True: raise ValueError("Explicit confirmation required")
    if action in ("commission_input","emergency_test") and d.get("test_bus") is not True: raise ValueError("Confirm isolated test bus")
    if action=="feedback": raise ValueError("Feedback not enabled")
    # Serialize multi-frame operations with every normal high-level command.
    with c.operation_lock:
        if c.scan_running: raise ValueError("Scan in progress")
        if action=="commission_input":
            if d.get("confirm") is not True: raise ValueError("Explicit commissioning confirmation required")
            c.create_backup([b],"before-input-commission")
            return {"ok":True,**commission_one(c,b)}
        a=integer(d.get("address"),0,63,"address")
        if action in ("input_config","input_read","feedback"):
            return {"ok":True,**input_action(c,b,a,d)}
        g=gear(c,b,a,d.get("uid"))
        if action=="inspect": r=inspect(c,b,a)
        elif action=="memory":
            bank=integer(d.get("bank"),0,255,"bank")
            if bank>=202 and g.get("last_memory_bank",0)<bank: raise ValueError("Read bank 0 first; bank not advertised")
            # Invalidate old sample before requesting fresh data.
            keys={202:("energy_kwh","power_w"),203:("apparent_energy_kvah","apparent_power_va"),
                  204:("energy_loadside_kwh","power_loadside_w"),
                  205:("gear_operation_seconds","gear_start_counter","gear_temperature_raw","gear_temperature_c"),
                  206:("light_start_counter","light_on_seconds","light_temperature_raw","light_temperature_c")}.get(bank,())
            with c.cache_lock:
                item=c.gear[b][a]
                for k in keys: item.pop(k,None)
            r=read_memory_set(c,b,a,[bank])
            # Merge bank cache, without turning missing data into zero.
            with c.cache_lock:
                prev=dict(c.gear[b][a].get("memory_banks",{}))
            prev.pop(str(bank),None); prev.update(r["memory_banks"]); r["memory_banks"]=prev
            cache(c,b,a,r)
        elif action=="name":
            name=d.get("name")
            if not isinstance(name,str) or not name.strip() or len(name)>80 or any(ord(x)<32 for x in name):
                raise ValueError("Name must contain 1..80 printable characters")
            cache(c,b,a,{"name":name.strip()}); r={"name":name.strip()}
        elif action=="basic_config":
            parameter=d.get("parameter")
            if parameter not in BASIC: raise ValueError("Unsupported basic parameter")
            value=integer(d.get("value"),0,255 if parameter in ("power_on_level","system_failure_level") else 254,"value")
            r=c.set_config(b,a,parameter,value)
            if r.get("readback")!=value: raise RuntimeError("Basic parameter readback mismatch")
        elif action=="fade":
            if d.get("parameter") not in FADES: raise ValueError("Unsupported fade parameter")
            r=fade(c,b,a,d["parameter"],d.get("value"))
        elif action=="curve":
            if 6 not in types(c,b,a): raise ValueError("DT6 required")
            value=integer(d.get("value"),0,1,"curve")
            dtr(c,b,0,value); ext(c,b,a,6,0xE3,"twice")
            actual=ext(c,b,a,6,0xEE)
            if actual!=value: raise RuntimeError("Curve readback mismatch")
            r={"dimming_curve":actual}; cache(c,b,a,r)
        elif action in ("color","light"):
            if 8 not in types(c,b,a): raise ValueError("DT8 required")
            if action=="color": r=color_set(c,b,a,d)
            else:
                state=d.get("state")
                if state not in ("ON","OFF"): raise ValueError("Invalid light state")
                level=d.get("level")
                if level is not None: integer(level,0,254,"brightness")
                if state=="OFF": r=c.set_level(b,a,0)
                else:
                    r=color_set(c,b,a,d) if "kelvin" in d or "rgbwaf" in d or "xy" in d else {}
                    if level is not None or not g.get("actual_level"):
                        r.update(c.set_level(b,a,max(1,level if level is not None else 254)))
        elif action=="reset":
            if d.get("confirm") is not True: raise ValueError("Explicit factory reset confirmation required")
            # Refuse reset of emergency gear, including multi-type gear.
            dt=types(c,b,a)
            if not dt or 1 in dt or g.get("device_type")==255: raise ValueError("Reset not allowed for emergency or ambiguous multi-type gear")
            c.create_backup([b],"before-gear-reset")
            c._s1tn(b,frame(a,0x20))
            r={"note":"Reset sent; scan and verify all settings"}
        elif action in ("emergency_read","emergency_test"):
            if 1 not in types(c,b,a): raise ValueError("DT1 required")
            if action=="emergency_test":
                # Never scheduled automatically. Operator must verify site
                # safety and follow the emergency lighting maintenance plan.
                test=d.get("test")
                if test not in ("function","duration","stop") or d.get("confirm") is not True:
                    raise ValueError("Select test and explicitly confirm safe conditions")
                ext(c,b,a,1,{"function":0xE3,"duration":0xE4,"stop":0xE5}[test],"twice")
            r=emergency_read(c,b,a); cache(c,b,a,r)
            if action=="emergency_test":
                from maintenance import audit
                audit({"controller_id":c.controller_id,"bus":b,"address":a,"uid":g.get("ha_uid"),"test":test,"status":"command_sent_not_test_passed","readback":r})
        else: r=restore_plan(c,b,a,g,d)
        return {"ok":True,**r}

# Keep the old scan's identity and metadata only when the physical random
# address is unchanged. Read extended parameters on demand, not on all 64
# addresses: avoids turning ordinary scans into hour-long scans.
PRESERVE=("name","device_types","fade_time","fade_rate","extended_fade_time","dimming_curve",
          "colour_features","colour_status","rgbwaf_channels","min_kelvin","max_kelvin",
          "color_temp_kelvin","rgbwaf","xy","gtin","identification_raw","memory_banks",
          "luminaire_bank1","data_read_at","battery_raw","battery_percent","duration_result",
          "emergency_mode","emergency_failure","emergency_status","energy_kwh","power_w",
          "energy_apparent_kwh","power_apparent_w","energy_loadside_kwh","power_loadside_w",
          "gear_operation_seconds","gear_start_counter","gear_temperature_raw","light_start_counter",
          "light_on_seconds","light_temperature_raw")

PRESERVE += ("identity_read_at","capabilities_read_at","color_read_at","last_memory_bank","driver_firmware","driver_hardware","iec101","iec102","iec103","logical_control_devices","logical_control_gear","logical_index","gtin_raw","apparent_energy_kvah","apparent_power_va","gear_temperature_c","light_temperature_c")+tuple("sampled_bank_"+str(n) for n in range(202,208))

def install(cls):
    old_read=cls._read_gear_details
    def read(self,b,a):
        with self.cache_lock: prev=dict(self.gear[b].get(a,{}))
        item=old_read(self,b,a)
        if item.get("random_address") is not None and item.get("random_address")==prev.get("random_address") and not item.get("address_conflict"):
            for k in PRESERVE:
                if k in prev: item[k]=prev[k]
        if not item.get("address_conflict"):
            try: item.update(read_fades(self,b,a))
            except Exception: pass
        return item
    cls._read_gear_details=read
    old_config=cls.set_config
    def config(self,b,a,parameter,value):
        if parameter not in FADES: return old_config(self,b,a,parameter,value)
        with self.operation_lock:
            if not self.settings.local_dali_enabled or self.scan_running: raise ValueError("Unavailable")
            with self.cache_lock: uid=self.gear.get(b,{}).get(a,{}).get("ha_uid")
            gear(self,b,a,uid)
            r=fade(self,b,a,parameter,value)
            return {"ok":True,"readback":r[parameter]}
    cls.set_config=config
