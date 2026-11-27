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
