# Pulsar DALI All-in-One

Experimental v0.14.0. One Home Assistant App for the Pulsar DALI hardware, local and remote commissioning and Home Assistant MQTT entities. Requires the standard MQTT integration and an MQTT broker (e.g. Mosquitto). No Pulsar custom integration needed.

Add https://github.com/lennert1986/pulsar-dali-all-in-one in Settings → Apps → Install app → Repositories. Stop the original Pulsar App before running this one on the same hardware. See the app documentation.

This is a new installation with a separate data directory; do not assume configuration or entity registry migration. Do not run two publishers for the same controller on the same broker.
 
Experimental Vertex G3 / G4 profiles: see app DOCS.md.

The develop/dali-complete branch contains the v0.15.0 Test Lab preview. Advanced writes remain experimental and disabled.
