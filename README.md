# Forza Shift Light (WLED)

This python script reads Forza telemetry and drives a WLED LED strip in realtime mode as a shift light.

---

## What it does

- Listens to Forza UDP telemetry
- Reads RPM and max RPM
- Calculates RPM ratio
- Sends LED data to WLED
- Turns LEDs on/off based on a set shift threshold (e.g. 85%)
