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


## Controller pairing (0.21.0)

On both controllers enable `controller_discovery_enabled`; on the receiver enable `remote_api_enabled` and restart. On the receiver open Controllers → Tillad parring. On the initiating controller click Tilføj controller, give it a name, compare the **entire** code on both screens, approve on the receiver, then click Koden matcher – tilføj on the initiator. Never approve a differing code. A pending session expires after five minutes. The resulting bearer token is stored in the initiating registry and only its hash on the receiving controller. Revoke the grant on the receiver; removing a controller from the initiating list does not revoke remote permission. Existing manual credentials and their rotation are independent. Pairing is experimental and grants the existing full remote API permissions. Keep local port 8099 unexposed; use authenticated HA ingress. The discovered hostname and version are unverified hints. The UI intentionally uses a longer code than a six-digit PIN to resist guessing or manipulation. If the receiver's certificate changes, verify and re-pair manually.


## Single master and IP recovery (0.21.1)

Each controller accepts only one incoming paired master, even after restart. A master may manage multiple controllers. Remove the master locally under Controllers → Master-controller before pairing a replacement. If more than one historical grant exists, all remote grant authentication is blocked until only one remains. Local control continues. The old shared manual token is disabled by default; set `remote_legacy_token_enabled: true` only for an unpaired legacy installation that requires manual access. This compatibility mode is not exclusive because the shared token can be copied. It never works on a paired controller. Existing paired tokens are retained. For manual connections on upgrade, either pair instead or explicitly opt in to legacy mode. Discovery must be enabled on both devices for automatic address recovery. When a registered LAN IPv4 address stops responding and discovery identifies an alternate address, the master verifies the stored TLS fingerprint and bearer token and checks the stable controller ID before changing the registry. A working old address is retained; ambiguous candidates are rejected. MQTT identities, registry IDs, and DALI configuration are unchanged. No writes are automatically replayed. DNS/WAN entries are not rewritten. If discovery is blocked by VLANs, edit the address manually.


## Exclusive topology (0.21.2)

A controller with at least one registered remote child is a master. It cannot itself be paired to or managed by another master, and it rejects incoming pairing and remote bearer tokens. A controller already paired to a master is a subordinate and cannot add or control remote controllers. Pending outgoing requests reserve the master role, and approved incoming requests reserve the subordinate role. A standalone controller can choose either direction. To switch roles, remove the existing master or remove all child registrations; also remove the corresponding grants on the other devices so they can be paired again. Mixed configurations from older releases fail closed for remote traffic until resolved locally, without automatically deleting anything. Legacy receiver mode is not permitted to initiate connections when standalone. Discovery role hints are not trusted as authorization. Both ends must run 0.21.2 or newer for full enforcement; old firmware may not enforce these rules. Local DALI control remains unchanged.


## DALI-2 feedback (0.21.3, experimental)

Scan the bus to query Part 332 capability on generic and push-button instances. Test Lab → DALI-2 input adds optional capability, active, timing, brightness and colour queries. No reply is unknown, not proof of unsupported hardware. In Configuration select the input instance and Feedback-LED → Læs feedback-egenskaber or Manuel feedback-test. The latter requires explicit confirmation and an isolated test bus; only a freshly confirmed visible-only capability permits sending single-frame ACTIVATE or STOP. A feature's active and inactive brightness can differ from on/off; a silent active query cannot conclusively prove inactive mode. No automatic LED synchronization, persistent brightness/colour configuration, local bindings or MQTT writes are enabled. Actual button/LED hardware has not yet been tested. Source: IEC 62386-332:2017/COR1:2019; IEC 62386-103:2014/AMD1:2018 table 2.


## Local buttons and feedback (0.21.4, experimental)

Enable `local_button_bindings_enabled: true` on the hardware controller and restart. In Configuration select the scanned DALI-2 push-button. Enable the instance, select event scheme 2, enable event filter bit 2 (short press), bit 4 (long press start), and bit 5 if using repeat dimming. Open Lokal knapstyring → Konfigurér lokal tilknytning. Select a same-bus armature or group (max 16 members), short/long action and optional follow/inverse feedback. Save explicitly. The source is addressed by bus/address/instance; remove bindings before input replacement or readdressing. Gear identity and membership are checked before commands; group actions are sent to verified individual members, not broadcast. After a target changes re-save the binding. Long dim steps are 20 DALI arc codes; not a perceptual percentage. Local bindings run even when HA/MQTT are unavailable. Events older than 3 s or received while operations are busy may be dropped, not replayed. Disable or remove a local binding before assigning the same button to a conflicting HA automation. Configuration stored in `/data/button_bindings.json`; back up this file separately.

For LED setup, open Feedback-LED → Indstil LED-lysstyrke / farve. Configure active and inactive brightness 0–255, colour 1–63 (two bits per channel: red + 4*green + 16*blue, channels 0–3, black uses brightness 0), and timing 255 for steady follow or MQTT. Explicit isolated test bus confirmation required. A DTR0 and send-twice command followed by matching readback verifies storage; unsupported or audible feedback is rejected. No redundant writes when value already matches. Automatic follow means active when any linked gear has actual level >0; inverse is the opposite. Actual physical LED brightness depends on configured active/inactive brightness and colour. Sync runs on the controller, one binding per 3-second cycle, with periodic reassertion and live identity/level checks; no automatic persistent writes. If there are multiple bindings, latency increases.

Enable `feedback_mqtt_enabled: true` on the target hardware controller and restart. Scan to detect feedback capability. HA discovers Activate feedback and Stop feedback buttons for visible-only features with no automatic follow/inverse binding. The master bridge can publish remote buttons; existing event IDs remain unchanged. Set steady timing (255) first; runtime command checks it. No actual light on/off state is asserted, because STOP may select a nonzero inactive brightness and no reply is ambiguous. All features are experimental and not physically validated. No cross-controller bindings or scene binding in this release.


## Local automation (0.22.0, experimental)

Enable local_automation_enabled on the hardware controller and restart. Open Automatik and select the local or paired remote controller. Create a zone using a scanned ordinary gear or group (maximum 16 members), optional same-bus occupancy and/or relative light sensor, and optional weekly schedule in an explicit IANA time zone (default Europe/Copenhagen). Select weekdays, start/end, normal and outside-window levels. Midnight-spanning windows are supported. Equal start/end means all day on selected weekdays. Configure occupancy hold, vacant level, daylight setpoint (normalized relative value, not lux), deadband, minimum/maximum and adjustment step. Sensor communication failure uses last valid sample for the configured timeout, then hold existing level or use an explicit fallback. The priority is manual override, outside schedule level, occupancy, daylight and normal level. Only one zone can own each gear; group members and identities must be reviewed and re-saved after changes. Emergency and unknown gear are excluded.

The worker processes one enabled zone per approximately three-second cycle. It uses live target readings and sensor queries, no MQTT dependency. It skips scans/busy operations, retries errors with backoff and avoids writing when the requested level already matches. Up to 32 zones; this is best-effort control, not a real-time guarantee. The zone definitions persist in /data/local_automation.json; back up this file separately. Runtime override and hold timers reset at app restart. Local button and ordinary HA light commands can pause overlapping zones for the configured override duration (default 1800 s; zero disables automatic pause). Pause 30 min and Resume are available in the web UI and HA MQTT discovery. Disable a rule for indefinite manual ownership. The schedule uses the hardware host's system clock, not the application-clock estimate; maintain correct time independently. No calibrated lux, cross-controller targets, scene rules or physical acceptance tests in this version. Remove rules before readdressing/replacing their input devices; input identities are bus/address/instance. Local software requires the app and hardware to remain running.


## Hardware diagnostics (0.23.0)

The Hardware page selects local or paired remote controllers through the existing pinned HTTPS API. It displays container-visible device-tree/CPU identity, kernel, SPI sysfs devices and driver/modalias metadata, partition sizes and readable LUKS header summaries (version, UUID, cipher, reported key size, keyslot count and KDF where available), eMMC raw lifetime/pre-EOL indicators, RTC date/time, host-visible resources and thermal zones, existing STM32/UART status, transport counters and the latest 100 observed bus-state transitions. Resource sampling is every ten seconds; slower device/partition metadata are refreshed approximately every 120 seconds. JSON export includes only the collected metadata, and may contain hardware serial numbers and partition UUIDs. No raw SPI payload is read, no key material or decrypted content is collected, and no new raw device permissions are granted. A visible SPI node is not evidence of a particular chip model, contents or clock rate. HAOS may not expose the original Vertex partition or SPI node. RTC battery health is not measured; eMMC indicators are raw, not a remaining-life prediction. LUKS probing uses read-only luksDump on at most four already visible partition nodes per slow cycle; no unlock, mount or header modifications. No UART recovery, hardware watchdog or new automatic firmware polling is added in this release. Physical G3/G4 verification is pending.

## SPI identification (0.23.1)

Enable `spi_identification_enabled: true` only on the known Vertex G4 board and restart. The app requests the specific /dev/spidev1.1 mapping; no full device access is requested. The host must already expose the device, and Supervisor must allow access. No overlay or host configuration is modified. The optional probe runs once per app start on a local G4 profile/CM4 model with local DALI enabled, using SPI mode 0, 8 bits and 500 kHz. Two matching JEDEC ID replies are required. Familiar NOR families are eligible for bounded SFDP parameter-space queries; the reported density is compared with the estimated JEDEC capacity. Unknown IDs, missing access and unsupported SFDP are reported, not guessed. The precise chip model is not inferred from family alone. The SPI settings are restored after the probe; no flash array reads, OTP reads, writes, erase, security register accesses or key extraction are implemented. The result appears on Hardware, including remote paired-controller view. Physical verification pending; the Linux ioctl transport is not exercised on real hardware by unit tests. A missing device can be investigated in the host hardware inventory; do not broaden privileges merely to make the probe succeed.
