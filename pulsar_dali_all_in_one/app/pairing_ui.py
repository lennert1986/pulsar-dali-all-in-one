"""Controllers pairing UI; no peer credential in browser."""
import re
PANEL=r'''<section class="card"><h2>Fundne controllere</h2><p class="hint">Klik Tilføj, og godkend på den anden controller. Discovery er endnu ikke verificeret.</p><p id="pairDiscovery" role="status">Indlæser…</p><div id="pairCandidates"></div></section>
<section class="card"><h2>Parring</h2><p class="hint">Åbn Controllers på begge enheder. Tillad parring på modtageren, og sammenlign hele sikkerhedskoden på begge skærme.</p><div class="actions"><button type="button" class="primary" id="pairAllow">Tillad parring i 5 min.</button><button type="button" id="pairClose">Luk parring</button></div><p id="pairWindow"></p><div id="pairMessage" role="status" aria-live="polite"></div><div id="pairIncoming"></div><div id="pairOutgoing"></div></section>
<section class="card"><h2>Controllere med adgang til denne</h2><p class="hint">Parring giver samme styrings- og konfigurationsadgang som eksisterende remote API. Tilbagekald en adgang her.</p><div id="pairGrants"></div></section>
<script>
document.addEventListener("DOMContentLoaded",()=>{
 const get=id=>document.getElementById(id);
 const node=(tag,text)=>{const e=document.createElement(tag);e.textContent=text;return e};
 const msg=t=>{get("pairMessage").textContent=t};
 let busy=false,state=null,discovery=null;
 async function call(action,data){
   const r=await fetch(apiUrl("api/pairing/"+action),{method:data===undefined?"GET":"POST",headers:{"X-Pulsar-Pairing":"1","Content-Type":"application/json"},cache:"no-store",...(data===undefined?{}:{body:JSON.stringify(data)})});
   const j=await r.json();if(!r.ok||!j.ok)throw Error(j.error||"HTTP "+r.status);return j;
 }
 function button(label,fn,primary=false){
   const b=node("button",label);b.type="button";if(primary)b.className="primary";
   b.onclick=async()=>{if(busy)return;busy=true;b.disabled=true;try{await fn()}catch(e){msg(e.message)}finally{busy=false;b.disabled=false;refresh()}};return b;
 }
 function row(root,title,detail){
   const el=document.createElement("div");el.style.cssText="padding:12px 0;border-top:1px solid var(--border);overflow-wrap:anywhere";
   el.append(node("strong",title),node("p",detail));root.append(el);return el;
 }
 function render(){
   const d=get("pairCandidates");d.replaceChildren();
   get("pairDiscovery").textContent=discovery.error||(!discovery.enabled?"Aktiver controller_discovery_enabled i add-on-indstillingerne.":(discovery.candidates||[]).length+" fundne controllere");
   for(const c of discovery.candidates||[]){
     const already=(registry||[]).some(x=>x.remote_controller_id===c.controller_id);
     const pending=state.outgoing.some(x=>x.controller_id===c.controller_id);
     const item=row(d,(c.name||"Pulsar")+" · "+c.host+":"+c.port,"ID: "+c.controller_id+(c.version?" · v"+c.version:"")+" · "+(already?"Tilføjet":"Uverificeret"));
     const b=button(already?"Tilføjet":pending?"Parring i gang":"Tilføj controller",async()=>{
       const name=prompt("Navn på controller",c.name||"Pulsar "+c.host);if(name===null)return;
       await call("begin",{host:c.host,controller_id:c.controller_id,name});msg("Sammenlign koden på begge controllere. Godkend på modtageren, og bekræft derefter her.");
     },true);b.disabled=already||pending;item.append(b);
   }
   get("pairAllow").disabled=!state.listening||state.remaining>0;
   get("pairWindow").textContent=!state.listening?"Remote HTTPS er ikke aktiv. Aktivér remote_api_enabled og genstart.":state.remaining?"Parring åben i "+state.remaining+" sek.":"Parring lukket";
   for(const direction of ["incoming","outgoing"]){
     const root=get(direction==="incoming"?"pairIncoming":"pairOutgoing");root.replaceChildren();
     for(const p of state[direction]){
       const incoming=direction==="incoming";if(incoming&&p.state==="complete")continue;
       const item=row(root,incoming?"Indgående anmodning":"Udgående anmodning",p.host+" · "+p.controller_id+" · "+p.remaining+" sek. · "+p.state);
       const key=node("p",p.code||"Opretter forbindelse…");key.style.cssText="font-size:clamp(17px,4vw,27px);font-weight:700;font-family:monospace;letter-spacing:1px";item.append(key);
       if(incoming&&p.state==="pending"){
         item.append(button("Godkend",async()=>{if(confirm("Er HELE sikkerhedskoden identisk på begge skærme? Dette giver den anden controller fuld remote API-adgang.")){await call("approve",{id:p.id});msg("Godkendt. Bekræft nu på den anden controller.")}},true),
                     button("Afvis",async()=>{await call("deny",{id:p.id});msg("Anmodning afvist.")}));
       }else if(!incoming&&p.state==="pending"){
         item.append(button("Koden matcher – tilføj",async()=>{
           if(!confirm("Er HELE sikkerhedskoden identisk, og er anmodningen godkendt på modtageren?"))return;
           const result=await call("finish",{id:p.id});
           msg(result.state==="complete"?"Controller tilføjet.":result.state==="denied"?"Modtageren afviste anmodningen.":"Afventer godkendelse på modtageren.");
           if(result.state==="complete")await loadControllers();
         },true),button("Annuller",async()=>{await call("cancel",{id:p.id});msg("Anmodning annulleret lokalt.")}));
       }
     }
   }
   const grants=get("pairGrants");grants.replaceChildren();
   if(!state.grants.length)grants.append(node("p","Ingen parrede controllere."));
   for(const g of state.grants){const item=row(grants,g.controller_id,g.host);item.append(button("Tilbagekald adgang",async()=>{if(confirm("Fjern denne controllers adgang?")){await call("revoke",{id:g.id});msg("Adgang tilbagekaldt.")}}))}
 }
 async function refresh(){
   if(busy)return;busy=true;
   try{[state,discovery]=await Promise.all([call("status"),req("api/discovery")]);render()}
   catch(e){get("pairDiscovery").textContent=e.message}
   finally{busy=false}
 }
 get("pairAllow").onclick=async()=>{if(busy)return;busy=true;try{await call("allow",{});msg("Parring åben. Find denne controller fra den anden enhed.")}catch(e){msg(e.message)}finally{busy=false;refresh()}};
 get("pairClose").onclick=async()=>{if(busy)return;busy=true;try{await call("close",{});msg("Parringsvinduet lukket.")}catch(e){msg(e.message)}finally{busy=false;refresh()}};
 refresh();setInterval(refresh,3000);
});
</script>'''
def install(page):
    match=re.search(r'(<section class="card"><h2>Tilføj remote controller</h2>.*?</section>)',page,flags=re.S)
    if not match:raise RuntimeError("Manual controller form not found")
    manual=match.group(1).replace('<section class="card">','<details class="card"><summary>Avanceret – manuel tilføjelse</summary>',1).replace("</section>","</details>",1)
    page=page[:match.start()]+page[match.end():]
    anchor="</div><script>"
    if anchor not in page:raise RuntimeError("Controllers page wrapper missing")
    page=page.replace(anchor,PANEL+manual+anchor,1)
    esc=r'''function pairEscape(v){return String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}'''
    page=page.replace("function card(x){",esc+"\nfunction card(x){",1)
    for expression in ("x.name","x.host","x.port","x.remote_controller_id||'-'","x.last_ok||'-'","x.last_error"):
        page=page.replace("\x24{"+expression+"}","\x24{pairEscape("+expression+")}")
    return page
