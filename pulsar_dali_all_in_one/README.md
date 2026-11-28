# Pulsar DALI All-in-One

**Version 0.23.1 · Experimental · aarch64 / amd64**

One Home Assistant app for compatible Pulsar/Vertex hardware, three DALI buses, local and remote commissioning, DALI-2 inputs, MQTT Discovery, diagnostics and secure multi-controller management.

[Complete project README](https://github.com/lennert1986/pulsar-dali-all-in-one#readme) · [Configuration and release notes](https://github.com/lennert1986/pulsar-dali-all-in-one/blob/main/pulsar_dali_all_in_one/DOCS.md) · [Changelog](https://github.com/lennert1986/pulsar-dali-all-in-one/blob/main/pulsar_dali_all_in_one/CHANGELOG.md)

## Before starting

Stop the original Pulsar app before using the same physical hardware. All-in-One uses a separate data directory; previous configuration and Home Assistant entity registry are not automatically migrated. Use one MQTT publisher per physical controller on each broker.

For Home Assistant entities, install a broker such as Mosquitto and the standard MQTT integration. No separate Pulsar custom integration is required.

## Quick start

1. Configure the hardware profile: auto, vertex_g3, vertex_g4, remote_only or manual.
2. Start the app and check its startup log. If hardware detection fails, correct the UART mapping before using local DALI.
3. Open the web UI through Home Assistant ingress.
4. Run Test Lab → STM32-kommunikation on each connected bus.
5. Scan the bus, review gear and input instances, and resolve address conflicts.
6. Test basic parameters and control on a known device before advanced configuration.
7. Enable optional features only as needed.

## Main features

| Function | Description |
| --- | --- |
| DALI | Three local buses, control gear, groups, scenes, addressing and configuration |
| DT6 / DT8 | Level and fade settings, dimming curves, compatible colour modes |
| DALI-2 | Input instances, push-button events, occupancy, relative illuminance |
| Feedback | Part 332 capability reads, manual activation, brightness, colour and timing |
| Local button bindings | Same-bus gear/group toggle, on/off and stepped dimming without MQTT |
| Automatic feedback | Follow or inverse live light status |
| MQTT | Standard HA entities and optional feedback command buttons |
| Controllers | Discovery, approved TLS-pinned pairing, single-master roles, verified IP recovery |
| D4i | Memory-bank diagnostics and optional sampled energy data |
| DT1 | Emergency status and manual test commands; not a certified test system |
| Test Lab | Diagnostic reads, telegram log, latency and JSON export |
| Maintenance | Cached backup, restore tools, resource data and combined snapshot export |

## Multiple controllers

A master can manage multiple subordinate controllers, but cannot itself have a master. A subordinate cannot manage other controllers. Local operation is still available.

Example hardware-free master configuration:

```yaml
hardware_model: remote_only
local_dali_enabled: false
controller_discovery_enabled: true
remote_api_enabled: false
mqtt_publish_local: false
mqtt_publish_remote: true
```

On each managed hardware controller enable discovery and remote HTTPS, map TCP 8443 as required, and disable its own MQTT publishing if the master publishes it. In Controllers, allow pairing on the receiver, add it on the master, compare the entire code, approve on the receiver and confirm on the master. Remove the master locally to revoke access.

## Optional DALI-2 features

```yaml
local_button_bindings_enabled: false
feedback_mqtt_enabled: false
```

Enable as needed on the hardware controller. Select a scanned push-button instance under Configuration to configure its local binding and Part 332 feedback. Local bindings require an enabled instance, event scheme 2 and suitable event filter. Follow/inverse and MQTT feedback require continuous timing (255); MQTT is unavailable when an automatic feedback binding owns the feature. Remove bindings before readdressing or replacing the input device. These features remain physically unverified.

## Security and backup

Keep TCP 8099 restricted to the trusted local ingress environment; do not expose the local API to untrusted clients or the Internet. Remote control uses pinned HTTPS on 8443. Discovery uses UDP 38443 and is disabled by default; legacy shared-token access is disabled by default. Keep credentials and backup data private.

Back up app data before upgrading or commissioning. Combined JSON snapshot export is not a full restore backup. Keep a separate copy of local button bindings and app credentials.

## Documentation

The [complete GitHub README](https://github.com/lennert1986/pulsar-dali-all-in-one#readme) contains hardware mappings, installation instructions, all configuration defaults, multi-controller setup, MQTT, DALI-2 binding instructions, energy, emergency limitations and troubleshooting.

**Experimental:** automated tests do not establish physical hardware compatibility, DALI certification or emergency-lighting compliance. Test advanced functions on an isolated bus before production use.

## Local automation and hardware

Enable `local_automation_enabled` for local zone rules. The Hardware page displays local or paired remote hardware metadata, including SPI inventory, readable LUKS metadata, eMMC, RTC, resources and bus status. No raw SPI data or keys are collected. See current DOCS.md for limitations.

Optional SPI identification: enable `spi_identification_enabled` on the known Vertex G4 and restart. Hardware displays JEDEC and supported SFDP metadata only.
