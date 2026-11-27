"""Read-only, bounded DALI diagnostic laboratory. No persistent gear writes."""
import threading,time
from datetime import datetime,timezone

_trace=threading.local()
BANKS=(0,1,202,203,204,205,206,207)
MODES=("communication","basic","fade","capabilities","memory","input")
BASIC=("status","device_type","version_number","actual_level","min_level","max_level","physical_min","power_on_level","system_failure_level","groups_0_7","groups_8_15")

def install(transport,encoder):
    original=transport.transact
    def traced(self,command,sequence,data="",blink=True):
        trace=getattr(_trace,"items",None)
        if trace is None: return original(self,command,sequence,data,blink=blink)
        if time.monotonic()>_trace.deadline: raise TimeoutError("Test time budget exhausted")
        if len(trace)>=96: raise RuntimeError("Test telegram limit exceeded")
        start=time.monotonic()
        row={"bus":self.bus_number,"command":command,"sequence":sequence,
             "tx":encoder(command,sequence,data).decode("ascii").rstrip("\n"),"response_payload":None}
        trace.append(row)
        try:
            row["response_payload"]=original(self,command,sequence,data,blink=blink)
            return row["response_payload"]
        except Exception as exc:
            row["error"]=str(exc)
            raise
        finally:
            row["ms"]=round((time.monotonic()-start)*1000,1)
    transport.transact=traced

def intfield(value,low,high,name):
    if type(value) is not int or not low<=value<=high:
        raise ValueError(f"{name}: expected integer {low}..{high}")
    return value

def run(c,d):
    if not isinstance(d,dict): raise ValueError("Invalid request")
    if d.get("controller_id")!=c.controller_id: raise ValueError("Controller identity changed; reload")
    if not c.settings.local_dali_enabled: raise ValueError("Local DALI disabled")
    mode=d.get("mode")
    if mode not in MODES: raise ValueError("Unknown test")
    bus=intfield(d.get("bus"),1,3,"bus")
    address=None if mode=="communication" else intfield(d.get("address"),0,63,"address")
    if mode in ("capabilities","memory") and d.get("confirm_volatile") is not True:
        raise ValueError("Confirm temporary DTR / device-type commands")
    if mode=="memory":
        bank=intfield(d.get("bank"),0,255,"bank")
        if bank not in BANKS: raise ValueError("Select supported bank")
        offset=intfield(d.get("offset"),0,255,"offset")
        count=intfield(d.get("count"),1,16,"count")
        if offset+count>256: raise ValueError("Memory range exceeds bank")
    if mode=="input": instance=intfield(d.get("instance"),0,31,"instance")
    # Do not wait behind commissioning/scan. Never send commands to an
    # address selected on another controller or an out-of-date cached UID.
    if not c.operation_lock.acquire(blocking=False): raise RuntimeError("DALI operation busy; retry after completion")
    start=time.monotonic()
    report={"ok":True,"controller_id":c.controller_id,"bus":bus,"address":address,
            "mode":mode,"created_utc":datetime.now(timezone.utc).isoformat(),
            "checks":[],"telegram_log":[],"persistent_writes":False}
    rows=report["checks"]
    def record(label,fn,optional=False):
        if time.monotonic()>_trace.deadline:
            rows.append({"test":label,"status":"skipped","detail":"Time budget exhausted"}); return None
        try:
            value=fn()
            rows.append({"test":label,"status":"no_reply" if value is None else "pass","value":value,
                         "optional":optional})
            return value
        except Exception as exc:
            rows.append({"test":label,"status":"error","detail":str(exc),"optional":optional})
            return None
    def q(op):
        return c._s1or(bus,(op<<8)|((address<<1)|1))
    def ext(dt,op):
        c._s1on(bus,(dt<<8)|0xC1)
        return q(op)
    def dtr(n,v): c._s1on(bus,(v<<8)|{0:0xA3,1:0xC3}[n])
    def identity():
        with c.cache_lock: gear=dict(c.gear.get(bus,{}).get(address,{}))
        if not gear or gear.get("ha_uid")!=d.get("uid") or gear.get("address_conflict"):
            raise ValueError("Missing or conflicted gear / UID mismatch; rescan")
        actual=c._assert_unique_address(bus,address)
        if gear.get("random_address") is None or actual!=gear["random_address"]:
            raise ValueError("Physical random address changed; rescan")
        return actual
    try:
        if c.scan_running: raise RuntimeError("Scan running")
        if not getattr(c.transports.get(bus),"ready",False): raise RuntimeError("UART not ready")
        _trace.items=report["telegram_log"]; _trace.deadline=start+25
        fw=record("STM32 GVER",lambda:c.gver(bus))
        if fw is None: return report
        if mode=="communication": return report
        if mode=="input":
            with c.cache_lock:
                dev=c.control_devices.get(bus,{}).get(address,{})
                if not any(x.get("instance")==instance for x in dev.get("instances",[])):
                    raise ValueError("Input instance missing; rescan")
            if record("Control device status",lambda:c._dali2_query_device(bus,address,0x30)) is None: return report
            for label,op in (("Instance type",0x80),("Resolution",0x81),("Instance status",0x83),("Event priority",0x84),("Enabled",0x86),("Event scheme",0x8B),("Event filter byte 0",0x90),("Event filter byte 1",0x91),("Event filter byte 2",0x92)):
                record(label,lambda op=op:c._dali2_query_instance(bus,address,instance,op),True)
            return report
        if record("Physical identity (random address)",identity) is None: return report
        if mode=="basic":
            for field in BASIC: record(field,lambda field=field:c.query(bus,address,field),field!="status")
            return report
        if mode=="fade":
            value=record("Fade Time / Fade Rate (raw)",lambda:q(0xA5))
            if value is not None:
                rows.append({"test":"Fade codes","status":"pass","value":{"fade_time":value>>4,"fade_rate":value&15}})
            record("Extended Fade Time (raw)",lambda:q(0xA8),True)
            return report
        if mode=="capabilities":
            dt=record("Device type",lambda:q(0x99))
            types=[] if dt is None or dt==255 else [dt]
            if dt==255:
                for _ in range(16):
                    v=record("Next device type",lambda:q(0xA7),True)
                    if v is None or v==255 or v in types: break
                    types.append(v)
            rows.append({"test":"Reported device types","status":"pass" if types else "unknown","value":types})
            if 6 in types: record("DT6 dimming curve (raw)",lambda:ext(6,0xEE),True)
            if 8 in types:
                f=record("DT8 colour features",lambda:ext(8,0xF9),True)
                if f is not None:
                    rows.append({"test":"DT8 capabilities","status":"pass","value":{"xy":bool(f&1),"tunable_white":bool(f&2),"primaries":(f>>2)&7,"rgbwaf_channels":(f>>5)&7}})
                record("DT8 colour status",lambda:ext(8,0xF8),True)
            if 1 in types:
                v=record("DT1 battery charge (raw)",lambda:ext(1,0xF1),True)
                if v is not None and v<255: rows.append({"test":"DT1 battery estimate (%)","status":"pass","value":round(v*100/254,1)})
                for label,op in (("DT1 emergency mode",0xFA),("DT1 failure status",0xFC),("DT1 emergency status",0xFD)):
                    record(label,lambda op=op:ext(1,op),True)
            return report
        if mode=="memory":
            # DTR writes are transient and affect the bus. No STORE, ENABLE
            # WRITE MEMORY, RESET, addressing or emergency-test commands.
            def byte(n):
                dtr(1,bank); dtr(0,n)
                return q(0xC5)
            last=record("Last accessible location",lambda:byte(0),True)
            values=[]
            if last is not None:
                for i in range(offset,min(last+1,offset+count)):
                    v=record(f"Bank {bank} byte {i}",lambda i=i:byte(i),True)
                    if v is None: break
                    values.append(v)
            report["memory"]={"bank":bank,"offset":offset,"requested":count,"last_location":last,"bytes":values,"hex":" ".join(f"{v:02X}" for v in values),"decoded":False}
            return report
        return report
    finally:
        _trace.items=None
        report["elapsed_ms"]=round((time.monotonic()-start)*1000,1)
        report["summary"]={s:sum(r["status"]==s for r in rows) for s in ("pass","no_reply","error","skipped","unknown")}
        c.operation_lock.release()

PAGE=r'''<!doctype html><html lang="da"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DALI Test Lab</title>
<style>
:root{color-scheme:light dark;--accent:#039be5;--border:rgba(127,127,127,.35);font-family:Roboto,system-ui,sans-serif}
body{margin:0;background:var(--primary-background-color,Canvas);color:var(--primary-text-color,CanvasText)}main{max-width:1180px;margin:auto;padding:20px}nav{display:flex;flex-wrap:wrap;gap:8px}nav a,button,select,input{font:inherit;border:1px solid var(--border);border-radius:8px;padding:9px;color:inherit;background:var(--card-background-color,Canvas)}nav a{text-decoration:none}button{cursor:pointer}button:disabled,select:disabled,input:disabled{opacity:.5;cursor:default}button.primary{background:var(--accent);color:white}section{border:1px solid var(--border);border-radius:14px;padding:16px;margin-top:16px}h1,h2{margin:0 0 12px}.muted{opacity:.75}.fields{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}label{display:flex;flex-direction:column;gap:5px}.actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}.check{flex-direction:row;align-items:center;margin-top:14px}table{width:100%;border-collapse:collapse;font-size:.9rem}th,td{text-align:left;padding:9px;border-bottom:1px solid var(--border);overflow-wrap:anywhere;vertical-align:top}.scroll{overflow:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:.82rem}.pass{color:#16803c}.error{color:#d34b45}.no_reply,.skipped,.unknown{color:#b58900}#status{white-space:pre-wrap} [hidden]{display:none!important}
</style></head><body><main>
<h1>DALI Test Lab</h1><p class="muted">Diagnostik og kompatibilitetstest · ingen permanente DALI-ændringer</p>
<nav><a href="./">Oversigt</a><a href="commissioning">Commissioning</a><a href="controllers">Controllers</a><a href="remote">Remote</a><a href="diagnostics">Diagnostik</a><a href="testlab">Test Lab</a></nav>
<section><h2>Vælg test</h2><div class="fields">
<label>Controller<select id="controller"></select></label>
<label>DALI-bus<select id="bus"><option value="1">DALI 1</option><option value="2">DALI 2</option><option value="3">DALI 3</option></select></label>
<label>Testtype<select id="mode"><option value="communication">STM32-kommunikation</option><option value="basic">Grundparametre</option><option value="fade">Fade-parametre</option><option value="capabilities">DT6 / DT8 / DT1 egenskaber</option><option value="memory">Memory banks / D4i rådata</option><option value="input">DALI-2 input</option></select></label>
<label>Enhed<select id="device"></select></label>
</div><div class="fields" id="memory" hidden><label>Bank<select id="bank"><option>0</option><option>1</option><option>202</option><option>203</option><option>204</option><option>205</option><option>206</option><option>207</option></select></label><label>Startadresse<input id="offset" type="number" min="0" max="255" value="0"></label><label>Antal bytes<input id="count" type="number" min="1" max="16" value="16"></label></div>
<label class="check" id="volatile" hidden><input id="confirm" type="checkbox">Tillad midlertidige DTR/device-type-kommandoer. Test kun når anden DALI-commissioning er stoppet.</label>
<div class="actions"><button id="refresh">Opdater enheder</button><button class="primary" id="run" disabled>Kør test</button><button id="export" disabled>Eksportér JSON</button></div><p id="status" role="status">Indlæser…</p>
</section><section><h2>Resultat</h2><p id="summary" class="muted">Ingen test kørt.</p><div class="scroll"><table><thead><tr><th>Kontrol</th><th>Status</th><th>Værdi / fejl</th></tr></thead><tbody id="results"></tbody></table></div></section>
<section><h2>Telegramlog</h2><p class="muted">TX = kodet forespørgsel til STM32. RX = svarpayload efter validering af ramme/checksum. Ingen antagelse om faktisk busmåling.</p><div class="scroll"><table><thead><tr><th>TX</th><th>RX</th><th>ms</th></tr></thead><tbody id="trace"></tbody></table></div></section>
</main><script>
"use strict";
const $=id=>document.getElementById(id);
let snapshot=null,report=null,busy=false,devices=[],controllers=[];
function status(s){$("status").textContent=s;}
function lock(v){busy=v;for(const id of ["controller","bus","mode","device","bank","offset","count","confirm","refresh"])$(id).disabled=v;$("run").disabled=v||!snapshot||($("mode").value!=="communication"&&!$("device").value);$("export").disabled=v||!report;}
function clear(){report=null;$("results").replaceChildren();$("trace").replaceChildren();$("summary").textContent="Ingen test kørt.";$("export").disabled=true;}
function option(select,value,label){const el=document.createElement("option");el.value=value;el.textContent=label;select.append(el);}
async function req(path,data){const r=await fetch(path,{method:data===undefined?"GET":"POST",headers:{"Content-Type":"application/json"},body:data===undefined?undefined:JSON.stringify(data),cache:"no-store"});const j=await r.json();if(!r.ok||j.ok===false)throw Error(j.error||"HTTP "+r.status);return j;}
function selected(){return controllers.find(c=>c.id===$("controller").value);}
function populate(){const mode=$("mode").value,bus=Number($("bus").value);$("memory").hidden=mode!=="memory";$("volatile").hidden=!["memory","capabilities"].includes(mode);$("confirm").checked=false;$("device").replaceChildren();devices=[];option($("device"),"","Vælg enhed");
if(snapshot&&mode!=="communication"){devices=(mode==="input"?snapshot.input_instances:snapshot.gear)||[];devices=devices.filter(x=>x.bus===bus&&(mode==="input"||!x.address_conflict));devices.forEach((g,i)=>option($("device"),String(i+1),mode==="input"?"Adresse "+g.address+" / instance "+g.instance+" · "+(g.instance_type_name||"Input"):"Adresse "+g.address+" · "+(g.name||"DT "+g.device_type)));} lock(busy);}
async function load(){if(busy)return;clear();snapshot=null;lock(true);populate();status("Henter aktuelle enheder…");
try{const c=selected();if(!c)throw Error("Vælg controller");const target={registry_id:c.id,controller_id:c.remote_controller_id||c.controller_id};snapshot=c.id==="local"?await req("api/devices"):await req("api/lab/remote",{...target,operation:"snapshot"});if(snapshot.controller_id!==target.controller_id)throw Error("Controller-ID ændret; genindlæs siden");status("Controller: "+c.name+" · "+snapshot.controller_id);populate();}catch(e){snapshot=null;status(String(e));}finally{lock(false);}}
function cell(tr,value,cls){const td=document.createElement("td");td.textContent=value==null?"—":typeof value==="object"?JSON.stringify(value):String(value);if(cls)td.className=cls;tr.append(td);}
function render(r){$("results").replaceChildren();$("trace").replaceChildren();for(const x of r.checks||[]){const tr=document.createElement("tr");cell(tr,x.test);cell(tr,x.status,x.status);cell(tr,x.detail||x.value);$("results").append(tr);}for(const x of r.telegram_log||[]){const tr=document.createElement("tr");cell(tr,x.tx);cell(tr,x.error||x.response_payload);cell(tr,x.ms);$("trace").append(tr);}$("summary").textContent=JSON.stringify(r.summary)+" · "+r.elapsed_ms+" ms";}
async function run(){if(busy||!snapshot)return;clear();const c=selected(),mode=$("mode").value,g=devices[Number($("device").value)-1];const d={controller_id:snapshot.controller_id,bus:Number($("bus").value),mode,confirm_volatile:$("confirm").checked};if(mode!=="communication"){if(!g)return;d.address=g.address;d.uid=g.ha_uid;d.instance=g.instance;}if(mode==="memory")Object.assign(d,{bank:Number($("bank").value),offset:Number($("offset").value),count:Number($("count").value)});if(["memory","capabilities"].includes(mode)&&!d.confirm_volatile){status("Bekræft de midlertidige buskommandoer først.");return;}lock(true);status("Test kører på "+c.name+" · DALI "+d.bus+"…");try{report=c.id==="local"?await req("api/lab/run",d):await req("api/lab/remote",{registry_id:c.id,controller_id:d.controller_id,operation:"run",test:d});if(report.controller_id!==d.controller_id)throw Error("Forkert controller i svar");render(report);status("Test afsluttet. No reply kan betyde manglende understøttelse eller kommunikationsfejl.");}catch(e){report=null;status(String(e));}finally{lock(false);}}
$("controller").onchange=load;$("refresh").onclick=load;$("bus").onchange=()=>{clear();populate();};$("mode").onchange=()=>{clear();populate();};$("device").onchange=()=>{clear();lock(false);};$("run").onclick=run;
$("export").onclick=()=>{if(!report)return;const u=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:"application/json"}));const a=document.createElement("a");a.href=u;a.download="pulsar-dali-test-"+Date.now()+".json";a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);};
(async()=>{try{const j=await req("api/controllers");controllers=[j.local,...j.controllers].filter(Boolean);for(const c of controllers)option($("controller"),c.id,c.name||c.id);await load();}catch(e){status(String(e));lock(false);}})();
</script></body></html>'''
