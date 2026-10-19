# Mocks

Stand-ins for the other layers, so the Brain can be built and tested alone. They speak the
real protocol (MQTT, sealed envelopes, topic names from `config/topics.yaml`), contain no Brain
logic, and use the same `src/common/` code as the Brain.

| Mock | Run | Config | Status |
|---|---|---|---|
| Twin | `python -m mocks.twin` | `config/twin-mock.yaml` | done |
| Guardian | | | to do |

## Twin mock

A small deterministic city: one zone (`zone-01`), 6 sensors, 3 actuators, 3 response units.
Run it from the `brain/` folder with a broker and the keys of `README.md` in place. It needs
the `twin-brain` HMAC key and, for a TLS broker, the Twin's own broker account in
`secrets/twin-password.txt` (`auth` in `config/twin-mock.yaml`).

On connect it publishes `twin/status` (`online`, Last Will `offline`), the retained city
description `twin/meta`, and the retained state of every actuator and unit. Then, every
`sim.tick_s` seconds:

| Topic | Content |
|---|---|
| `city/zone-01/sensor/{type}/{sensor_id}` | one reading per sensor: `traffic_speed`, `traffic_density`, `traffic_flow`, `water_level`, `power_load`, `air_quality` (`seq` = tick, `origin: simulated`) |
| `city/zone-01/call` | emergency calls (`fire`, `accident` scenarios) |
| `twin/actuator/{id}`, `twin/unit/{id}` | acknowledgement of a command, and unit status changes (`en_route` → `on_scene` → `returning` → `free`) |

Timestamps are wall-clock (the Brain refuses anything older than 10 s). `sim.run_id: auto`
keeps ids unique across restarts, so the Brain's replay check never fires by accident.

**Scenarios** (`sim.scenario`, started after `scenario_after_ticks`): `calm`, `flood` (water over
1.3 m, rising), `fire` (particulates up + fire calls), `accident` (traffic drops + calls),
`traffic-jam`. Effects are small scripted perturbations, not city physics.

**Commands** (provisional, until the output module fixes the format). Topic
`brain/cmd/{actuator_id or unit_id}`, envelope sealed with the twin-brain key (`hmac` or
`hmacs.twin`), body:

```json
{"id": "brain-000042", "timestamp": "2026-11-14T10:22:04.000Z", "source": "brain",
 "target_id": "valve-01", "action": "open", "parameters": {"opening": 0.8}}
```

| Target | Actions | Parameters |
|---|---|---|
| `valve-01` | `open`, `close` | `opening` 0..1 (default 1); lowers water level by up to 0.3 m |
| `signal-01` | `normal`, `priority` | `priority` adds speed and flow |
| `grid-01` | `normal`, `shed` | `shed` cuts power load by 15 % |
| `unit-fire-01`, `unit-ambulance-01`, `unit-police-01` | `dispatch`, `recall` | `zone_id`; a fire truck on scene cuts particulates by 30 %, the others improve traffic |

The Twin acknowledges after `sim.command_delay_ticks` with `correlation_id` = the command `id`
and `result` `done`, `rejected` or `failed` (+ `reason`, `state`). Same `id` again returns the
same acknowledgement and is never applied twice; same `id` with another payload is `rejected`
(`command_id_reused`). Commands that fail the HMAC, are older than `max_command_age_s`, or name
an unknown target get no answer (logged as `message_refused`).

**Faults** (`faults:` in `config/twin-mock.yaml`, or a `faults` control message). Each reading
fault is meant to hit one check of the input module:

| Fault | Brain answer |
|---|---|
| `malformed`, `wrong_type`, `wrong_unit` | `E_FORMAT` |
| `bad_hmac` | `E_AUTH` |
| `old` (`delay_ticks` ≥ 11 s of age) | `E_STALE` |
| `duplicate`, `replay` | `E_REPLAY` |
| `unknown_id` | `E_UNKNOWN_ID` |
| `impossible` | `E_RANGE` |
| `falsify` (valid but false value) | accepted; Guardian's job |
| `missing`, `delay`, `freeze` | accepted (gaps, late or stuck data) |
| `reject`, `failure`, `lost_ack`, `no_effect` | actuator/unit: `rejected`, `failed`, no acknowledgement until the Brain retries the same id, `done` but no effect on later readings |

**Control** (test only). Topic `twin/control`, sealed with the twin-brain key, body
`{"op": ...}`: `trigger` (`scenario`), `faults` (`faults: [...]`), `contain` (`device_id`,
`action`: `isolate` / `quarantine` / `release`, takes effect next tick), `reset` (new run id,
goes `offline` then `online` so the Brain restarts its `seq` counters), `step` (use with
`sim.mode: manual`).

**Tests:** `pytest tests/mocks`. They include the mock feeding the Brain's real input module:
every message must pass, and each fault must give the code above.
