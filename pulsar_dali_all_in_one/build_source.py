"""Reconstruct pinned v0.12 source and apply AIO changes."""
import base64,gzip,hashlib,pathlib,sys
root=pathlib.Path(__file__).parent
raw=gzip.decompress(base64.b64decode(b"".join((root/"base"/f"pulsar.py.gz.b64.{i}").read_bytes() for i in range(7)),validate=True))
assert hashlib.sha256(raw).hexdigest()=="f98126a642481ec5af67cdbc02efc125e518984627b6e4544af0f8d9f44ff11d","Unexpected source"
s=raw.decode()
def change(old,new):
    global s
    if old not in s: raise RuntimeError("Missing patch anchor: "+repr(old))
    s=s.replace(old,new,1)
s=s.replace("0.12.0","0.13.0").replace("Pulsar DALI Control 0.13.0","Pulsar DALI All-in-One 0.13.0")
change('    remote_api_enabled: bool = False','    remote_api_enabled: bool = False\n    local_dali_enabled: bool = True')
change('        led_enabled=bool(data.get("led_enabled", True)),','        led_enabled=bool(data.get("led_enabled", True)) and bool(data.get("local_dali_enabled", True)),')
change('        remote_api_enabled=bool(data.get("remote_api_enabled", False)),','        remote_api_enabled=bool(data.get("remote_api_enabled", False)),\n        local_dali_enabled=bool(data.get("local_dali_enabled", True)),')
change('    "/api/backups",\n    "/api/commissioning",','    "/api/backups",\n    "/api/events",\n    "/api/commissioning",')
change('        self._load_cache()\n        self.transports = {','        if settings.local_dali_enabled:\n            self._load_cache()\n        self.operation_lock = threading.RLock()\n        self.transports = {')
change('            for bus in (1, 2, 3)\n        }\n\n    def _load_cache','            for bus in ((1, 2, 3) if settings.local_dali_enabled else ())\n        }\n\n    def _load_cache')
change('        with self.locks[bus_number]:\n            sequence = self._next_sequence(bus_number)','        if not self.settings.local_dali_enabled:\n            raise RuntimeError("Local DALI disabled")\n        with self.locks[bus_number]:\n            sequence = self._next_sequence(bus_number)')
change('    for bus_number in (1, 2, 3):\n        try:\n            result = controller.gver','    for bus_number in ((1, 2, 3) if settings.local_dali_enabled else ()):\n        try:\n            result = controller.gver')
change('def background_worker(controller: PulsarDali, settings: Settings):\n','def background_worker(controller: PulsarDali, settings: Settings):\n    if not settings.local_dali_enabled:\n        return\n')
change('                    item["online"] = True\n                    item["control_gear_failure"]','                    item["online"] = status is not None or actual is not None\n                    item["control_gear_failure"]')
change('                    device["online"] = True\n                    device["last_seen"]','                    device["online"] = status is not None or raw_value is not None\n                    device["last_seen"]')
change('        if not (path == "/api/status" or path.startswith("/api/")):','        allowed = REMOTE_PROXY_ALLOWED_GET if self.command == "GET" else REMOTE_PROXY_ALLOWED_POST if self.command == "POST" else set()\n        if path not in allowed:')
change("PAGE = r'''",'''def _serialise_operation(method):
    from functools import wraps
    @wraps(method)
    def wrapped(self,*args,**kwargs):
        if not self.settings.local_dali_enabled:
            raise RuntimeError("Local DALI disabled")
        with self.operation_lock:
            return method(self,*args,**kwargs)
    return wrapped

for _operation in (
    "gver","scan","scan_bus","scan_control_devices_bus","refresh_states",
    "set_level","set_config","set_groups","identify","set_group_level",
    "set_scene_level","broadcast_level","broadcast_command","broadcast_scene",
    "set_input_config","configure_recommended_event_profile","detect_address_conflicts",
    "change_short_address","clear_short_address","commission_unaddressed","repair_address_conflict",
):
    setattr(PulsarDali,_operation,_serialise_operation(getattr(PulsarDali,_operation)))

PAGE = r'''+ "'''")
change('    try:\n        while RUNNING:\n            time.sleep(0.25)\n    finally:\n        server.shutdown()', '    from mqtt_bridge import Bridge\n    bridge = Bridge(controller, settings, log, load_controller_registry, remote_controller_request)\n    server.mqtt_bridge = bridge\n    bridge.start()\n    try:\n        while RUNNING:\n            time.sleep(0.25)\n    finally:\n        bridge.stop()\n        server.shutdown()')
change('        if path.endswith("/api/status") or path == "/api/status":','        if path.endswith("/api/mqtt/status"):\n            bridge = getattr(self.server, "mqtt_bridge", None)\n            self._json({"ok": True, **(bridge.status() if bridge else {"connected": False})})\n            return\n        if path.endswith("/api/status") or path == "/api/status":')
change('  <div id="banner" class="banner"></div>','  <section class="card"><b>Home Assistant / MQTT</b><div class="subtle" id="mqttStatus">Indlæser…</div><script>async function mqttStatus(){try{const r=await fetch("api/mqtt/status");const j=await r.json();document.getElementById("mqttStatus").textContent=(j.enabled?(j.connected?"Forbundet":"Ikke forbundet"):"Deaktiveret")+" · "+(j.controllers||0)+" controllere · "+(j.entities||0)+" entities"+(j.error?" · "+j.error:"");}catch(e){document.getElementById("mqttStatus").textContent="Status utilgængelig";}}mqttStatus();setInterval(mqttStatus,5000);</script></section>\n  <div id="banner" class="banner"></div>')
compile(s,"pulsar_dali_control.py","exec")
out=pathlib.Path(sys.argv[1])
out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(s,encoding="utf-8")
