"""Read-only, bounded DALI diagnostic laboratory. No persistent gear writes."""
import threading,time
from datetime import datetime,timezone

_trace=threading.local()
BANKS=tuple(range(256))
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
    if d.get("mode")=="advanced":
        import advanced
        result=advanced.execute(c,d)
        return {"controller_id":c.controller_id,**result}
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
                    values.append(v)
            report["memory"]={"bank":bank,"offset":offset,"requested":count,"last_location":last,"bytes":values,"hex":" ".join("--" if v is None else f"{v:02X}" for v in values),"decoded":False}
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
<label id="modeLabel">Testtype<select id="mode"><option value="communication">STM32-kommunikation</option><option value="basic">Grundparametre</option><option value="fade">Fade-parametre</option><option value="capabilities">DT6 / DT8 / DT1 egenskaber</option><option value="memory">Memory banks / D4i rådata</option><option value="input">DALI-2 input</option><option value="advanced">Avanceret konfiguration</option></select></label>
<label id="deviceLabel">Enhed<select id="device"></select></label>
</div><div class="fields" id="memory" hidden><label>Bank<input id="bank" type="number" min="0" max="255" value="0"></label><label>Startadresse<input id="offset" type="number" min="0" max="255" value="0"></label><label>Antal bytes<input id="count" type="number" min="1" max="16" value="16"></label></div>
<label class="check" id="volatile" hidden><input id="confirm" type="checkbox">Tillad midlertidige DTR/device-type-kommandoer. Test kun når anden DALI-commissioning er stoppet.</label>
<div id="advanced" hidden><div class="fields"><label>Handling<select id="action">
<option value="inspect">Læs egenskaber og fade</option><option value="memory">Læs og gem memory bank</option><option value="name">Navngiv armatur</option>
<option value="fade">Indstil fade</option><option value="curve">Indstil DT6 dimmekurve</option><option value="color">Indstil DT8 farve</option>
<option value="input_config">DALI-2 sensorparameter</option><option value="commission_input">Adresservér én ny DALI-2 enhed</option>
<option value="restore_preview">Backup: vis restore-plan</option><option value="restore_apply">Backup: udfør restore / udskiftning</option>
<option value="emergency_read">DT1 læs status</option><option value="emergency_test">DT1 manuel test</option><option value="reset">Reset armatur</option>
</select></label></div><div id="argFields" class="pulsar-args"></div><div hidden><textarea id="args"></textarea></div>
<p id="hint" class="muted"></p><label class="check"><input id="writeconfirm" type="checkbox">Bekræft handlingen. Anden DALI-commissioning er stoppet.</label><label class="check"><input id="testbus" type="checkbox">Isoleret testbus (påkrævet ved DALI-2 adressering og nødlystest).</label>
<p class="muted" id="warning" hidden>Restore kan gennemføre delvise ændringer. DT1-test erstatter ikke godkendt nødlysvedligehold.</p></div><div class="actions"><button id="refresh">Opdater enheder</button><button class="primary" id="run" disabled>Kør test</button><button id="export" disabled>Eksportér JSON</button></div><p id="status" class="pulsar-state" role="status">Indlæser…</p>
</section><section><h2>Resultat</h2><p id="summary" class="muted">Ingen test kørt.</p><div id="metrics" class="pulsar-metrics"></div><div class="scroll"><table><thead><tr><th>Kontrol</th><th>Status</th><th>Værdi / fejl</th></tr></thead><tbody id="results"></tbody></table></div></section>
<section id="telegramSection"><h2>Telegramlog</h2><p class="muted">TX = kodet forespørgsel til STM32. RX = svarpayload efter validering af ramme/checksum. Ingen antagelse om faktisk busmåling.</p><div class="scroll"><table><thead><tr><th>TX</th><th>RX</th><th>ms</th></tr></thead><tbody id="trace"></tbody></table></div></section>
</main><script>
"use strict";
const $=id=>document.getElementById(id);
let snapshot=null,report=null,busy=false,devices=[],controllers=[];
function action(){return $("action").value;}
function needsDevice(){return $("mode").value!=="communication"&&!( $("mode").value==="advanced"&&action()==="commission_input");}
const inputFields=[
 ["enabled","Aktiveret",0,1],["event_filter","Eventfilter (decimal eller 0xHEX)",0,16777215],
 ["event_priority","Eventprioritet",0,5],["event_scheme","Event scheme",0,4],["primary_group","Primær gruppe",0,255],["group_1","Gruppe 1",0,255],["group_2","Gruppe 2",0,255],
 ["short_timer","Short timer",0,255,1],["double_timer","Double timer",0,255,1],["repeat_timer","Repeat timer",0,255,1],["stuck_timer","Stuck timer",0,255,1],
 ["report_timer_302","Report timer",0,255,2],["deadtime_timer_302","Deadtime timer",0,255,2],
 ["hold_timer","Hold timer",0,255,3],["report_timer_303","Report timer",0,255,3],["deadtime_timer_303","Deadtime timer",0,255,3],
 ["report_timer_304","Report timer",0,255,4],["hysteresis","Hysterese",0,255,4],["deadtime_timer_304","Deadtime timer",0,255,4],["hysteresis_min","Minimum hysterese",0,255,4]];
function field(parent,id,label,kind,value,opts={}){
 const wrap=document.createElement("label");wrap.textContent=label;
 const e=document.createElement(kind==="select"?"select":"input");e.id="arg_"+id;e.dataset.arg=id;
 if(kind==="select"){for(const [v,t] of opts.choices||[])option(e,String(v),t);e.value=String(value);}
 else {e.type=kind;e.value=String(value??"");if(kind==="number"){e.min=opts.min??0;e.max=opts.max??255;e.step=1;}if(kind==="checkbox"){e.checked=!!value;wrap.className="check";}}
 e.required=kind!=="checkbox";wrap.append(e);parent.append(wrap);return e;
}
let backupList=[],backupSeq=0;
async function loadBackups(){
 const seq=++backupSeq, target=selected(), el=$("arg_filename");
 if(!target||!el||!snapshot)return;
 try{const j=target.id==="local"?await req("api/backups"):await req("api/controller/proxy",{controller_id:target.id,method:"GET",path:"/api/backups",body:{}});
 if(seq!==backupSeq||el!==$("arg_filename")||selected()?.id!==target.id)return;
 const old=el.value;el.replaceChildren();option(el,"","Vælg backup");for(const b of j.backups||[]){if(b.filename)option(el,b.filename,b.filename+" · "+(b.reason||""));}if([...el.options].some(x=>x.value===old))el.value=old;
 }catch(e){if(seq===backupSeq&&el===$("arg_filename"))status("Kunne ikke hente backups: "+e.message,"error");}
}
function advancedFields(){
 $("advanced").hidden=$("mode").value!=="advanced";
 $("writeconfirm").checked=false;$("testbus").checked=false;
 const a=action(),root=$("argFields");root.replaceChildren();backupSeq++;
 const wrap=document.createElement("div");wrap.className="fields";root.append(wrap);
 const g=devices[Number($("device").value)-1]||{};
 const add=(...x)=>field(wrap,...x);
 const numeric=(id,label,v,min,max)=>add(id,label,"number",v,{min,max});
 const select=(id,label,v,choices)=>add(id,label,"select",v,{choices});
 const text=(id,label,v)=>add(id,label,"text",v);
 $("warning").hidden=!["restore_apply","restore_preview","reset","commission_input","emergency_test"].includes(a);
 $("testbus").parentElement.hidden=!["commission_input","emergency_test"].includes(a);
 $("writeconfirm").parentElement.hidden=["name"].includes(a);
 $("hint").textContent="";
 if(a==="fade"){
   const p=select("parameter","Fade-parameter","fade_time",[["fade_time","Fade Time"],["fade_rate","Fade Rate"],["extended_fade_time","Extended Fade Time"]]);
   const v=numeric("value","Kodet værdi",g.fade_time??4,0,15);
   const update=()=>{const n=p.value;v.min=n==="fade_rate"?1:0;v.max=n==="extended_fade_time"?79:15;v.value=g[n]??(n==="fade_rate"?7:n==="fade_time"?4:0);$("hint").textContent=n==="extended_fade_time"?"Rå DALI-kode: multiplikator og basis. 0 deaktiverer.":"Kodet DALI-værdi (ikke sekunder). Efter skrivning læses parameteren tilbage.";};
   p.onchange=update;update();
 }else if(a==="curve"){select("value","Dimmekurve",g.dimming_curve??0,[[0,"Logaritmisk"],[1,"Lineær"]]);}
 else if(a==="memory"){numeric("bank","Memory bank",0,0,255);$("hint").textContent="Bank 0 indeholder identifikation. D4i-data aflæses kun på understøttede drivere.";}
 else if(a==="name"){text("name","Armaturets navn",g.name||"");$("hint").textContent="Navnet gemmes i controlleren; eksisterende MQTT-identitet bevares.";}
 else if(a==="color"){
   const cap=select("color_kind","Farvetype","kelvin",[["kelvin","Tunable White (Kelvin)"],["rgbwaf","RGB / RGBWAF"]]);
   const area=document.createElement("div");area.className="fields";root.append(area);
   const update=()=>{area.replaceChildren();if(cap.value==="kelvin"){field(area,"kelvin","Farvetemperatur (K)","number",g.color_temp_kelvin??Math.max(g.min_kelvin||1000,Math.min(3000,g.max_kelvin||20000)),{min:g.min_kelvin||1000,max:g.max_kelvin||20000});}
    else {const n=Number(g.rgbwaf_channels)||3;const channels=field(area,"channels","Antal kanaler","select",Math.max(3,Math.min(6,n)),{choices:[[3,"RGB"],[4,"RGBW"],[5,"RGBWA"],[6,"RGBWAF"]]});const levels=document.createElement("div");levels.className="fields";area.append(levels);const make=()=>{levels.replaceChildren();for(let i=0;i<Number(channels.value);i++)field(levels,"rgb_"+i,["Rød","Grøn","Blå","Hvid","Amber","Fri kanal"][i],"number",g.rgbwaf?.[i]??0,{min:0,max:254});};channels.onchange=make;make();}
    $("hint").textContent="DT8-egenskaber og grænser kontrolleres på den fysiske driver. Læs egenskaber først.";};
   cap.onchange=update;update();
 }else if(a==="input_config"){
   const rows=inputFields.filter(x=>x.length===4||x[4]===g.instance_type);
   const p=select("parameter","Sensorparameter","event_filter",rows.map(x=>[x[0],x[1]]));
   const v=text("value","Værdi",g.event_filter??84);
   const update=()=>{const row=rows.find(x=>x[0]===p.value);v.value=g[p.value]??(p.value==="event_filter"?84:0);$("hint").textContent="Tilladt råværdi "+row[2]+"–"+row[3]+". Eventfilter kan indtastes i hex.";};p.onchange=update;update();
 }else if(a.startsWith("restore")){
   select("filename","Backup","",[["","Vælg backup"]]);numeric("source_bus","Kildebus",Number($("bus").value),1,3);numeric("source_address","Kildeadresse",g.address??0,0,63);add("replacement","Overfør til erstatningsarmatur","checkbox",false);
   $("hint").textContent=a==="restore_preview"?"Læs den planlagte ændring uden at skrive til armaturet.":"Kontrollér restore-planen først. Delvise writes kan ikke rulles tilbage automatisk.";loadBackups();
 }else if(a==="emergency_test"){select("test","Nødlystest","function",[["function","Funktionstest"],["duration","Varighedstest"],["stop","Stop test"]]);$("hint").textContent="Kun isoleret testarmatur. Varighedstest kan aflade batteriet.";}
 else if(a==="commission_input"){$("hint").textContent="Adresserer én uadresseret DALI-2-enhed på den valgte bus. Ingen masseadressering.";}
 else if(a==="reset"){$("hint").textContent="Ændrer driverens konfiguration. Backup oprettes før reset.";}
 else if(a==="inspect"){$("hint").textContent="Læs og gem rapporterede egenskaber, fade og enhedstyper.";}
 else if(a==="emergency_read"){$("hint").textContent="Læs rå DT1-status og batteriniveau.";}
 if(!wrap.children.length)wrap.remove();
}
function paramsFromForm(){
 const a=action(),out={};
 for(const e of $("argFields").querySelectorAll("[data-arg]")){
   if(!e.checkValidity()){e.reportValidity();throw Error("Kontrollér "+e.closest("label").textContent);}
   const id=e.dataset.arg;
   if(e.type==="checkbox")out[id]=e.checked;
   else if(e.type==="number"||["source_bus","source_address","channels"].includes(id)||(a==="curve"&&id==="value"))out[id]=Number(e.value);
   else out[id]=e.value.trim();
 }
 if(a==="fade"&&out.parameter==="extended_fade_time"&&(out.value&15)>4)throw Error("Reserveret extended fade kode");
 if(a==="input_config"){const row=inputFields.find(x=>x[0]===out.parameter);if(!/^(?:\d+|0x[0-9a-f]+)$/i.test(out.value))throw Error("Indtast et heltal");out.value=Number(out.value);if(!row||!Number.isInteger(out.value)||out.value<row[2]||out.value>row[3])throw Error("Parameter uden for område");}
 if(a==="color"){if(out.color_kind==="rgbwaf"){out.rgbwaf=Array.from({length:out.channels},(_,i)=>out["rgb_"+i]);for(const k of Object.keys(out))if(k.startsWith("rgb_"))delete out[k];delete out.channels;}delete out.color_kind;}
 return out;
}
function status(s,state=""){ $("status").textContent=s;$("status").dataset.state=state; }
function lock(v){busy=v;for(const id of ["controller","bus","mode","device","bank","offset","count","confirm","refresh","action","args","writeconfirm","testbus"])$(id).disabled=v;for(const e of $("argFields").querySelectorAll("input,select"))e.disabled=v;$("deviceLabel").hidden=!needsDevice();$("run").disabled=v||!snapshot||(needsDevice()&&!$("device").value);$("export").disabled=v||!report;}
function clear(){report=null;$("results").replaceChildren();$("trace").replaceChildren();$("summary").textContent="Ingen test kørt.";$("metrics").replaceChildren();$("export").disabled=true;}
function option(select,value,label){const el=document.createElement("option");el.value=value;el.textContent=label;select.append(el);}
async function req(path,data){const base=location.pathname.replace(/\/(?:testlab|configuration)\/?$/,"/").replace(/[^/]*$/,"");const r=await fetch(base+path,{method:data===undefined?"GET":"POST",headers:{"Content-Type":"application/json"},body:data===undefined?undefined:JSON.stringify(data),cache:"no-store"});const j=await r.json();if(!r.ok||(j.ok===false&&!j.controller_id))throw Error(j.error||"HTTP "+r.status);return j;}
function selected(){return controllers.find(c=>c.id===$("controller").value);}
function populate(){const mode=$("mode").value,bus=Number($("bus").value);$("memory").hidden=mode!=="memory";$("volatile").hidden=!["memory","capabilities"].includes(mode);$("confirm").checked=false;$("device").replaceChildren();devices=[];option($("device"),"","Vælg enhed");
if(snapshot&&needsDevice()){const input=mode==="input"||(mode==="advanced"&&action()==="input_config");devices=(input?snapshot.input_instances:snapshot.gear)||[];devices=devices.filter(x=>x.bus===bus&&(input||!x.address_conflict));devices.forEach((g,i)=>option($("device"),String(i+1),input?"Adresse "+g.address+" / instance "+g.instance+" · "+(g.instance_type_name||"Input"):"Adresse "+g.address+" · "+(g.name||"DT "+g.device_type)));} if(mode==="advanced")advancedFields();lock(busy);}
async function load(){if(busy)return;clear();snapshot=null;lock(true);populate();status("Henter aktuelle enheder…");
try{const c=selected();if(!c)throw Error("Vælg controller");const target={registry_id:c.id,controller_id:c.remote_controller_id||c.controller_id};snapshot=c.id==="local"?await req("api/devices"):await req("api/lab/remote",{...target,operation:"snapshot"});if(snapshot.controller_id!==target.controller_id)throw Error("Controller-ID ændret; genindlæs siden");status("Controller: "+c.name+" · "+snapshot.controller_id);populate();}catch(e){snapshot=null;status(String(e));}finally{lock(false);}}
function cell(tr,value,cls){const td=document.createElement("td");td.textContent=value==null?"—":typeof value==="object"?JSON.stringify(value):String(value);if(cls)td.className=cls;tr.append(td);}
function render(r){
 $("results").replaceChildren();$("trace").replaceChildren();$("metrics").replaceChildren();
 if(!r.checks){
  for(const [k,v] of Object.entries(r)){if(k==="controller_id"||k==="ok")continue;const tr=document.createElement("tr");cell(tr,k,"pulsar-result-key");cell(tr,k==="error"?"Fejl":"Data",k==="error"?"error":"");cell(tr,typeof v==="object"?JSON.stringify(v,null,2):v,"pulsar-result-value");$("results").append(tr);}
  $("summary").textContent=r.ok===false?"Handlingen rapporterede fejl eller delvis ændring.":"Handlingsresultat";return;
 }
 for(const [k,label] of [["pass","Bestået"],["no_reply","Intet svar"],["error","Fejl"],["skipped","Sprunget over"],["unknown","Ukendt"]]){const e=document.createElement("span");e.textContent=label+": "+(r.summary?.[k]||0);$("metrics").append(e);}
 $("summary").textContent="Samlet tid: "+r.elapsed_ms+" ms";
 for(const x of r.checks||[]){const tr=document.createElement("tr");cell(tr,x.test);cell(tr,({pass:"Bestået",no_reply:"Intet svar",error:"Fejl",skipped:"Sprunget over",unknown:"Ukendt"})[x.status]||x.status,x.status);cell(tr,x.detail??x.value);$("results").append(tr);}
 for(const x of r.telegram_log||[]){const tr=document.createElement("tr");cell(tr,x.tx,"mono");cell(tr,x.error||x.response_payload,"mono");cell(tr,x.ms);$("trace").append(tr);}
}
async function run(){if(busy||!snapshot)return;clear();const c=selected(),mode=$("mode").value,g=devices[Number($("device").value)-1];const d={controller_id:snapshot.controller_id,bus:Number($("bus").value),mode,confirm_volatile:$("confirm").checked};if(needsDevice()){if(!g)return;d.address=g.address;d.uid=g.ha_uid;d.instance=g.instance;}if(mode==="advanced"){try{const params=paramsFromForm();Object.assign(d,params,{controller_id:snapshot.controller_id,bus:Number($("bus").value),mode,action:action(),address:g?.address,uid:g?.ha_uid,instance:g?.instance,confirm:$("writeconfirm").checked||action()==="name",test_bus:$("testbus").checked});if(!d.confirm){status("Bekræft handlingen først.","error");return;}if(["commission_input","emergency_test"].includes(action())&&!d.test_bus){status("Bekræft isoleret testbus.","error");return;}}catch(e){status(String(e));return;}}if(mode==="memory")Object.assign(d,{bank:Number($("bank").value),offset:Number($("offset").value),count:Number($("count").value)});if(["memory","capabilities"].includes(mode)&&!d.confirm_volatile){status("Bekræft de midlertidige buskommandoer først.");return;}lock(true);status("Test kører på "+c.name+" · DALI "+d.bus+"…");try{report=c.id==="local"?await req("api/lab/run",d):await req("api/lab/remote",{registry_id:c.id,controller_id:d.controller_id,operation:"run",test:d});if(report.controller_id!==d.controller_id)throw Error("Forkert controller i svar");render(report);status(report.ok===false?"Delvis handling eller fejl: "+(report.error||"se resultat"):mode==="advanced"?"Handling afsluttet. Se resultat og eventuel read-back.":"Test afsluttet. No reply kan betyde manglende understøttelse eller kommunikationsfejl.",report.ok===false?"error":"success");}catch(e){report=null;status(String(e),"error");}finally{$("writeconfirm").checked=false;$("testbus").checked=false;lock(false);}}
$("controller").onchange=()=>{localStorage.setItem("pulsar_active_controller",$("controller").value);load();};$("refresh").onclick=load;$("bus").onchange=()=>{clear();populate();};$("mode").onchange=()=>{clear();advancedFields();populate();};$("action").onchange=()=>{clear();advancedFields();populate();};$("device").onchange=()=>{clear();if($("mode").value==="advanced")advancedFields();lock(false);};$("run").onclick=run;
advancedFields();
$("export").onclick=()=>{if(!report)return;const u=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:"application/json"}));const a=document.createElement("a");a.href=u;a.download="pulsar-dali-test-"+Date.now()+".json";a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);};
(async()=>{try{const j=await req("api/controllers");controllers=[j.local,...j.controllers].filter(Boolean);for(const c of controllers)option($("controller"),c.id,c.name||c.id);const stored=localStorage.getItem("pulsar_active_controller");if(controllers.some(c=>c.id===stored))$("controller").value=stored;const q=new URLSearchParams(location.search);if(["1","2","3"].includes(q.get("bus")))$("bus").value=q.get("bus");await load();if(q.has("address")){const idx=devices.findIndex(x=>x.address===Number(q.get("address")));if(idx>=0){$("device").value=String(idx+1);if($("mode").value==="advanced")advancedFields();lock(false);}}}catch(e){status(String(e));lock(false);}})();
</script></body></html>'''

def page_for(configuration=False):
    from ui_layout import apply
    if configuration:
        page=PAGE.replace('<option value="communication">STM32-kommunikation</option>','')
        page=page.replace('<option value="advanced">','<option value="advanced" selected>')
        page=page.replace('<label id="modeLabel">','<label id="modeLabel" hidden>')
        page=page.replace('<h2>Vælg test</h2>','<h2>Vælg enhed og handling</h2>')
        page=page.replace('>Kør test</button>','>Udfør handling</button>')
        page=page.replace('<section id="telegramSection">','<section id="telegramSection" hidden>')
        return apply(page,"configuration")
    page=PAGE.replace('<option value="advanced">Avanceret konfiguration</option>','')
    return apply(page,"testlab")
