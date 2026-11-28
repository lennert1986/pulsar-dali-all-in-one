# 0.23.0 – Hardware diagnostics

- Local and paired remote hardware page, cached read-only metadata and JSON export.
- SPI sysfs inventory; allowlisted LUKS metadata from already visible partitions; eMMC, RTC, thermal, CPU/RAM/disk, uptime and existing STM32/UART status.
- Bounded in-memory bus transition history and existing transport counters. No key material, SPI payload, new device permissions, recovery writes or watchdog changes.
- Physical hardware verification pending.

# 0.22.0 – Local zone automation (experimental)

- Optional independent local worker for occupancy/hold, relative daylight regulation, weekly schedule and night level.
- Persistent zone editor, same-controller gear/group target verification and overlap rejection.
- Manual command pause, MQTT enable/disable, timed pause/resume and status; remote management via existing pinned lab API.
- Sensor fallback, live readings, timezone handling, no persistent DALI writes by worker. Physical validation pending.

# 0.21.4 – feedback settings, local button bindings and MQTT

- Configure active/inactive LED brightness (0–255), RGB colour code (1–63) and feedback timing with DTR0, send-twice and exact readback. Explicit isolated test confirmation; only visible-only feedback, no redundant NVM writes.
- Opt-in local short-press and long-press actions (toggle/on/off/step dim) bind a push-button to one same-bus gear or a group of up to 16 known gear. Persist bindings locally and validate stable gear UID, random address and live levels before use. No Home Assistant or MQTT dependency. Group membership changes require re-saving.
- Opt-in follow/inverse feedback based on live target levels, round-robin, steady timing required. No automatic persistent settings writes. Drop old events rather than replay after busy scans.
- Optional MQTT discovery buttons for activate/stop feedback (not falsely reported light on/off), local/remote through existing bridge. Manual MQTT disabled on automatically managed feedback. No actual LED state asserted from no reply.
- Physical testing pending. Source input identity remains bus/address/instance; remove bindings before replacing/readdressing input hardware. No cross-controller bindings or scenes yet.

# 0.21.3 – DALI-2 feedback groundwork

- Correct IEC 62386-332 feedback query opcodes (0x4F through 0x49), feature addressing on instance-number level (0x20 | instance), and single-frame ACTIVATE/STOP (0x10/0x11).
- Scan push-button/generic instances for feedback capabilities; unknown and query errors remain distinct from reported absence. Test Lab input mode includes optional feedback queries.
- Configuration offers read-only feedback details and explicitly confirmed manual active/stop testing on an isolated bus. Only visible-only features may be activated; no automatic LED writes, persistent configuration changes or audible feedback commands.
- A silent active query is not verified OFF. Active mode is not proof of actual LED illumination. Physical validation, brightness/colour writes, local bindings, automatic status follow and MQTT feedback control remain pending.

# 0.21.2 – exclusive controller roles

- Master and subordinate roles are mutually exclusive. Registered children or pending outgoing pairing reserve the master role; incoming pairing/approval and remote authorization are blocked. A subordinate cannot add remote controllers or send remote API commands.
- Discovery advertises the current role as an unverified hint; Controllers UI shows role and disables incompatible actions. Role decisions are enforced independently by the backend.
- Existing conflicting master/child configurations are blocked in both remote directions until the operator removes one side locally; local DALI remains available. No registry entries are silently deleted.
- Manual legacy receiver mode cannot initiate remote connections while standalone. Master roles reject legacy inbound tokens. Update all controllers for consistent role enforcement.

# 0.21.1 – single master and verified IP recovery

- One incoming paired master per controller; further pairing blocked until master revoked. Multiple previous grants fail closed until locally resolved. Master may manage multiple controllers.
- Shared legacy remote API token disabled by default; optional `remote_legacy_token_enabled` works only while unpaired. Paired controllers reject the shared token even if enabled.
- Discovery-based IPv4 recovery verifies the saved certificate, token and controller ID before saving a new address. Never automatically retries write commands. Registry IDs stay stable and stale API requests cannot revert a migrated IP.
- Master address display follows authenticated requests. Automatic IP recovery requires discovery on both controllers and remote HTTPS on the managed device. Custom DNS and non-LAN addresses remain manual.

# 0.21.0 – controller pairing (experimental)

- LAN discovery now offers Add controller and advertises a name/version.
- Five-minute receiver pairing window; compare the entire certificate-bound 16-hex-character code on both controllers, approve on receiver, confirm on initiator.
- Unique bearer credential per pairing, revocation from the receiver; no token in browser. Existing manual HTTPS registration remains available under Advanced.
- Both controllers need this version for pairing. Enable discovery on both and remote HTTPS on receiver. Pairing grants the existing full remote API permissions. Pairing administration is restricted to HA ingress (172.30.32.2) or loopback. Keep the local API unexposed.
- Automatic address migration, scoped grants, mutual pairing and bulk pairing are not included.

# 0.20.3
- Experimental DT8 CIE XY commands, readback, configuration and MQTT JSON light integration.
- Existing light unique ID retained.

# 0.20.2
- Opt-in synchronized application UTC via registered HTTPS reference controller.
- Monotonic holdover, RTT rejection, clock diagnostics.
- No host clock writes or changes to existing event timestamps.

# 0.20.1
- Opt-in LAN multicast discovery, automatic candidate list, expiry and manual trusted pairing.
- Host networking for LAN multicast; check port conflicts and firewall.

# 0.20.0
- Combined installation snapshot export from Maintenance.
- Existing remote identity checks retained.

# 0.19.0
- Named push-button event filter bits (Part 301).
- Existing advanced functionality retained. XY, feedback and HA identity migration pending verification.

# 0.18.1
- DT8 graphical RGB and Kelvin controls; explicit save retained.
- DALI-2 raw event mask bit editor and named memory banks.
- Persistent automatic backup timing and improved restore min/max order.

# 0.18.0
- Dedicated energy, emergency and maintenance dashboards with shared navigation.
- D4i coverage and stale-data handling, local resource and UART transaction statistics.
- Optional daily cache backup and group/scene restore readback.
- Human-readable fade values and level code percentages.
- Advanced hardware verification pending.

# 0.17.2
- Direct editable settings with per-field save and readback.
- Compact advanced option groups and hidden empty result section.
- Separate configuration wording from diagnostic tests.

# 0.17.1
- Device-first configuration with grouped gear and sensor selection, current device facts and capability-filtered actions.
- Basic level settings with identity checks and readback.
- Refresh selected device after actions, avoid invented fade values.
- Separate bus commissioning and automated action-filter checks.

# 0.17.0
- Includes shared navigation and typed configuration forms from 0.16.1.
- Low-priority automatic identity and capability reads; optional D4i polling.
- Optional DT8 Tc/RGB/RGBW MQTT discovery and commands, stable light IDs.
- DT1 command audit history and validation improvements.
- Physical testing still required for advanced functions.

# 0.16.1
- Common responsive layout across all seven pages, stable navigation and active page indicator.
- Dedicated configuration page, typed fields, backup selection and readable results.
- Remember selected controller and reload legacy views when switching.
- Test Lab remains read-only. No new DALI protocol commands.

# 0.16.0 experimental
- Advanced web configuration: fade, curve, DT8, memory/identity, sampled D4i, input commissioning, restore and manual DT1 tests.
- MQTT additional properties and sampled diagnostics; existing IDs and brightness modes retained.
- Memory Lab handles missing bytes and all bank numbers.
- Physical testing pending for new writes.

# 0.15.0 development preview
- Read-only DALI Test Lab, local and remote controller selection, firmware, basic parameters, fade codes, DT6/DT8/DT1 capability queries, DALI-2 input diagnostics, raw memory-bank reads, telegram tracing and JSON export.
- Advanced writes remain disabled and in development.

# 0.14.0 experimental
- G3 (CM3 / FTDI interface mapping) and G4 (CM4) hardware profiles.
- Safe detection failure; manual and remote-only modes.
- I2C bus selection and configurable LED polarity.
- Hardware-profile unit tests and status reporting.

# 0.13.0 experimental
- Separate All-in-One app, local and remote DALI management.
- Standard MQTT Discovery; no custom integration required.
- Optional local hardware, explicit HTTPS host port mapping.
- MQTT status in overview, retained availability and stable IDs.
