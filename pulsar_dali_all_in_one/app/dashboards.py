"""Read-only management dashboards."""
import json,shutil,time,threading,os
from pathlib import Path
from ui_layout import apply
LOCK=threading.Lock()
STATS={}
def install(transport):
    old=transport.transact
    def measured(self,*args,**kwargs):
        start=time.monotonic(); failed=False
        try: return old(self,*args,**kwargs)
        except Exception:
            failed=True;raise
        finally:
            elapsed=(time.monotonic()-start)*1000
            with LOCK:
                x=STATS.setdefault(str(self.bus_number),{"transactions":0,"exceptions":0,"total_ms":0,"max_ms":0})
                x["transactions"]+=1;x["exceptions"]+=int(failed);x["total_ms"]+=elapsed;x["max_ms"]=max(x["max_ms"],elapsed)
    transport.transact=measured
def resources():
    out={}
    try:
        x=shutil.disk_usage("/data");out["data_disk"]={"total":x.total,"used":x.used,"free":x.free}
    except OSError: pass
    try:
        m={}
        for line in Path("/proc/meminfo").read_text().splitlines():
            k,v=line.split(":",1)
            if k in ("MemTotal","MemAvailable"): m[k]=int(v.split()[0])*1024
        if "MemTotal" in m and "MemAvailable" in m: out["visible_memory"]={"total":m["MemTotal"],"available":m["MemAvailable"]}
        out["load_average"]=list(os.getloadavg())
    except (OSError,ValueError): pass
    return out
def local_info(c):
    history=[]
    try:
        with Path("/data/emergency_history.jsonl").open() as f:
            from collections import deque
            for line in deque(f,maxlen=200):
                try:
                    row=json.loads(line)
                    if row.get("controller_id")==c.controller_id:history.append(row)
                except (ValueError,AttributeError): pass
    except OSError: pass
    with LOCK: stats={k:dict(v) for k,v in STATS.items()}
    for v in stats.values(): v["mean_ms"]=round(v["total_ms"]/max(1,v["transactions"]),1)
    return {"ok":True,"controller_id":c.controller_id,"resources":resources(),"transactions":stats,"history":history}
PAGE=r'''<!doctype html><html lang="da"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Pulsar DALI</title>
<style>.dash-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,190px),1fr));gap:12px;margin:12px 0}.dash-stat{border:1px solid var(--border);border-radius:10px;padding:14px;background:var(--card);min-width:0}.dash-stat small{display:block;color:var(--muted)}.dash-stat strong{font-size:23px;display:block;margin:4px 0;font-variant-numeric:tabular-nums}.dash-meter{height:8px;background:var(--border);border-radius:6px;overflow:hidden}.dash-meter span{display:block;height:100%;background:var(--accent)}.dash-table{overflow:auto}.dash-table table{min-width:620px}.dash-table td:first-child{font-weight:550}.dash-note{font-size:13px;color:var(--muted)}.dash-actions{display:flex;gap:8px;align-items:end;flex-wrap:wrap}.dash-actions label{flex:1;min-width:180px}.dash-actions label span{display:block;font-size:13px;margin-bottom:6px}</style></head>
<body><main><h1>Administration</h1><p>Administration</p><nav></nav>
<section><div class="dash-actions"><label><span>Controller</span><select id="target"></select></label><button id="refresh">Opdater</button><button id="download" disabled>Eksportér JSON</button></div><p id="status" role="status" class="pulsar-state">Indlæser…</p></section>
<div id="summary" class="dash-grid"></div><div id="content"></div></main>
<script>
"use strict";
const page="__PAGE__", $=id=>document.getElementById(id);
let controllers=[],last=null,busy=false;
const fmt=(v,n=1)=>Number.isFinite(v)?v.toLocaleString("da-DK",{maximumFractionDigits:n}):"—";
const dt=t=>Number.isFinite(t)&&t>0?new Date(t*1000).toLocaleString("da-DK"):"—";
const bytes=v=>Number.isFinite(v)?fmt(v/1048576,0)+" MB":"—";
const fresh=(g,b,now=Date.now()/1000)=>g.online===true&&!g.address_conflict&&Number.isFinite(g["sampled_bank_"+b])&&now-g["sampled_bank_"+b]>=0&&now-g["sampled_bank_"+b]<900;
function energyStats(gear,now){const eligible=gear.filter(g=>g.last_memory_bank>=202);const power=eligible.filter(g=>fresh(g,202,now)&&Number.isFinite(g.power_w)&&g.power_w>=0);const energy=eligible.filter(g=>fresh(g,202,now)&&Number.isFinite(g.energy_kwh)&&g.energy_kwh>=0);return {eligible:eligible.length,powerCount:power.length,energyCount:energy.length,power:power.length?power.reduce((a,g)=>a+g.power_w,0):null,energy:energy.length?energy.reduce((a,g)=>a+g.energy_kwh,0):null};}
function el(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=String(text);if(cls)e.className=cls;return e;}
function stat(label,value,note){const x=el("div",undefined,"dash-stat");x.append(el("small",label),el("strong",value),el("small",note||""));$("summary").append(x);}
function section(title,note){const x=el("section");x.append(el("h2",title));if(note)x.append(el("p",note,"dash-note"));$("content").append(x);return x;}
function table(parent,headers,rows){const wrap=el("div",undefined,"dash-table"),t=el("table"),head=el("thead"),tr=el("tr");for(const h of headers)tr.append(el("th",h));head.append(tr);t.append(head);const body=el("tbody");for(const row of rows){const tr=el("tr");for(const value of row){const td=el("td");if(value instanceof Node)td.append(value);else td.textContent=value??"—";tr.append(td);}body.append(tr);}t.append(body);wrap.append(t);parent.append(wrap);}
function link(g){const a=el("a",g.name||"Armatur "+g.address);a.href="configuration?bus="+g.bus+"&address="+g.address;return a;}
function meter(parent,label,n,d){parent.append(el("p",label+" · "+n+" / "+d));const bar=el("div",undefined,"dash-meter"),fill=el("span");fill.style.width=(d?Math.min(100,n/d*100):0)+"%";bar.append(fill);parent.append(bar);}
function renderEnergy(s){const gear=s.gear||[],now=Date.now()/1000,v=energyStats(gear,now);stat("Målt effekt",fmt(v.power)+" W",v.powerCount+" af "+v.eligible+" mulige drivere");stat("Målt akkumuleret energi",fmt(v.energy,3)+" kWh","Sum af friske driverregistre, ikke afregningsmåler");stat("Dækning",v.powerCount+" / "+v.eligible,"Kandidater til bank 202");
 const coverage=section("Dækning pr. bus","Kun friske, gyldige målinger summeres. Manglende værdier er ikke nul.");
 const rows=[];for(const b of [1,2,3]){const x=energyStats(gear.filter(g=>g.bus===b),now);rows.push(["DALI "+b,fmt(x.power)+" W",fmt(x.energy,3)+" kWh",x.powerCount+" / "+x.eligible]);meter(coverage,"DALI "+b,x.powerCount,x.eligible);}table(coverage,["Bus","Effekt","Energi","Måledækning"],rows);
 const list=section("Armaturmålinger","Målinger ældre end 15 minutter vises som utilgængelige. Aktiver eventuelt D4i polling i add-on-indstillinger.");
 const devices=gear.filter(g=>g.last_memory_bank>=202);table(list,["Armatur","Bus","Effekt (W)","Energi (kWh)","Drift (timer)","Temp. (°C)","Bank 202 aflæst"],devices.map(g=>[link(g),g.bus,fresh(g,202)?fmt(g.power_w):"—",fresh(g,202)?fmt(g.energy_kwh,3):"—",fresh(g,205)&&Number.isFinite(g.gear_operation_seconds)?fmt(g.gear_operation_seconds/3600):"—",fresh(g,205)?fmt(g.gear_temperature_c):"—",dt(g.sampled_bank_202)]));if(!devices.length)list.append(el("p","Ingen driver med rapporteret bank 202 eller højere. Læs memory bank 0 i Konfiguration.","dash-note"));
}
function renderEmergency(s,info){const gs=(s.gear||[]).filter(g=>g.device_type===1||(g.device_types||[]).includes(1));stat("Nødlysarmaturer",gs.length);stat("Registreret online",gs.filter(g=>g.online&&!g.address_conflict).length);stat("Senest aflæst fejlbyte ≠ 0",gs.filter(g=>Number.isInteger(g.emergency_failure)&&g.emergency_failure!==0).length,"Ikke en sikkerhedsgodkendelse");
 const p=section("Nødbelysning","Status er senest aflæste rådata; batteriprocent er et estimat. Manuelle tests udføres kun på isoleret testbus fra Konfiguration.");table(p,["Armatur","Bus","Batteri (%)","Mode (rå)","Fejl (rå)","Status (rå)"],gs.map(g=>[link(g),g.bus,fmt(g.battery_percent),g.emergency_mode,g.emergency_failure,g.emergency_status]));if(!gs.length)p.append(el("p","Ingen DT1-enheder registreret.","dash-note"));
 const h=section("Kommandohistorik","En afsendt testkommando er ikke et bestået resultat. Historikken erstatter ikke certificeret vedligehold.");if(!info)h.append(el("p","Historik er kun tilgængelig lokalt.","dash-note"));else table(h,["Tid","Bus","Adresse","Kommando","Registreret resultat"],(info.history||[]).slice().reverse().map(x=>[dt(x.utc),x.bus,x.address,x.test,"Kommando sendt – ikke verificeret testresultat"]));
}
function renderMaintenance(s,info,backups){const gear=s.gear||[];stat("Armaturer",gear.length);stat("Offline / konflikt",gear.filter(g=>!g.online||g.address_conflict).length);stat("Backups",backups?backups.length:"—");
 const res=section("Systemressourcer","Ressourcer som Linux-containeren kan se; ikke en komplet måling af HAOS-værten.");if(info){const r=info.resources||{};table(res,["Ressource","Værdi"],[["Disk /data",r.data_disk?bytes(r.data_disk.used)+" / "+bytes(r.data_disk.total):"—"],["Synlig RAM tilgængelig",r.visible_memory?bytes(r.visible_memory.available)+" / "+bytes(r.visible_memory.total):"—"],["Load average (1/5/15 min)",(r.load_average||[]).map(x=>fmt(x,2)).join(" / ")||"—"]]);}else res.append(el("p","Lokale ressourcer er ikke tilgængelige for denne controller.","dash-note"));
 const comm=section("STM32-transaktioner","Tællere siden app-start. Svartid er UART/API-transaktionstid, ikke fysisk DALI-busbelastning. Exceptions er ikke alle DALI no-reply.");table(comm,["Bus","Transaktioner","Exceptions","Middel (ms)","Maks. (ms)"],Object.entries(info?.transactions||{}).map(([b,v])=>[b,v.transactions,v.exceptions,fmt(v.mean_ms),fmt(v.max_ms)]));
 const b=section("Konfigurationsbackups","Backup indeholder controllerens kendte konfiguration. Gendannelse udføres pr. enhed i Konfiguration.");table(b,["Fil","Årsag","Tid"],(backups||[]).map(x=>[x.filename,x.reason,x.created_utc||x.created_at||"—"]));const a=el("a","Åbn Commissioning");a.href="commissioning";b.append(a);
}
async function req(path,data){const r=await fetch(path,{method:data===undefined?"GET":"POST",headers:{"Content-Type":"application/json"},body:data===undefined?undefined:JSON.stringify(data),cache:"no-store"});const j=await r.json();if(!r.ok||j.ok===false)throw Error(j.error||"HTTP "+r.status);return j;}
async function load(){if(busy)return;busy=true;$("target").disabled=true;$("refresh").disabled=true;$("download").disabled=true;last=null;$("summary").replaceChildren();$("content").replaceChildren();$("status").textContent="Henter data…";try{
 const c=controllers.find(x=>x.id===$("target").value);if(!c)throw Error("Vælg controller");const expected=c.remote_controller_id||c.controller_id;
 const s=c.id==="local"?await req("api/devices"):await req("api/lab/remote",{registry_id:c.id,controller_id:expected,operation:"snapshot"});if(s.controller_id!==expected)throw Error("Controller-ID ændret");
 let info=null,backups=null;if(page!=="energy"&&c.id==="local"){try{info=await req("api/admin/status");if(info.controller_id!==expected)info=null;}catch(e){}}
 if(page==="maintenance"&&c.id==="local"){try{const x=await req("api/backups");backups=x.backups||[];}catch(e){}}
 if(page==="energy")renderEnergy(s);else if(page==="emergency")renderEmergency(s,info);else renderMaintenance(s,info,backups);
 last={controller_id:expected,page,gear:s.gear||[],info,backups};$("download").disabled=false;$("status").textContent="Opdateret "+new Date().toLocaleTimeString("da-DK")+" · "+c.name;
 }catch(e){$("status").textContent=e.message;}finally{busy=false;$("target").disabled=false;$("refresh").disabled=false;}}
$("target").onchange=()=>{localStorage.setItem("pulsar_active_controller",$("target").value);load();};$("refresh").onclick=load;
$("download").onclick=()=>{if(!last)return;const u=URL.createObjectURL(new Blob([JSON.stringify(last,null,2)],{type:"application/json"})),a=el("a");a.href=u;a.download="pulsar-"+page+".json";a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);};
(async()=>{try{const x=await req("api/controllers");controllers=[x.local,...(x.controllers||[])].filter(Boolean);for(const c of controllers)$("target").append(new Option(c.name||c.id,c.id));const saved=localStorage.getItem("pulsar_active_controller");if(controllers.some(c=>c.id===saved))$("target").value=saved;await load();}catch(e){$("status").textContent=e.message;}})();
</script></body></html>'''
def page_for(key):
    if key not in ("energy","emergency","maintenance"):raise ValueError("Invalid page")
    return apply(PAGE.replace("__PAGE__",key),key)
