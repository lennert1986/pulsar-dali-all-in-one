# Configuration

Install and configure Home Assistant's standard MQTT integration and a broker (e.g. Mosquitto). The app requests the Supervisor MQTT service automatically when mqtt_host is empty; otherwise set host, port, user, password and mqtt_tls explicitly. TLS uses normal CA/hostname validation. No broker is bundled. Use a private LAN or TLS for MQTT.

Stop the old Pulsar app before starting this one. Stop/disable the old Pulsar custom integration to avoid duplicate entities. The new app uses separate /data and a separate controller ID; existing configuration, names, areas, automations and entity registry are not migrated automatically.

Local controller: local_dali_enabled=true (default). Remote-only master: local_dali_enabled=false. Add remote controllers via Controllers using token and SHA-256 certificate fingerprint. For a slave, enable remote_api_enabled and explicitly map port 8443 in Network. Disable mqtt_publish_local or mqtt_publish_remote as appropriate. Do not publish the same physical controller twice to one MQTT broker. Only one publisher should control each physical controller per broker. Hardware-free amd64 use is experimental; Supervisor device mapping is not verified on such hosts.

Run scan in web UI (or MQTT Scan buttons). HA creates lights, switches, groups, scenes, pushbutton events, occupancy, relative illuminance and diagnostic/config entities. DT8 color control and unaddressed DALI-2 commissioning are not implemented. Relative illuminance is not lux. Commands to conflicted/offline gear are blocked by the MQTT bridge. During scans the bridge refuses normal commands. Use the original commissioning UI for address changes.

MQTT state and availability retained; events and commands not retained. Broker account needs publish/subscribe rights on the configured discovery prefix and pulsar_dali_aio/#. Treat MQTT credentials as control access. No public MQTT listener is created. If replacing the app or changing broker/prefix, clean old discovery topics on the former broker before removing it.

Experimental: test actual DALI hardware and Home Assistant MQTT discovery before production use.
