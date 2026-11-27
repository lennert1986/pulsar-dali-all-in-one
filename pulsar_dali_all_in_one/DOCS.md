# Configuration

Install and configure Home Assistant's standard MQTT integration and a broker (e.g. Mosquitto). The app requests the Supervisor MQTT service automatically when mqtt_host is empty; otherwise set host, port, user, password and mqtt_tls explicitly. TLS uses normal CA/hostname validation. No broker is bundled. Use a private LAN or TLS for MQTT.

Stop the old Pulsar app before starting this one. Stop/disable the old Pulsar custom integration to avoid duplicate entities. The new app uses separate /data and a separate controller ID; existing configuration, names, areas, automations and entity registry are not migrated automatically.

Local controller: local_dali_enabled=true (default). Remote-only master: local_dali_enabled=false. Add remote controllers via Controllers using token and SHA-256 certificate fingerprint. For a slave, enable remote_api_enabled and explicitly map port 8443 in Network. Disable mqtt_publish_local or mqtt_publish_remote as appropriate. Do not publish the same physical controller twice to one MQTT broker. Only one publisher should control each physical controller per broker. Hardware-free amd64 use is experimental; Supervisor device mapping is not verified on such hosts.

Run scan in web UI (or MQTT Scan buttons). HA creates lights, switches, groups, scenes, pushbutton events, occupancy, relative illuminance and diagnostic/config entities. DT8 color control and unaddressed DALI-2 commissioning are not implemented. Relative illuminance is not lux. Commands to conflicted/offline gear are blocked by the MQTT bridge. During scans the bridge refuses normal commands. Use the original commissioning UI for address changes.

MQTT state and availability retained; events and commands not retained. Broker account needs publish/subscribe rights on the configured discovery prefix and pulsar_dali_aio/#. Treat MQTT credentials as control access. No public MQTT listener is created. If replacing the app or changing broker/prefix, clean old discovery topics on the former broker before removing it.

Experimental: test actual DALI hardware and Home Assistant MQTT discovery before production use.

## Vertex G3 / G4 hardware profiles (0.14.0)

- `hardware_model: auto` uses the device-tree model. Existing non-default UART mappings are treated as manual to preserve upgrades.
- `vertex_g3`: requires one uniquely identifiable FTDI 0403:6011 adapter; maps USB interface numbers 00, 01 and 02 to DALI 1–3, regardless of ttyUSB numbering. I2C bus 0. This FTDI mapping is based on earlier project findings and is not yet verified on a physical G3.
- `vertex_g4`: maps /dev/ttyAMA3, /dev/ttyAMA4, /dev/ttyAMA5; I2C bus 1.
- `remote_only`: no local UART or I2C access; master management and MQTT remain active.
- `manual`: set the existing three dali*_device options and i2c_bus explicitly.

If a profile cannot resolve three distinct present serial devices, local DALI is disabled, with the reason in the startup log and hardware/MQTT status. Select the correct profile or manual ports and restart. No arbitrary USB serial probing or firmware updates are performed. LED polarity can be set via led_active_high (default true for both, based on the original G3 configuration and practical G4 test); GPIO reset/boot pins are untouched. Only DALI LED bits B5/B3/B1 are changed.

G3 requires a working 64-bit Home Assistant OS/Supervised environment with FTDI driver, correct USB/device-tree configuration and optional /dev/i2c-0. Firmware 1.x advanced DALI-2/commissioning compatibility is not verified; test basic GVER and light control first, with auto_scan disabled. The app does not install or modify HAOS. MQTT and TLS remote management remain unchanged. No full_access or protection-mode changes are required by the manifest.

## DALI Test Lab (0.15.0 development preview)

Open Test Lab in the app sidebar web UI. Select the local controller or an enrolled remote, bus, test type and a previously scanned gear/input instance. Both local and remote must run 0.15.0 for remote tests. Start with STM32 communication, then basic and fade queries. DT6/DT8/DT1 capabilities and memory reads require explicit confirmation of temporary DTR/device-type commands. Run on a test bus without another application commissioning it. Test Lab never sends STORE, RESET, addressing or emergency test commands. It reads memory banks 0, 1, 202–207 in chunks of up to 16 bytes; data are raw, not calibrated or decoded D4i measurements. No reply is not proof of unsupported capability. RX is validated response payload, not the original wire frame. Results include TX, sequence, latency, errors and JSON export. Tests have a 25-second budget between telegrams and reject a busy local operation lock. A timeout may leave a temporary DTR value changed, but does not intentionally write persistent configuration.

This preview contains the test lab, not completed advanced writes, D4i MQTT entities, DT8 control, restore, input commissioning or DT1 active tests. The advanced prototype is preserved in development/ only and is not included in the running app. Do not deploy to an occupied emergency-lighting installation for acceptance tests. The existing MQTT bridge remains unchanged. Actual Docker/HAOS and G3/G4 hardware compatibility still need verification.

## 0.16.0 experimental advanced configuration

Test Lab now reads banks 0–255 and preserves holes. Choose Advanced configuration, action and JSON parameters. Read and save memory bank 0 first; GTIN, identification and versions are decoded. D4i 202–206 data are sampled on demand, require matching reads and known layout, and become unavailable after 15 min. Bank 207 is raw. New MQTT read buttons, diagnostic sensors and fade configuration numbers are disabled by default; enable as needed. DT8 Tc and RGBWAF controls are in the web UI only. Existing MQTT light IDs/modes remain unchanged. DALI-2 commissioning addresses one unaddressed device at a time; sensor parameters use existing instance methods. Restore preview/apply requires an existing controller-specific backup; partial writes are not rolled back; target UID is retained. DT1 tests and input commissioning require isolated test bus confirmation. Manual tests do not replace certified emergency maintenance. All new operations are experimental until tested on actual gear. No automatic emergency schedule or D4i polling.

## 0.16.1 web interface

All seven pages share a common responsive menu, heading and page width. Konfiguration contains ordinary form fields for advanced operations; Test Lab is read-only. The selected controller is remembered across pages; changing it on the legacy views reloads the page instead of retargeting existing controls. The overview's advanced links preselect a bus and address. Restore lists existing backup files. JSON export remains available. New advanced hardware writes remain experimental; no new protocol opcodes in this release.

## 0.17.0

Includes 0.16.1 shared layout and separate configuration forms. Auto identification is enabled by default; only scanned, online, uniquely identified gear is eligible. A background worker processes at most one read job per 30 seconds, skips scans and busy operations, and backs off failures. No automated address/configuration writes. Set auto_identify false to disable identity/capability reads. D4i polling and DT8 MQTT are opt-in until physically verified: d4i_poll_enabled, d4i_poll_interval (300–3600 s), dt8_mqtt_enabled. Polling is best effort, not guaranteed interval under heavy bus load. D4i samples retain existing freshness limits. DT8 Tc/RGB/RGBW uses existing light ID, and is exposed only when actual colour and capabilities are known. RGBWAF 5/6 remains web only. Manual isolated DT1 test commands are recorded in /data/emergency_history.jsonl; command acceptance is not a passed emergency test. No certification claim. Restore/commissioning remain experimental. No new XY or feedback writes.

## 0.17.1 device-first configuration

Select controller, bus and gear/input instance before choosing settings. Device overview displays cached reported values; relevant action groups depend on device type and reported colour capabilities. Offline/conflicted devices cannot execute configuration. Basic level parameters are configurable with readback via the existing advanced identity checks. After each action the selected device is refreshed. DALI-2 commissioning is a separate bus tool, only with no device selected and explicit isolated bus confirmation. Test Lab remains separate. No new DALI telegram opcodes.

## 0.17.2

Configuration shows name, basic levels, fade and supported dimming curve directly, with per-field Save. Writes use the existing identity-checked advanced API and confirmation; no new DALI commands. Action details are hidden until a command has run. Test Lab retains its diagnostic labels.

## 0.18.0 administration

New Energy, Emergency and Maintenance pages share the navigation. Energy sums only fresh valid D4i samples, with per-bus coverage; missing data is not zero. Emergency command history and resource/transaction counters are local only; remote gear snapshots remain available. No safety certification or measured bus-utilization claim. Optional daily cached configuration backup (auto_backup_enabled, default false); existing backup storage policy applies. Restore checks group and scene readback and reports partial changes. Fade time/rate choices show nominal values; level percentage is raw code percentage, not light output. XY, feedback LEDs and HA identity transfer remain unimplemented; advanced hardware features remain experimental.

## 0.18.1

DT8 configuration includes RGB colour picker and Kelvin slider, without sending commands while editing. Unknown channel values remain blank. Event mask editor exposes individual raw bits, without guessing their instance-specific meanings. Named memory banks and manual bank selection. Daily backup timestamp persists across restarts. Restore chooses safe min/max write order. No new DALI opcodes, XY/feedback and HA identity transfer remain unimplemented.

## 0.19.0

Part 301 push-button event filter labels for bits 0–8. Other instance bits remain raw. XY, feedback and identity migration are not enabled. Existing emergency command log retains its bounded rotation; general application logs remain managed by Home Assistant.

## 0.20.0

Maintenance exports a combined JSON snapshot of registered controllers, with selected configuration fields and per-controller errors. This is a snapshot export, not a full restorable backup. Discovery, XY control and clock synchronization remain pending.

## Controller discovery (0.20.1)

Enable `controller_discovery_enabled` on each participating controller. Controllers with `remote_api_enabled` advertise every 15 seconds over IPv4 multicast 239.255.84.43 UDP 38443, TTL 1. Candidates expire after 100 seconds. Controllers page refreshes automatically. Source IP and controller ID are unverified hints; manual registration and existing pinned HTTPS authentication remain required. No credentials in advertisements. Host networking is enabled to receive LAN multicast; check firewall and existing port conflicts (8099 and 8443), and restrict access to trusted networks. Discovery is off by default. VLANs and multicast-filtering networks may require manual setup. No DALI telegrams are emitted by discovery.

## Application clock (0.20.2)

Set `clock_reference_controller_id` to the actual ID of a registered, pinned HTTPS peer using its own system clock. Leave blank on reference. `clock_sync_interval` defaults to 60 seconds. Samples use monotonic round-trip compensation; slow samples are rejected, holdover expires after 900 seconds, and chained references are rejected. Maintenance displays system/application UTC and synchronization status. This creates a separate synchronized application clock exposed by API; existing event timestamps, system clock, TLS, timers and HAOS NTP are not changed. No claim of host clock synchronization. Reference system time must be accurate independently.

## 0.20.3 experimental DT8 XY

Enable `dt8_mqtt_enabled`. Inspect compatible DT8 gear; XY discovery requires an actual valid XY reading and reported support. Uses existing unique ID and JSON light schema. Coordinates are fractions in 1/65536 units, with readback via query colour value. Unsupported coordinates or gamut clipping are reported as mismatches. Only active colour mode is advertised. Physical DT8 verification pending.
