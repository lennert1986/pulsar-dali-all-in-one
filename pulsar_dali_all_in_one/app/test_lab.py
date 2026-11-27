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
<div id="advanced" hidden><div id="deviceOverview" hidden></div><div id="directSettings" hidden></div><div id="deviceOptions" class="device-options" hidden></div><details id="busTools" hidden><summary>Busværktøjer (ingen valgt enhed)</summary><button type="button" id="commissionInput">Adresservér én ny DALI-2-enhed</button><p class="muted">Kun på isoleret testbus.</p></details><div class="fields"><label id="actionLabel">Handling<select id="action">
<option value="inspect">Læs egenskaber og fade</option><option value="basic_config">Grundparametre</option><option value="input_read">Læs sensorstatus</option><option value="memory">Læs og gem memory bank</option><option value="name">Navngiv armatur</option>
<option value="fade">Indstil fade</option><option value="curve">Indstil DT6 dimmekurve</option><option value="color">Indstil DT8 farve</option>
<option value="input_config">DALI-2 sensorparameter</option><option value="commission_input">Adresservér én ny DALI-2 enhed</option>
<option value="restore_preview">Backup: vis restore-plan</option><option value="restore_apply">Backup: udfør restore / udskiftning</option>
<option value="emergency_read">DT1 læs status</option><option value="emergency_test">DT1 manuel test</option><option value="reset">Reset armatur</option>
</select></label></div><div id="argFields" class="pulsar-args"></div><div hidden><textarea id="args"></textarea></div>
<p id="hint" class="muted"></p><label class="check"><input id="writeconfirm" type="checkbox">Bekræft handlingen. Anden DALI-commissioning er stoppet.</label><label class="check"><input id="testbus" type="checkbox">Isoleret testbus (påkrævet ved DALI-2 adressering og nødlystest).</label>
<p class="muted" id="warning" hidden>Restore kan gennemføre delvise ændringer. DT1-test erstatter ikke godkendt nødlysvedligehold.</p></div><div class="actions"><button id="refresh">Opdater enheder</button><button class="primary" id="run" disabled>Kør test</button><button id="export" disabled>Eksportér JSON</button></div><p id="status" class="pulsar-state" role="status">Indlæser…</p>
</section><section id="resultSection"><h2>Resultat</h2><p id="summary" class="muted">Ingen test kørt.</p><div id="metrics" class="pulsar-metrics"></div><div class="scroll"><table><thead><tr><th>Kontrol</th><th>Status</th><th>Værdi / fejl</th></tr></thead><tbody id="results"></tbody></table></div></section>
<section id="telegramSection"><h2>Telegramlog</h2><p class="muted">TX = kodet forespørgsel til STM32. RX = svarpayload efter validering af ramme/checksum. Ingen antagelse om faktisk busmåling.</p><div class="scroll"><table><thead><tr><th>TX</th><th>RX</th><th>ms</th></tr></thead><tbody id="trace"></tbody></table></div></section>
</main><script>
"use strict";
const $=id=>document.getElementById(id);
let snapshot=null,report=null,busy=false,devices=[],controllers=[];
function action(){return $("action").value;}
const configurationPage=location.pathname.replace(/\/$/,"").endsWith("/configuration");
let busAction=false;
function needsDevice(){return configurationPage?!busAction:$("mode").value!=="communication"&&!( $("mode").value==="advanced"&&action()==="commission_input");}
function currentDevice(){return devices[Number($("device").value)-1];}
function typesOf(g){return [...new Set([...(Array.isArray(g.device_types)?g.device_types:[]),g.device_type].filter(v=>Number.isInteger(v)&&v!==255))];}
function availableActions(g){
 if(!g)return [];
 if(g.kind==="input")return ["input_read","input_config"];
 const t=typesOf(g),a=["inspect","name","basic_config","fade","memory"];
 if(t.includes(6))a.push("curve");
 if(t.includes(8))a.push("color");
 if(t.includes(1))a.push("emergency_read","emergency_test");
 if(!t.includes(1)&&t.length&&g.device_type!==255)a.push("restore_preview","restore_apply","reset");
 return a;
}
const groups=[
 ["Generelt",[["inspect","Læs egenskaber"],["name","Navn"],["basic_config","Grundparametre"],["fade","Fade"],["curve","Dimmekurve"]]],
 ["Farvestyring",[["color","Farve / Tunable White"]]],
 ["Identifikation og diagnose",[["memory","Memory Banks / D4i"],["input_read","Læs sensorstatus"],["input_config","Sensorindstillinger"]]],
 ["Vedligeholdelse",[["restore_preview","Restore-plan"],["restore_apply","Gendan / udskift"],["reset","Reset"],["emergency_read","Nødlysstatus"],["emergency_test","Nødlystest"]]]
];
function describeDevice(g){
 const root=$("deviceOverview");root.replaceChildren();root.hidden=!g;if(!g)return;
 const title=document.createElement("h2");title.textContent=g.kind==="input"?(g.instance_type_name||"DALI-2 input")+" · adresse "+g.address+" / instance "+g.instance:g.name||"Armatur "+g.address;root.append(title);
 const meta=document.createElement("p");meta.className="muted";meta.textContent="DALI "+g.bus+" · "+(g.kind==="input"?"Instance "+g.instance:typesOf(g).map(t=>"DT"+t).join(", ")||"Enhedstype ikke afklaret")+" · "+(g.address_conflict?"Adressekonflikt":g.online===false?"Offline":"Registreret");root.append(meta);
 const grid=document.createElement("div");grid.className="device-facts";
 const fields=g.kind==="input"?[["Instancetype",g.instance_type],["Aktiveret",g.enabled],["Værdi",g.input_value],["Tilstedeværelse",g.occupied],["Eventfilter",g.event_filter]]:[["Aktuelt niveau",g.actual_level],["Min. niveau",g.min_level],["Maks. niveau",g.max_level],["Fade Time",g.fade_time],["Fade Rate",g.fade_rate],["GTIN",g.gtin],["Identifikation",g.identification_raw],["Firmware",g.driver_firmware],["Hardware",g.driver_hardware],["Sidste bank",g.last_memory_bank],["Effekt (senest målt W)",g.power_w],["Energi (senest målt kWh)",g.energy_kwh],["Batteri (senest målt %)",g.battery_percent]];
 for(const [label,v] of fields){if(v===undefined||v===null)continue;const box=document.createElement("div"),k=document.createElement("small"),val=document.createElement("strong");k.textContent=label;val.textContent=typeof v==="boolean"?(v?"Ja":"Nej"):String(v);box.append(k,val);grid.append(box);}
 root.append(grid);
}
function fadeLabel(k,n){
 if(k==="fade_time")return n===0?"0 · Ingen programmeret fade":n+" · "+(0.5*Math.pow(2,n/2)).toLocaleString("da-DK",{maximumFractionDigits:2})+" s";
 if(k==="fade_rate")return n+" · "+(506/Math.pow(2,n/2)).toLocaleString("da-DK",{maximumFractionDigits:1})+" trin/s";
 return String(n);
}
const directRows=[
 ["basic_config","min_level","Minimum Level",0,254],["basic_config","max_level","Maximum Level",0,254],["basic_config","power_on_level","Power-on Level",0,255],["basic_config","system_failure_level","System Failure Level",0,255],
 ["fade","fade_time","Fade Time",0,15],["fade","fade_rate","Fade Rate",1,15],["fade","extended_fade_time","Extended Fade Time",0,79]
];
function directSettings(g){
 const root=$("directSettings");root.replaceChildren();root.hidden=!configurationPage||!g||g.kind!=="gear";if(root.hidden)return;
 const name=document.createElement("section");name.className="settings-panel";const nh=document.createElement("h3");nh.textContent="Navn";name.append(nh);
 const line=document.createElement("div");line.className="setting-row";const label=document.createElement("label");label.textContent="Armaturets navn";label.htmlFor="direct_name";const input=document.createElement("input");input.id="direct_name";input.value=g.name||"";input.maxLength=80;input.placeholder="Armatur "+g.address;const save=document.createElement("button");save.textContent="Gem";save.type="button";save.onclick=()=>{const v=input.value.trim();if(!v){status("Indtast et navn.","error");return;}saveDirect("name",{name:v});};line.append(label,input,save);name.append(line);root.append(name);
 const grid=document.createElement("div");grid.className="settings-grid";root.append(grid);
 for(const [heading,kind] of [["Grundparametre","basic_config"],["Fade og dimning","fade"]]){
  const panel=document.createElement("section");panel.className="settings-panel";const h=document.createElement("h3");h.textContent=heading;panel.append(h);
  for(const [a,k,title,min,max] of directRows.filter(x=>x[0]===kind)){
   if(k==="extended_fade_time"&&!Number.isInteger(g[k]))continue;
   const row=document.createElement("div");row.className="setting-row";const label=document.createElement("label");label.htmlFor="direct_"+k;label.textContent=title;
   const choice=k==="fade_time"||k==="fade_rate";
   const input=document.createElement(choice?"select":"input");input.id=label.htmlFor;input.required=true;
   if(choice){option(input,"","Ikke aflæst");for(let n=min;n<=max;n++)option(input,String(n),fadeLabel(k,n));}
   else{input.type="number";input.min=min;input.max=max;input.step=1;input.placeholder="Ikke aflæst";}
   input.value=Number.isInteger(g[k])?String(g[k]):"";
   if(a==="basic_config"){const detail=document.createElement("small");detail.className="muted";const show=()=>{const v=Number(input.value);detail.textContent=input.value===""?"Ikke aflæst":v===255?"MASK / specialværdi":(v/254*100).toLocaleString("da-DK",{maximumFractionDigits:1})+" % af DALI-kodeområdet";};input.addEventListener("input",show);show();label.append(detail);}
   const button=document.createElement("button");button.type="button";button.textContent="Gem";button.onclick=()=>{if(!input.reportValidity())return;const value=Number(input.value);if(k==="extended_fade_time"&&(value&15)>4){status("Reserveret extended fade kode.","error");return;}saveDirect(a,{parameter:k,value});};
   row.append(label,input,button);panel.append(row);
  }
  if(kind==="fade"&&typesOf(g).includes(6)){
   const row=document.createElement("div");row.className="setting-row";const label=document.createElement("label");label.textContent="Dimmekurve";label.htmlFor="direct_curve";const select=document.createElement("select");select.id=label.htmlFor;option(select,"","Ikke aflæst");option(select,"0","Logaritmisk");option(select,"1","Lineær");select.value=g.dimming_curve==null?"":String(g.dimming_curve);select.required=true;
   const button=document.createElement("button");button.textContent="Gem";button.type="button";button.onclick=()=>{if(select.reportValidity())saveDirect("curve",{value:Number(select.value)});};row.append(label,select,button);panel.append(row);
  }
  grid.append(panel);
 }
 const note=document.createElement("p");note.className="muted";note.textContent="Hver indstilling gemmes separat. Fade vises med tid eller trin/s; niveauprocent er kodeprocent, ikke målt lysudbytte. Skrivning kræver bekræftelse og tilbageaflæsning.";root.append(note);
 for(const el of root.querySelectorAll("input,select,button"))el.disabled=busy||g.online===false||!!g.address_conflict;
}
async function saveDirect(a,params){
 if(busy||!snapshot)return;const g=currentDevice(),c=selected();
 if(!g||g.kind!=="gear"||g.online===false||g.address_conflict||!availableActions(g).includes(a))return;
 const value=params.value??params.name;
 if(a!=="name"&&!window.confirm("Gem "+(params.parameter||"dimmekurve")+" = "+value+" på DALI "+g.bus+", adresse "+g.address+"? Anden DALI-commissioning skal være stoppet."))return;
 const d={controller_id:snapshot.controller_id,bus:g.bus,address:g.address,uid:g.ha_uid,mode:"advanced",action:a,confirm:true,...params};
 clear();lock(true);status("Gemmer indstilling…");
 try{
  report=c.id==="local"?await req("api/lab/run",d):await req("api/lab/remote",{registry_id:c.id,controller_id:d.controller_id,operation:"run",test:d});
  if(report.controller_id!==d.controller_id)throw Error("Forkert controller i svar");
  if(report.ok===false)throw Error(report.error||"Ændringen blev afvist");
  render(report);
  await refreshSelected(deviceKey(g),"inspect");
  status(a==="name"?"Navn gemt.":"Indstilling gemt og tilbageaflæst.","success");
 }catch(e){status(String(e),"error");}finally{lock(false);}
}
function deviceOptions(preferred){
 if(!configurationPage)return;
 const g=currentDevice(),allowed=availableActions(g),sel=$("action"),root=$("deviceOptions");
 busAction=false;$("busTools").hidden=!!g||!snapshot;
 describeDevice(g);directSettings(g);root.replaceChildren();root.hidden=!g;$("actionLabel").hidden=true;
 sel.replaceChildren();for(const [heading,entries] of groups){const matching=entries.filter(([key])=>allowed.includes(key)&&!(g?.kind==="gear"&&["name","basic_config","fade","curve"].includes(key)));if(!matching.length)continue;
  const section=document.createElement("div");section.className="device-option-group";
  const label=document.createElement("h3");label.textContent=heading;section.append(label);
  const items=document.createElement("div");items.className="device-option-buttons";
  for(const [key,name] of matching){option(sel,key,name);const btn=document.createElement("button");btn.type="button";btn.dataset.action=key;btn.textContent=name;btn.onclick=()=>{if(busy)return;clear();sel.value=key;advancedFields();lock(false);};items.append(btn);}
  section.append(items);root.append(section);
 }
 if(allowed.includes(preferred))sel.value=preferred;
 else if(g)sel.value=g.kind==="input"?"input_read":"inspect";
 else sel.value="";
}
function markAction(){if(configurationPage)for(const e of $("deviceOptions").querySelectorAll("button")){e.classList.toggle("primary",e.dataset.action===action());e.setAttribute("aria-pressed",String(e.dataset.action===action()));}}

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
 const a=action(),root=$("argFields");root.replaceChildren();backupSeq++;markAction();
 if(configurationPage&&!currentDevice()&&!busAction){$("hint").textContent="Vælg en enhed for at se dens konfiguration.";$("writeconfirm").parentElement.hidden=true;$("testbus").parentElement.hidden=true;$("warning").hidden=true;return;}
 const wrap=document.createElement("div");wrap.className="fields";root.append(wrap);
 const g=devices[Number($("device").value)-1]||{};
 const add=(...x)=>field(wrap,...x);
 const numeric=(id,label,v,min,max)=>add(id,label,"number",v,{min,max});
 const select=(id,label,v,choices)=>add(id,label,"select",v,{choices});
 const text=(id,label,v)=>add(id,label,"text",v);
 $("warning").hidden=!["restore_apply","restore_preview","reset","commission_input","emergency_test"].includes(a);
 $("testbus").parentElement.hidden=!["commission_input","emergency_test"].includes(a);
 $("writeconfirm").parentElement.hidden=["name","inspect","input_read","emergency_read","restore_preview"].includes(a);
 $("hint").textContent="";
 if(a==="basic_config"){
   const rows=[["min_level","Minimum Level"],["max_level","Maximum Level"],["power_on_level","Power-on Level"],["system_failure_level","System Failure Level"]].filter(([k])=>Number.isInteger(g[k]));
   if(!rows.length){$("hint").textContent="Ingen grundparametre aflæst. Opdater eller scan enheden først.";return;}
   const p=select("parameter","Parameter",rows[0][0],rows),v=numeric("value","Ny værdi",g[p.value],0,254);
   const update=()=>{v.max=["power_on_level","system_failure_level"].includes(p.value)?255:254;v.value=g[p.value];};p.onchange=update;update();$("hint").textContent="Aktuel værdi fra seneste aflæsning. Ændringer verificeres med tilbageaflæsning.";
 }else if(a==="input_read"){$("hint").textContent="Læs den valgte instances aktuelle værdi.";
 }else if(a==="fade"){
   const fadeChoices=[["fade_time","Fade Time"],["fade_rate","Fade Rate"],["extended_fade_time","Extended Fade Time"]].filter(([k])=>k!=="extended_fade_time"||Number.isInteger(g[k]));
   const p=select("parameter","Fade-parameter","fade_time",fadeChoices);
   const v=numeric("value","Kodet værdi",g.fade_time??"",0,15);
   const update=()=>{const n=p.value;v.min=n==="fade_rate"?1:0;v.max=n==="extended_fade_time"?79:15;v.value=g[n]??"";$("hint").textContent=n==="extended_fade_time"?"Rå DALI-kode: multiplikator og basis. 0 deaktiverer.":"Kodet DALI-værdi (ikke sekunder). Efter skrivning læses parameteren tilbage.";};
   p.onchange=update;update();
 }else if(a==="curve"){select("value","Dimmekurve",g.dimming_curve??"",[["","Vælg dimmekurve"],[0,"Logaritmisk"],[1,"Lineær"]]);}
 else if(a==="memory"){const banks=[[0,"0 · Identifikation"]];if(g.last_memory_bank>=1)banks.push([1,"1 · Producentdata"]);for(const [n,label] of [[202,"Aktiv energi"],[203,"Tilsyneladende energi"],[204,"Udgangsenergi"],[205,"Driverdiagnostik"],[206,"Lyskildediagnostik"],[207,"Rådata"]])if(g.last_memory_bank>=n)banks.push([n,n+" · "+label]);banks.push([-1,"Anden bank (rånummer)"]);const chosen=select("bank_choice","Memory bank",0,banks);const raw=numeric("bank","Banknummer",0,0,255);raw.parentElement.hidden=true;chosen.onchange=()=>{raw.parentElement.hidden=chosen.value!=="-1";if(chosen.value!=="-1")raw.value=chosen.value;};$("hint").textContent="Bank 0: identifikation · 1: producentdata · 202–204: energi · 205–206: diagnostik · 207: rådata. D4i kræver understøttelse.";}
 else if(a==="name"){text("name","Armaturets navn",g.name||"");$("hint").textContent="Navnet gemmes i controlleren; eksisterende MQTT-identitet bevares.";}
 else if(a==="color"){
   const choices=[];if((g.colour_features&2)&&g.min_kelvin&&g.max_kelvin)choices.push(["kelvin","Tunable White (Kelvin)"]);if(g.rgbwaf_channels>=3&&g.rgbwaf_channels<=6)choices.push(["rgbwaf","RGB / RGBWAF"]);if(!choices.length){$("hint").textContent="Læs egenskaber først. Ingen understøttet farvetype er bekræftet endnu.";return;}const cap=select("color_kind","Farvetype",choices[0][0],choices);
   const area=document.createElement("div");area.className="fields";root.append(area);
   const update=()=>{
    area.replaceChildren();
    if(cap.value==="kelvin"){
      const lo=g.min_kelvin,hi=g.max_kelvin;
      const number=field(area,"kelvin","Farvetemperatur (K)","number",g.color_temp_kelvin??"",{min:lo,max:hi});
      const control=document.createElement("div");control.className="color-control";
      const slider=document.createElement("input");slider.type="range";slider.min=lo;slider.max=hi;slider.step=1;slider.value=g.color_temp_kelvin??Math.round((lo+hi)/2);slider.setAttribute("aria-label","Farvetemperatur");
      const gradient=document.createElement("div");gradient.className="temperature-gradient";
      const labels=document.createElement("div");labels.className="color-labels";labels.textContent=lo+" K · Varm hvid / Kold hvid · "+hi+" K";
      slider.oninput=()=>{number.value=slider.value;};number.oninput=()=>{if(number.checkValidity())slider.value=number.value;};
      control.append(labels,gradient,slider);area.append(control);
    }else{
      const n=Number(g.rgbwaf_channels);
      const channels=field(area,"channels","Antal kanaler","select",n,{choices:[[n,({3:"RGB",4:"RGBW",5:"RGBWA",6:"RGBWAF"})[n]]]});
      const levels=document.createElement("div");levels.className="fields";area.append(levels);
      const inputs=[];for(let i=0;i<n;i++)inputs.push(field(levels,"rgb_"+i,["Rød","Grøn","Blå","Hvid","Amber","Fri kanal"][i],"number",g.rgbwaf?.[i]??"",{min:0,max:254}));
      const visual=document.createElement("label");visual.className="color-control";visual.textContent="RGB-farvevælger (kun RGB-kanaler)";
      const picker=document.createElement("input");picker.type="color";picker.value="#ffffff";
      const hex=()=>"#"+inputs.slice(0,3).map(e=>Math.round(Number(e.value)*255/254).toString(16).padStart(2,"0")).join("");
      if(inputs.slice(0,3).every(e=>e.value!==""&&e.checkValidity()))picker.value=hex();
      picker.oninput=()=>{for(let i=0;i<3;i++)inputs[i].value=String(Math.round(parseInt(picker.value.slice(1+i*2,3+i*2),16)*254/255));};
      for(const e of inputs.slice(0,3))e.oninput=()=>{if(inputs.slice(0,3).every(v=>v.value!==""&&v.checkValidity()))picker.value=hex();};
      visual.append(picker);area.append(visual);
    }
    $("hint").textContent="Farvevælgeren ændrer kun formularen. Den valgte farve sendes først, når du bekræfter handlingen.";
   };
   cap.onchange=update;update();
 }else if(a==="input_config"){
   const rows=inputFields.filter(x=>x.length===4||x[4]===g.instance_type);
   const p=select("parameter","Sensorparameter","event_filter",rows.map(x=>[x[0],x[1]]));
   const v=text("value","Værdi",g.event_filter??"");
   const bits=document.createElement("div");bits.className="event-bits";root.append(bits);
   const rebuild=()=>{
     bits.replaceChildren();bits.hidden=p.value!=="event_filter";if(bits.hidden)return;
     const valid=/^(?:\d+|0x[0-9a-f]+)$/i.test(v.value)&&Number(v.value)>=0&&Number(v.value)<=16777215;
     if(!valid){bits.append(document.createTextNode("Aflæs eller indtast en gyldig eventmaske først."));return;}
     const mask=Number(v.value);
     for(let i=0;i<24;i++){const label=document.createElement("label"),box=document.createElement("input");box.type="checkbox";box.checked=Boolean(mask&(1<<i));box.onchange=()=>{const old=Number(v.value);v.value=String(box.checked?old|(1<<i):old&~(1<<i));};label.append(box,document.createTextNode((g.instance_type===1?["Button released","Button pressed","Short press","Double press","Long press start","Long press repeat","Long press stop","Button free","Button stuck"][i]:undefined)||"Bit "+i));bits.append(label);}
   };
   const update=()=>{const row=rows.find(x=>x[0]===p.value);v.value=g[p.value]??"";$("hint").textContent="Tilladt råværdi "+row[2]+"–"+row[3]+". Eventfilter kan indtastes i hex. Bitbetydning afhænger af instancetype.";rebuild();};p.onchange=update;v.oninput=rebuild;update();
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
 if(a==="memory")delete out.bank_choice;
 if(a==="fade"&&out.parameter==="extended_fade_time"&&(out.value&15)>4)throw Error("Reserveret extended fade kode");
 if(a==="input_config"){const row=inputFields.find(x=>x[0]===out.parameter);if(!/^(?:\d+|0x[0-9a-f]+)$/i.test(out.value))throw Error("Indtast et heltal");out.value=Number(out.value);if(!row||!Number.isInteger(out.value)||out.value<row[2]||out.value>row[3])throw Error("Parameter uden for område");}
 if(a==="color"){if(out.color_kind==="rgbwaf"){out.rgbwaf=Array.from({length:out.channels},(_,i)=>out["rgb_"+i]);for(const k of Object.keys(out))if(k.startsWith("rgb_"))delete out[k];delete out.channels;}delete out.color_kind;}
 return out;
}
function status(s,state=""){ $("status").textContent=s;$("status").dataset.state=state; }
function lock(v){busy=v;for(const id of ["controller","bus","mode","device","bank","offset","count","confirm","refresh","action","args","writeconfirm","testbus"])$(id).disabled=v;for(const e of $("argFields").querySelectorAll("input,select"))e.disabled=v;$("deviceLabel").hidden=!configurationPage&&!needsDevice();$("commissionInput").disabled=v;for(const e of $("deviceOptions").querySelectorAll("button"))e.disabled=v;const g=currentDevice();for(const e of $("directSettings").querySelectorAll("input,select,button"))e.disabled=v||!g||g.online===false||!!g.address_conflict;$("run").disabled=v||!snapshot||(needsDevice()&&!$("device").value)||(configurationPage&&!busAction&&(!g||g.online===false||g.address_conflict||!action()||!availableActions(g).includes(action())||(action()==="basic_config"&&!$("arg_parameter"))||(action()==="color"&&!$("arg_color_kind"))));$("export").disabled=v||!report;}
function clear(){report=null;$("results").replaceChildren();$("trace").replaceChildren();$("summary").textContent=configurationPage?"":"Ingen test kørt.";if(configurationPage)$("resultSection").hidden=true;$("metrics").replaceChildren();$("export").disabled=true;}
function option(select,value,label){const el=document.createElement("option");el.value=value;el.textContent=label;select.append(el);}
async function req(path,data){const base=location.pathname.replace(/\/(?:testlab|configuration)\/?$/,"/").replace(/[^/]*$/,"");const r=await fetch(base+path,{method:data===undefined?"GET":"POST",headers:{"Content-Type":"application/json"},body:data===undefined?undefined:JSON.stringify(data),cache:"no-store"});const j=await r.json();if(!r.ok||(j.ok===false&&!j.controller_id))throw Error(j.error||"HTTP "+r.status);return j;}
function selected(){return controllers.find(c=>c.id===$("controller").value);}
function populate(){const mode=$("mode").value,bus=Number($("bus").value);$("memory").hidden=mode!=="memory";$("volatile").hidden=!["memory","capabilities"].includes(mode);$("confirm").checked=false;$("device").replaceChildren();devices=[];option($("device"),"","Vælg enhed");
if(snapshot&&(configurationPage||needsDevice())){
 if(configurationPage){
  const gear=(snapshot.gear||[]).filter(g=>g.bus===bus).map(g=>({...g,kind:"gear"}));
  const inputs=(snapshot.input_instances||[]).filter(g=>g.bus===bus).map(g=>({...g,kind:"input",online:(snapshot.control_devices||[]).find(d=>d.bus===g.bus&&d.address===g.address)?.online}));
  devices=[...gear,...inputs];
  for(const [kind,label] of [["gear","Armaturer"],["input","Sensorer og tryk"]]){const group=document.createElement("optgroup");group.label=label;
   devices.forEach((g,i)=>{if(g.kind!==kind)return;option(group,String(i+1),kind==="input"?"Adresse "+g.address+" / instance "+g.instance+" · "+(g.instance_type_name||"Input"):"Adresse "+g.address+" · "+(g.name||typesOf(g).map(t=>"DT"+t).join(", ")||"Armatur"));});if(group.children.length)$("device").append(group);}
 }else{
  const input=mode==="input";devices=(input?snapshot.input_instances:snapshot.gear)||[];devices=devices.filter(x=>x.bus===bus&&(input||!x.address_conflict));devices.forEach((g,i)=>option($("device"),String(i+1),input?"Adresse "+g.address+" / instance "+g.instance+" · "+(g.instance_type_name||"Input"):"Adresse "+g.address+" · "+(g.name||"DT "+g.device_type)));
 }
} if(mode==="advanced"){deviceOptions();advancedFields();}lock(busy);}
function deviceKey(g){return g?JSON.stringify([g.kind,g.bus,g.address,g.instance??null,g.ha_uid??null]):"";}
async function refreshSelected(key,preferred){
 const c=selected();if(!c||!snapshot)return;
 const target={registry_id:c.id,controller_id:c.remote_controller_id||c.controller_id};
 const fresh=c.id==="local"?await req("api/devices"):await req("api/lab/remote",{...target,operation:"snapshot"});
 if(fresh.controller_id!==target.controller_id||fresh.controller_id!==snapshot.controller_id)throw Error("Controller-ID ændret; genindlæs siden");
 snapshot=fresh;populate();const idx=devices.findIndex(g=>deviceKey(g)===key);
 if(idx>=0){$("device").value=String(idx+1);deviceOptions(preferred);advancedFields();}
}

async function load(){if(busy)return;clear();snapshot=null;lock(true);populate();status("Henter aktuelle enheder…");
try{const c=selected();if(!c)throw Error("Vælg controller");const target={registry_id:c.id,controller_id:c.remote_controller_id||c.controller_id};snapshot=c.id==="local"?await req("api/devices"):await req("api/lab/remote",{...target,operation:"snapshot"});if(snapshot.controller_id!==target.controller_id)throw Error("Controller-ID ændret; genindlæs siden");status(configurationPage?"Klar · "+c.name:"Controller: "+c.name+" · "+snapshot.controller_id);populate();}catch(e){snapshot=null;status(String(e));}finally{lock(false);}}
function cell(tr,value,cls){const td=document.createElement("td");td.textContent=value==null?"—":typeof value==="object"?JSON.stringify(value):String(value);if(cls)td.className=cls;tr.append(td);}
function render(r){
 if(configurationPage)$("resultSection").hidden=false;
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
async function run(){if(busy||!snapshot)return;clear();const c=selected(),mode=$("mode").value,g=devices[Number($("device").value)-1];const d={controller_id:snapshot.controller_id,bus:Number($("bus").value),mode,confirm_volatile:$("confirm").checked};if(needsDevice()){if(!g)return;d.address=g.address;d.uid=g.ha_uid;d.instance=g.instance;}if(mode==="advanced"){try{if(configurationPage&&!busAction&&!availableActions(g).includes(action()))throw Error("Handlingen passer ikke til den valgte enhed");const params=paramsFromForm();Object.assign(d,params,{controller_id:snapshot.controller_id,bus:Number($("bus").value),mode,action:action(),address:g?.address,uid:g?.ha_uid,instance:g?.instance,confirm:$("writeconfirm").checked||["name","inspect","input_read","emergency_read","restore_preview"].includes(action()),test_bus:$("testbus").checked});if(!d.confirm){status("Bekræft handlingen først.","error");return;}if(["commission_input","emergency_test"].includes(action())&&!d.test_bus){status("Bekræft isoleret testbus.","error");return;}}catch(e){status(String(e));return;}}if(mode==="memory")Object.assign(d,{bank:Number($("bank").value),offset:Number($("offset").value),count:Number($("count").value)});if(["memory","capabilities"].includes(mode)&&!d.confirm_volatile){status("Bekræft de midlertidige buskommandoer først.");return;}lock(true);status((configurationPage?"Udfører handling på ":"Test kører på ")+c.name+" · DALI "+d.bus+"…");try{report=c.id==="local"?await req("api/lab/run",d):await req("api/lab/remote",{registry_id:c.id,controller_id:d.controller_id,operation:"run",test:d});if(report.controller_id!==d.controller_id)throw Error("Forkert controller i svar");render(report);if(configurationPage){try{await refreshSelected(deviceKey(g),d.action);}catch(e){status("Handling udført; opdatering af enhed mislykkedes: "+e.message,"error");return;}}status(report.ok===false?"Delvis handling eller fejl: "+(report.error||"se resultat"):mode==="advanced"?"Handling afsluttet. Se resultat og eventuel read-back.":"Test afsluttet. No reply kan betyde manglende understøttelse eller kommunikationsfejl.",report.ok===false?"error":"success");}catch(e){report=null;status(String(e),"error");}finally{$("writeconfirm").checked=false;$("testbus").checked=false;lock(false);}}
$("controller").onchange=()=>{localStorage.setItem("pulsar_active_controller",$("controller").value);load();};$("refresh").onclick=load;$("bus").onchange=()=>{clear();populate();};$("mode").onchange=()=>{clear();advancedFields();populate();};$("action").onchange=()=>{clear();advancedFields();populate();};$("device").onchange=()=>{clear();if($("mode").value==="advanced"){deviceOptions();advancedFields();}lock(false);};$("run").onclick=run;
$("commissionInput").onclick=()=>{if(busy||!snapshot||!configurationPage||currentDevice())return;busAction=true;clear();$("action").replaceChildren();option($("action"),"commission_input","Adresservér én ny enhed");$("action").value="commission_input";advancedFields();lock(false);};
if(configurationPage)deviceOptions();advancedFields();
$("export").onclick=()=>{if(!report)return;const u=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:"application/json"}));const a=document.createElement("a");a.href=u;a.download="pulsar-dali-test-"+Date.now()+".json";a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);};
(async()=>{try{const j=await req("api/controllers");controllers=[j.local,...j.controllers].filter(Boolean);for(const c of controllers)option($("controller"),c.id,c.name||c.id);const stored=localStorage.getItem("pulsar_active_controller");if(controllers.some(c=>c.id===stored))$("controller").value=stored;const q=new URLSearchParams(location.search);if(["1","2","3"].includes(q.get("bus")))$("bus").value=q.get("bus");await load();if(q.has("address")){const idx=devices.findIndex(x=>x.address===Number(q.get("address"))&&(!configurationPage||x.kind==="gear"));if(idx>=0){$("device").value=String(idx+1);if($("mode").value==="advanced"){deviceOptions();advancedFields();}lock(false);}}}catch(e){status(String(e));lock(false);}})();
</script></body></html>'''

def page_for(configuration=False):
    from ui_layout import apply
    if configuration:
        page=PAGE.replace('<option value="communication">STM32-kommunikation</option>','')
        page=page.replace('<option value="advanced">','<option value="advanced" selected>')
        page=page.replace('<label id="modeLabel">','<label id="modeLabel" hidden>')
        page=page.replace('<h2>Vælg test</h2>','<h2>Vælg enhed</h2>')
        page=page.replace('>Kør test</button>','>Udfør handling</button>')
        page=page.replace('<section id="telegramSection">','<section id="telegramSection" hidden>')
        page=page.replace('<section id="resultSection"><h2>Resultat</h2>','<section id="resultSection" hidden><h2>Handlingsdetaljer</h2>')
        page=page.replace('Ingen test kørt.</p>','</p>')
        page=page.replace('<th>Kontrol</th><th>Status</th><th>Værdi / fejl</th>','<th>Parameter</th><th>Status</th><th>Værdi / fejl</th>')
        page=page.replace('Eksportér JSON</button>','Eksportér handlingsdata</button>')
        return apply(page,"configuration")
    page=PAGE.replace('<option value="advanced">Avanceret konfiguration</option>','')
    return apply(page,"testlab")
