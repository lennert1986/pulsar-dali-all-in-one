"""Shared web layout; existing page IDs and command handlers are preserved."""
import re
from html import escape
PAGES=(
    ("overview","./","Oversigt","Busser, armaturer, grupper og scener"),
    ("configuration","configuration","Konfiguration","Indstil armaturer, sensorer og avancerede funktioner"),
    ("energy","energy","Energi","D4i-målinger og dækningsgrad"),
    ("emergency","emergency","Nødbelysning","Registreret nødlysstatus og kommandohistorik"),
    ("maintenance","maintenance","Vedligeholdelse","Backup, ressourcer og kommunikation"),
    ("commissioning","commissioning","Commissioning","Adresser, konflikter og konfigurationsbackups"),
    ("controllers","controllers","Controllers","Administrér lokale og eksterne controllere"),
    ("remote","remote","Remote","Sikker HTTPS-adgang fra andre controllere"),
    ("diagnostics","diagnostics","Diagnostik","Teknisk status og rå API-data"),
    ("testlab","testlab","Test Lab","Læsende DALI-tests og telegramlog"),
)
CSS=r"""
:root{color-scheme:light dark;--bg:var(--primary-background-color,#f3f5f8);--card:var(--card-background-color,#fff);--text:var(--primary-text-color,#202b3c);--muted:var(--secondary-text-color,#58677a);--border:var(--divider-color,#dce2e9);--accent:var(--primary-color,#027ea8);--success:#268343;--error:#bb3030;--radius:12px;--shadow:none;font-family:Roboto,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
@media(prefers-color-scheme:dark){:root{--bg:var(--primary-background-color,#151a22);--card:var(--card-background-color,#202732);--text:var(--primary-text-color,#edf0f5);--muted:var(--secondary-text-color,#abb8c8);--border:var(--divider-color,#3b4655);--accent:var(--primary-color,#36b1df);--success:#66c98a;--error:#ff9a94}}
*{box-sizing:border-box}html{scrollbar-gutter:stable;min-width:0}body{margin:0;background:var(--bg);color:var(--text);font-size:15px;line-height:1.45}
body .wrap,body main{width:100%;max-width:1440px;margin:0 auto;padding:20px 24px 36px;min-width:0}
.pulsar-shell{margin-bottom:20px}.pulsar-brand{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px;min-height:44px}.pulsar-brand-left{display:flex;align-items:center;gap:12px;min-width:0}.pulsar-logo{width:40px;height:40px;flex:none;border-radius:10px;background:var(--accent);color:white;display:grid;place-items:center;font-size:21px;font-weight:800}.pulsar-name{font-size:17px;font-weight:700;line-height:1.3}.pulsar-edition{font-size:12px;color:var(--muted)}.pulsar-version{font-size:12px;color:var(--muted);white-space:nowrap;padding:5px 9px;border:1px solid var(--border);border-radius:8px;font-variant-numeric:tabular-nums}
nav.pulsar-nav{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:4px;padding:5px;background:var(--card);border:1px solid var(--border);border-radius:12px;margin:0;align-items:stretch}
nav.pulsar-nav a{min-width:0;min-height:42px;display:flex;align-items:center;justify-content:center;text-align:center;line-height:1.2;padding:8px 4px;font-size:13px;font-weight:600;white-space:normal;border:1px solid transparent;border-radius:8px;background:transparent;color:var(--muted);text-decoration:none}
nav.pulsar-nav a:hover{border-color:var(--border);color:var(--text)}nav.pulsar-nav a[aria-current=page]{background:var(--accent);color:#fff;border-color:var(--accent)}nav.pulsar-nav a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.pulsar-heading{display:block;margin:0 0 20px;min-width:0}.pulsar-heading h1{margin:0;font-size:clamp(23px,3vw,30px);line-height:1.25;font-weight:700}.pulsar-heading p{margin:5px 0 0;font-size:14px;color:var(--muted)}
.card,main>section{min-width:0;background:var(--card);border:1px solid var(--border);border-radius:var(--radius);box-shadow:none;padding:18px;margin:0 0 16px}
body h2,.card h2,main h2{font-size:18px;font-weight:650;line-height:1.3;margin:0 0 10px}body h3,.card h3{font-size:16px;line-height:1.3;margin:0 0 8px}
.subtle,.muted,.hint,.meta{color:var(--muted);font-size:13px;opacity:1}.grid,.fields,.form,.form-grid,.statgrid,.bus-meta{min-width:0;gap:12px}.grid>*{min-width:0}.grid .card{margin-bottom:0}.grid{margin-bottom:16px}.cols-2{grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr))}.cols-3{grid-template-columns:repeat(auto-fit,minmax(min(100%,295px),1fr))}.cols-4{grid-template-columns:repeat(auto-fit,minmax(min(100%,155px),1fr))}.fields{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,195px),1fr));align-items:start}.fields>*,.field,.actions>*{min-width:0}.field label,.fields label{font-size:13px;font-weight:600;color:var(--muted)}.fields label{display:flex;flex-direction:column;gap:6px}.actions{display:flex;flex-wrap:wrap;gap:8px;align-items:center}.card-head,.section-title{gap:12px;align-items:center}
button,input,select,textarea,.field input{font:inherit;border:1px solid var(--border);border-radius:8px;background:var(--card);color:var(--text);min-height:40px;padding:8px 11px;max-width:100%}input:not([type=checkbox]):not([type=radio]),select,textarea{width:100%}input[type=checkbox],input[type=radio]{width:17px;height:17px;min-height:0;padding:0;flex:none;accent-color:var(--accent)}button{cursor:pointer;white-space:normal;font-weight:550}button.primary{background:var(--accent);border-color:var(--accent);color:#fff}button:disabled,select:disabled,input:disabled,textarea:disabled{opacity:.55;cursor:not-allowed}button.small{min-height:34px;padding:5px 10px;font-size:13px}select#controllerSelect{width:min(360px,100%);min-width:0!important}.check{display:flex;flex-direction:row;align-items:flex-start;gap:8px;font-size:13px;line-height:1.45}.check input{margin-top:2px}
.table-wrap,.scroll,#conflicts,#backups{max-width:100%;overflow:auto;overscroll-behavior-inline:contain}table{width:100%;border-collapse:collapse;font-size:13px}th,td{padding:10px 9px;border-bottom:1px solid var(--border);vertical-align:middle;overflow-wrap:anywhere}th{font-size:12px;color:var(--muted);font-weight:650;background:var(--bg);text-align:left}tbody tr:last-child td{border-bottom:0}tbody tr:hover{background:rgba(127,127,127,.045)}.mono,.log,pre{overflow-wrap:anywhere;white-space:pre-wrap;max-width:100%}.stat .value{font-variant-numeric:tabular-nums}.pulsar-state{min-height:42px;padding:10px 12px;border:1px solid var(--border);border-radius:8px;background:var(--bg);margin:14px 0 0;font-size:13px;overflow-wrap:anywhere}.pulsar-state[data-state=error]{border-color:var(--error);color:var(--error)}.pulsar-state[data-state=success]{border-color:var(--success);color:var(--success)}
.pulsar-args{margin-top:14px;padding:14px;border:1px solid var(--border);border-radius:10px;background:var(--bg)}.pulsar-args:empty{display:none}.pulsar-args .fields{margin-top:0}.pulsar-args input,.pulsar-args select{background:var(--card)}.pulsar-result-key{width:34%;font-weight:600}.pulsar-result-value{white-space:pre-wrap;font-family:ui-monospace,monospace;font-size:12px}.pulsar-metrics{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0 12px}.pulsar-metrics span{padding:5px 9px;border:1px solid var(--border);border-radius:6px;font-size:13px}.pass{color:var(--success)}.error{color:var(--error)}.no_reply,.skipped,.unknown{color:var(--muted)}
.settings-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,360px),1fr));gap:12px;margin:12px 0}.settings-panel{padding:14px;border:1px solid var(--border);border-radius:10px;background:var(--card);margin:0;min-width:0}.settings-panel h3{margin:0 0 10px}.setting-row{display:grid;grid-template-columns:minmax(110px,1fr) minmax(85px,1fr) auto;align-items:center;gap:8px;padding:8px 0;border-top:1px solid var(--border)}.setting-row label{font-size:13px;font-weight:550}.setting-row button{min-height:36px;font-size:13px}.setting-row input,.setting-row select{min-width:0;width:100%;min-height:36px}.device-options{align-items:start}.device-option-group{align-self:start}.device-option-buttons button{min-height:34px}.settings-panel+ .muted{margin:8px 0}@media(max-width:420px){.setting-row{grid-template-columns:minmax(0,1fr) 80px auto}.setting-row label{overflow-wrap:anywhere}}
.color-control{display:flex;flex-direction:column;gap:8px;grid-column:1/-1;padding:12px;border:1px solid var(--border);border-radius:8px}.color-control input[type=color]{height:46px;padding:4px;cursor:pointer}.temperature-gradient{height:12px;border-radius:8px;background:linear-gradient(90deg,#ffb35f,#fff3d4,#e4efff,#a6c8ff)}.color-labels{font-size:12px;color:var(--muted)}.event-bits{display:grid;grid-template-columns:repeat(auto-fit,minmax(85px,1fr));gap:7px;margin-top:12px}.event-bits label{display:flex;flex-direction:row;align-items:center;gap:6px;border:1px solid var(--border);border-radius:6px;padding:6px;font-size:12px}
#deviceOverview{margin:18px 0;padding:16px;border:1px solid var(--border);border-radius:12px;background:var(--bg)}#deviceOverview h2{margin-bottom:4px}#deviceOverview p{margin:0 0 12px}.device-facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,145px),1fr));gap:10px}.device-facts>div{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:10px;min-width:0}.device-facts small{display:block;color:var(--muted);font-size:12px}.device-facts strong{display:block;font-size:14px;overflow-wrap:anywhere;font-variant-numeric:tabular-nums}.device-options{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,210px),1fr));gap:10px;margin:14px 0}.device-option-group{border:1px solid var(--border);border-radius:10px;padding:12px;min-width:0}.device-option-group h3{font-size:13px;color:var(--muted);margin:0 0 8px}.device-option-buttons{display:flex;flex-direction:column;gap:6px}.device-option-buttons button{text-align:left;font-size:13px;min-height:36px}#busTools{border:1px solid var(--border);border-radius:8px;padding:12px;margin:14px 0}#busTools button{margin-top:10px}#busTools summary{cursor:pointer;font-weight:600}
body .banner{position:fixed;z-index:1100;bottom:18px;right:24px;max-width:min(480px,calc(100% - 48px));margin:0;box-shadow:0 4px 20px #0002;background:var(--card)}body .modal{max-width:860px}body [hidden]{display:none!important}
@media(max-width:1050px){nav.pulsar-nav{grid-template-columns:repeat(4,minmax(0,1fr))}}
@media(max-width:600px){body .wrap,body main{padding:14px 12px 24px}.pulsar-brand{min-height:40px}.pulsar-name{font-size:15px}.pulsar-logo{width:34px;height:34px}.pulsar-heading{margin-bottom:14px}nav.pulsar-nav{grid-template-columns:repeat(3,minmax(0,1fr))}nav.pulsar-nav a{min-height:38px;font-size:12px}.card,main>section{padding:13px;margin-bottom:12px}.fields,.form,.form-grid{grid-template-columns:minmax(0,1fr)}.actions{align-items:stretch}.actions button{flex:1 1 auto}body .banner{bottom:12px;right:12px;max-width:calc(100% - 24px)}}
"""
def apply(page,key,version="0.21.4"):
    info=next(x for x in PAGES if x[0]==key)
    nav='<nav class="pulsar-nav" aria-label="Hovedmenu">'+''.join(
        '<a href="'+url+'"'+(' aria-current="page"' if k==key else '')+'>'+label+'</a>'
        for k,url,label,_ in PAGES)+'</nav>'
    shell=('<div class="pulsar-shell"><div class="pulsar-brand"><div class="pulsar-brand-left">'
           '<span class="pulsar-logo" aria-hidden="true">P</span><div><div class="pulsar-name">Pulsar DALI</div>'
           '<div class="pulsar-edition">All-in-One · Vertex G3 / G4</div></div></div>'
           '<span class="pulsar-version">v'+escape(version)+'</span></div>'+nav+'</div>'
           '<header class="pulsar-heading"><h1>'+info[2]+'</h1><p>'+info[3]+'</p></header>')
    if key in ("testlab","configuration","energy","emergency","maintenance"):
        page,n=re.subn(r'<h1>.*?</h1><p[^>]*>.*?</p>\s*<nav[^>]*>.*?</nav>',shell,page,count=1,flags=re.S)
    else:
        page,n=re.subn(r'<div class="header">.*?</nav>\s*</div>',shell,page,count=1,flags=re.S)
    if n!=1: raise RuntimeError("UI header not found: "+key)
    page=page.replace("</head>","<style>"+CSS+"</style></head>",1)
    # Controller changes start a fresh page. The old page's asynchronous
    # multi-step writes never read a new controller ID from the selector.
    page=re.sub(r"function controllerChanged\(\)\{activeController=\$\('controllerSelect'\)\.value;localStorage\.setItem\('pulsar_active_controller',activeController\);(?:loadDevices|loadAll|refreshAll)\(\)\}",
        "function controllerChanged(){localStorage.setItem('pulsar_active_controller',$('controllerSelect').value);location.reload()}",page)
    # Escape remote names by using textContent via Option rather than innerHTML.
    page=re.sub(r's\.innerHTML=(all|a)\.map\(x=>\x60<option value="\$\{x\.id\}">\$\{x\.name\}\$\{x\.id===\x27local\x27\?\x27\x27:\x27 · \x27\+x\.host\}</option>\x60\)\.join\(\x27\x27\)',
        r"s.replaceChildren(...\1.map(x=>new Option(x.name+(x.id==='local'?'':' · '+x.host),x.id)))",page)
    if key=="overview":
        # Jump directly from gear overview into the dedicated configuration
        # form without sending any command.
        page=page.replace("onclick=\"openGearModal(\x24{x.bus},\x24{x.address})\">Rediger</button>",
            "onclick=\"openGearModal(\x24{x.bus},\x24{x.address})\">Rediger</button> <a class=\"pulsar-config-link\" href=\"configuration?bus=\x24{x.bus}&amp;address=\x24{x.address}\">Avanceret</a>")
    if key=="controllers":
        import pairing_ui
        page=pairing_ui.install(page)
    return page
