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
s=s.replace("0.12.0","0.25.0").replace("Pulsar DALI Control 0.25.0","Pulsar DALI All-in-One 0.25.0")
change('    remote_api_enabled: bool = False','    remote_api_enabled: bool = False\n    local_dali_enabled: bool = True')
change('        led_enabled=bool(data.get("led_enabled", True)),','        led_enabled=bool(data.get("led_enabled", True)) and bool(data.get("local_dali_enabled", True)),')
change('        remote_api_enabled=bool(data.get("remote_api_enabled", False)),','        remote_api_enabled=bool(data.get("remote_api_enabled", False)),\n        local_dali_enabled=bool(data.get("local_dali_enabled", True)),')
change('    "/api/backups",\n    "/api/commissioning",','    "/api/backups",\n    "/api/admin/clock",\n    "/api/events",\n    "/api/commissioning",')
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
change('    try:\n        while RUNNING:\n            time.sleep(0.25)\n    finally:\n        server.shutdown()', '    from mqtt_bridge import Bridge\n    bridge = Bridge(controller, settings, log, load_controller_registry, remote_controller_request)\n    server.mqtt_bridge = bridge\n    bridge.start()\n    from maintenance import Worker\n    maintenance_worker=Worker(controller,log)\n    maintenance_worker.start()\n    from discovery import Discovery\n    discovery_worker=Discovery(controller,settings,log)\n    server.discovery_worker=discovery_worker\n    discovery_worker.start()\n    from clock_sync import Clock\n    clock_worker=Clock(controller,load_controller_registry,remote_controller_request,log)\n    server.clock_worker=clock_worker\n    clock_worker.start()\n    try:\n        while RUNNING:\n            time.sleep(0.25)\n    finally:\n        clock_worker.stop()\n        discovery_worker.stop()\n        maintenance_worker.stop()\n        bridge.stop()\n        server.shutdown()')
change('        if path.endswith("/api/status") or path == "/api/status":','        if path.endswith("/api/mqtt/status"):\n            bridge = getattr(self.server, "mqtt_bridge", None)\n            self._json({"ok": True, **(bridge.status() if bridge else {"connected": False})})\n            return\n        if path.endswith("/api/status") or path == "/api/status":')
change('  <div id="banner" class="banner"></div>','  <section class="card"><b>Home Assistant / MQTT</b><div class="subtle" id="mqttStatus">Indlæser…</div><script>async function mqttStatus(){try{const r=await fetch("api/mqtt/status");const j=await r.json();document.getElementById("mqttStatus").textContent=(j.enabled?(j.connected?"Forbundet":"Ikke forbundet"):"Deaktiveret")+" · "+(j.controllers||0)+" controllere · "+(j.entities||0)+" entities"+(j.error?" · "+j.error:"");}catch(e){document.getElementById("mqttStatus").textContent="Status utilgængelig";}}mqttStatus();setInterval(mqttStatus,5000);</script></section>\n  <div id="banner" class="banner"></div>')
# v0.14 hardware profiles (settings resolved before opening UART/I2C).
change('    local_dali_enabled: bool = True','    local_dali_enabled: bool = True\n    hardware_profile: str = "manual"\n    hardware_requested: str = "manual"\n    hardware_board: str = ""\n    hardware_error: str = ""\n    led_active_high: bool = True')
change('    return Settings(\n','    from hardware_profile import resolve\n    data = resolve(data)\n    log("Hardware profile: " + data["hardware_profile"] + " (" + data["hardware_board"] + ")")\n    if data["hardware_error"]:\n        log("WARNING: " + data["hardware_error"] + "; local DALI disabled")\n    return Settings(\n')
change('        local_dali_enabled=bool(data.get("local_dali_enabled", True)),','        local_dali_enabled=bool(data.get("local_dali_enabled", True)),\n        hardware_profile=data["hardware_profile"],\n        hardware_requested=data["hardware_requested"],\n        hardware_board=data["hardware_board"],\n        hardware_error=data["hardware_error"],\n        led_active_high=bool(data.get("led_active_high", True)),')
change('    log("Fixed hardware mapping: DALI1=ttyAMA3, DALI2=ttyAMA4, DALI3=ttyAMA5")','    log("Local DALI mapping: " + str(settings.devices) if settings.local_dali_enabled else "Local DALI disabled")')
change('                self.bus.write_byte_data(settings.mcp_address, OLATB, current & ~DALI_LED_MASK)\n                self.bus.write_byte_data(settings.mcp_address, GPPUB, CM4_IODIRB)\n                self.bus.write_byte_data(settings.mcp_address, IODIRB, CM4_IODIRB)','                idle = current & ~DALI_LED_MASK if settings.led_active_high else current | DALI_LED_MASK\n                self.bus.write_byte_data(settings.mcp_address, OLATB, idle)\n                direction = self.bus.read_byte_data(settings.mcp_address, IODIRB)\n                self.bus.write_byte_data(settings.mcp_address, IODIRB, direction & ~DALI_LED_MASK)')
change('current & ~(1 << bit))','(current & ~(1 << bit)) if self.settings.led_active_high else (current | (1 << bit)))')
change('current | (1 << bit))\n            timer','(current | (1 << bit)) if self.settings.led_active_high else (current & ~(1 << bit)))\n            timer')
change('current & ~DALI_LED_MASK)\n        except Exception as exc:\n            log(f"WARNING: could not restore DALI LEDs LOW','(current & ~DALI_LED_MASK) if self.settings.led_active_high else (current | DALI_LED_MASK))\n        except Exception as exc:\n            log(f"WARNING: could not restore DALI LEDs idle state')
change('f"MCP23017 0x{settings.mcp_address:02X}, active-high B5/B3/B1; idle LOW."','f"MCP23017 0x{settings.mcp_address:02X}, active-high={settings.led_active_high}, B5/B3/B1."')
change('                "generation": self.scan_generation,\n                "scan_running": self.scan_running,','                "generation": self.scan_generation,\n                "hardware_profile": self.settings.hardware_profile,\n                "hardware_requested": self.settings.hardware_requested,\n                "hardware_board": self.settings.hardware_board,\n                "hardware_error": self.settings.hardware_error,\n                "local_dali_enabled": self.settings.local_dali_enabled,\n                "i2c_bus": self.settings.i2c_bus,\n                "scan_running": self.scan_running,')
change('self._json({"ok": True, **(bridge.status() if bridge else {"connected": False})})','self._json({"ok": True, "hardware_profile": ctl.settings.hardware_profile, "hardware_error": ctl.settings.hardware_error, **(bridge.status() if bridge else {"connected": False})})')
change('+(j.error?" · "+j.error:"");','+(j.error?" · "+j.error:"")+" · Hardware: "+(j.hardware_profile||"unknown")+(j.hardware_error?" · "+j.hardware_error:"");')

# Test Lab is deliberately query-only; advanced write prototype is not loaded.
change('    "/api/gear/control",','    "/api/lab/run",\n    "/api/gear/control",')
change('class Handler(BaseHTTPRequestHandler):','import test_lab\n\ntest_lab.install(SerialBusTransport, encode_request)\nimport dashboards\ndashboards.install(SerialBusTransport)\nimport advanced\nadvanced.install(PulsarDali)\n\nclass Handler(BaseHTTPRequestHandler):')
change('        if path.endswith("/api/mqtt/status"):','        if path.endswith("/api/admin/clock"):\n            worker=getattr(self.server,"clock_worker",None)\n            if worker:\n                self._json(worker.status())\n            else:\n                self._json({"ok":True,"controller_id":ctl.controller_id,"system_utc":time.time(),"reference_controller_id":"","mode":"system"})\n            return\n        if path.endswith("/api/discovery"):\n            if getattr(self.server, "is_remote", False):\n                self._json({"ok": False, "error": "not found"}, 404)\n                return\n            worker=getattr(self.server,"discovery_worker",None)\n            self._json(worker.status() if worker else {"ok":True,"enabled":False,"candidates":[]})\n            return\n        if path.endswith("/api/admin/status"):\n            if getattr(self.server, "is_remote", False):\n                self._json({"ok": False, "error": "not found"}, 404)\n                return\n            self._json(dashboards.local_info(ctl))\n            return\n        if path.endswith(("/energy", "/emergency", "/maintenance")):\n            if getattr(self.server, "is_remote", False):\n                self._json({"ok": False, "error": "not found"}, 404)\n                return\n            body = dashboards.page_for(path.rsplit("/", 1)[-1]).encode("utf-8")\n            self.send_response(HTTPStatus.OK)\n            self.send_header("Content-Type", "text/html; charset=utf-8")\n            self.send_header("Cache-Control", "no-store")\n            self.send_header("Content-Length", str(len(body)))\n            self.end_headers()\n            self.wfile.write(body)\n            return\n        if path.endswith(("/testlab", "/configuration")):\n            if getattr(self.server, "is_remote", False):\n                self._json({"ok": False, "error": "not found"}, 404)\n                return\n            body = test_lab.page_for(path.endswith("/configuration")).encode("utf-8")\n            self.send_response(HTTPStatus.OK)\n            self.send_header("Content-Type", "text/html; charset=utf-8")\n            self.send_header("Cache-Control", "no-store")\n            self.send_header("Content-Length", str(len(body)))\n            self.end_headers()\n            self.wfile.write(body)\n            return\n        if path.endswith("/api/mqtt/status"):')
change('            data = self._read_json()\n','            data = self._read_json()\n            if path.endswith("/api/lab/run"):\n                self._json(test_lab.run(ctl, data))\n                return\n            if path.endswith("/api/lab/remote"):\n                if getattr(self.server, "is_remote", False):\n                    self._json({"ok": False, "error": "not found"}, 404)\n                    return\n                rid = data.get("registry_id")\n                with CONTROLLERS_LOCK:\n                    item = dict(load_controller_registry().get(rid, {}))\n                expected = data.get("controller_id")\n                if not expected or item.get("remote_controller_id") != expected:\n                    raise ValueError("Unknown or changed remote identity")\n                operation = data.get("operation")\n                if operation == "clock":\n                    result = remote_controller_request(item, "GET", "/api/admin/clock", timeout=10)\n                elif operation == "snapshot":\n                    result = remote_controller_request(item, "GET", "/api/devices", timeout=10)\n                elif operation == "run":\n                    test = data.get("test")\n                    if not isinstance(test, dict) or test.get("controller_id") != expected:\n                        raise ValueError("Remote test identity mismatch")\n                    result = remote_controller_request(item, "POST", "/api/lab/run", test, timeout=60)\n                else:\n                    raise ValueError("Unknown lab operation")\n                if result.get("controller_id") != expected:\n                    raise ValueError("Remote controller identity mismatch")\n                self._json(result)\n                return\n')
# Common shell for all existing pages. Runtime applies only to HTML.
change('import test_lab\n\ntest_lab.install', 'import ui_layout\nPAGE=ui_layout.apply(PAGE,"overview")\nCOMMISSIONING_PAGE=ui_layout.apply(COMMISSIONING_PAGE,"commissioning")\nCONTROLLERS_PAGE=ui_layout.apply(CONTROLLERS_PAGE,"controllers")\nREMOTE_PAGE=ui_layout.apply(REMOTE_PAGE,"remote")\nDIAGNOSTICS_PAGE=ui_layout.apply(DIAGNOSTICS_PAGE,"diagnostics")\nimport test_lab\n\ntest_lab.install')


# Pairing is separate from the remote data-plane allowlists.
change('import test_lab\n\ntest_lab.install', 'import pairing\nimport test_lab\n\ntest_lab.install')
change('if not self.server.remote_token or not hmac.compare_digest(supplied, expected):','if not pairing.service(self).authorized(supplied, str(self.server.remote_token or ""), self.server.settings.remote_legacy_token_enabled, client):')
change('if __name__ == "__main__":\n    raise SystemExit(main())','pairing.install(Handler, globals())\n\nif __name__ == "__main__":\n    raise SystemExit(main())')


# Exclusive master, and discovery-based verified address recovery.
change('    remote_api_enabled: bool = False','    remote_api_enabled: bool = False\n    remote_legacy_token_enabled: bool = False')
change('        remote_api_enabled=bool(data.get("remote_api_enabled", False)),','        remote_api_enabled=bool(data.get("remote_api_enabled", False)),\n        remote_legacy_token_enabled=bool(data.get("remote_legacy_token_enabled", False)),')
change('import pairing\nimport test_lab','import pairing\nimport reconnect\nimport test_lab')
change('    discovery_worker.start()\n    from clock_sync import Clock','    discovery_worker.start()\n    reconnect_worker=reconnect.Reconnect(discovery_worker,load_controller_registry,save_controller_registry,CONTROLLERS_LOCK,remote_controller_request,log)\n    reconnect_worker.start()\n    from clock_sync import Clock')
change('        clock_worker.stop()\n        discovery_worker.stop()','        clock_worker.stop()\n        reconnect_worker.stop()\n        discovery_worker.stop()')
change('        "remote_controller_id": item.get("remote_controller_id"),','        "remote_controller_id": item.get("remote_controller_id"),\n        "paired": bool(item.get("paired")),')
# Do not overwrite an address or revive a deleted registry entry when a call completes.
change('def sanitise_controller(controller_id: str, item: dict) -> dict:', '''def commit_controller_status(cid, original, result):
    with CONTROLLERS_LOCK:
        registry = load_controller_registry()
        current = registry.get(cid)
        if current is None or reconnect.identity(current) != reconnect.identity(original):
            return
        for key in ("last_ok", "last_error", "firmware", "remote_controller_id"):
            if key in result:
                if key == "remote_controller_id" and current.get(key) and result[key] != current[key]:
                    continue
                current[key] = result[key]
        save_controller_registry(registry)

def sanitise_controller(controller_id: str, item: dict) -> dict:''')
change('                    item = dict(registry[cid])\n                item["name"]', '                    item = dict(registry[cid])\n                original = dict(item)\n                item["name"]')
change('                    registry[cid] = item\n                    save_controller_registry(registry)\n                self._json({"ok": True, "controller": sanitise_controller(cid, item), "test": test})','                    if cid not in registry or reconnect.identity(registry[cid]) != reconnect.identity(original):\n                        raise ValueError("Controller changed; refresh and retry")\n                    if original.get("remote_controller_id") and test.get("controller_id") != original["remote_controller_id"]:\n                        raise ValueError("Controller identity mismatch")\n                    registry[cid] = item\n                    save_controller_registry(registry)\n                self._json({"ok": True, "controller": sanitise_controller(cid, item), "test": test})')
change('                    item = dict(registry[cid])\n                try:\n                    test = test_remote_controller(item)','                    item = dict(registry[cid])\n                original = dict(item)\n                try:\n                    test = test_remote_controller(item)')
change('                    item = dict(registry[cid])\n                parsed_target','                    item = dict(registry[cid])\n                original = dict(item)\n                parsed_target')
old_status='                    with CONTROLLERS_LOCK:\n                        registry = load_controller_registry(); registry[cid] = item; save_controller_registry(registry)\n                    raise\n                with CONTROLLERS_LOCK:\n                    registry = load_controller_registry(); registry[cid] = item; save_controller_registry(registry)'
new_status='                    commit_controller_status(cid, original, item)\n                    raise\n                commit_controller_status(cid, original, item)'
change(old_status,new_status)
change(old_status,new_status)
# Reject duplicate manually added controllers; existing registry IDs remain stable.
change('                    registry = load_controller_registry()\n                    registry[cid] = item\n                    save_controller_registry(registry)\n                log(f"Central management: added', '                    registry = load_controller_registry()\n                    if not item.get("remote_controller_id") or item["remote_controller_id"] == ctl.controller_id or any(x.get("remote_controller_id") == item["remote_controller_id"] for x in registry.values()):\n                        raise ValueError("Controller already registered or invalid identity")\n                    registry[cid] = item\n                    save_controller_registry(registry)\n                log(f"Central management: added')
# Never silently adopt a different identity returned by an endpoint.
change('        return payload\n    finally:', '        if controller.get("remote_controller_id") and payload.get("controller_id") and payload["controller_id"] != controller["remote_controller_id"]:\n            raise ValueError("Remote controller identity mismatch")\n        return payload\n    finally:')


# Exclusive topology: master OR subordinate, never both.
change('    server = Server(', '    pairing.configure(controller.controller_id,load_controller_registry,CONTROLLERS_LOCK,settings.remote_legacy_token_enabled)\n    server = Server(')
change('def remote_controller_request(controller: dict, method: str, path: str, data: dict | None = None, timeout: float = 30.0) -> dict:', '''def remote_controller_request(controller: dict, method: str, path: str, data: dict | None = None, timeout: float = 30.0) -> dict:
    with pairing.current().outbound():
        return _remote_controller_request(controller,method,path,data,timeout)

def _remote_controller_request(controller: dict, method: str, path: str, data: dict | None = None, timeout: float = 30.0) -> dict:''')
change('Discovery(controller,settings,log)', 'Discovery(controller,settings,log,pairing.current().role)')


change('    maintenance_worker.start()\n    from discovery import Discovery','    maintenance_worker.start()\n    from button_bindings import Worker as ButtonWorker\n    button_worker=ButtonWorker(controller,log)\n    button_worker.start()\n    from discovery import Discovery')
change('        maintenance_worker.stop()\n        bridge.stop()','        button_worker.stop()\n        maintenance_worker.stop()\n        bridge.stop()')


change('advanced.install(PulsarDali)\n\nclass Handler', 'advanced.install(PulsarDali)\nimport local_automation\nimport automation_ui\nlocal_automation.install(PulsarDali)\n\nclass Handler')
change('    bridge.start()\n    from maintenance import Worker','    controller.automation_engine=local_automation.Engine(controller,log)\n    controller.automation_engine.start()\n    bridge.start()\n    from maintenance import Worker')
change('        button_worker.stop()\n        maintenance_worker.stop()', '        controller.automation_engine.stop()\n        button_worker.stop()\n        maintenance_worker.stop()')
change('        if path.endswith(("/testlab", "/configuration")):', '''        if path.endswith("/automation"):
            if getattr(self.server,"is_remote",False):
                self._json({"ok":False,"error":"not found"},404)
                return
            body=automation_ui.page().encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type","text/html; charset=utf-8")
            self.send_header("Cache-Control","no-store")
            self.send_header("Content-Length",str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path.endswith(("/testlab", "/configuration")):''')


change('import automation_ui\nlocal_automation.install', 'import automation_ui\nimport hardware_diagnostics\nimport hardware_ui\nlocal_automation.install')
change('    "/api/admin/clock",', '    "/api/admin/clock",\n    "/api/admin/hardware",')
change('        if path.endswith("/api/admin/clock"):', '''        if path.endswith("/api/admin/hardware"):
            worker=getattr(ctl,"hardware_monitor",None)
            self._json(worker.status() if worker else {"ok":True,"controller_id":ctl.controller_id,"pending":True})
            return
        if path.endswith("/api/admin/clock"):''')
change('                elif operation == "snapshot":', '''                elif operation == "hardware":
                    result = remote_controller_request(item, "GET", "/api/admin/hardware", timeout=10)
                elif operation == "snapshot":''')
change('        if path.endswith("/automation"):', '''        if path.endswith("/hardware"):
            if getattr(self.server,"is_remote",False):
                self._json({"ok":False,"error":"not found"},404)
                return
            body=hardware_ui.page().encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type","text/html; charset=utf-8")
            self.send_header("Cache-Control","no-store")
            self.send_header("Content-Length",str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path.endswith("/automation"):''')
change('    controller.automation_engine.start()\n    bridge.start()', '    controller.automation_engine.start()\n    controller.hardware_monitor=hardware_diagnostics.Monitor(controller,log)\n    controller.hardware_monitor.start()\n    from front_panel import Panel\n    controller.front_panel=Panel(controller,log)\n    controller.front_panel.start()\n    bridge.start()')
change('        controller.automation_engine.stop()', '        controller.front_panel.stop()\n        controller.hardware_monitor.stop()\n        controller.automation_engine.stop()')

compile(s,"pulsar_dali_control.py","exec")
out=pathlib.Path(sys.argv[1])
out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(s,encoding="utf-8")

