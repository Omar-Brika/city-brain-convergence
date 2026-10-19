# brain — Interface Card (R1)

Inputs, outputs, message formats. Full rules: interface specification v0.1.

## Inputs

Every payload is an envelope `{"v": 1, "body": "<JSON text>", "hmac": "<hex>"}` (or `"hmacs": {"brain": ...}` for messages read by several layers). The HMAC is HMAC-SHA256 over the UTF-8 bytes of the body text, with the key of the sending pair (Twin–Brain, Guardian–Brain). Topic names are in `config/topics.yaml`.

| Topic | From | QoS | Retained | Body (beyond `id`, `timestamp`, `source`, `correlation_id`) |
|---|---|---|---|---|
| `twin/meta` | Twin | 1 | yes | `zones[]`, `sensors[]` (`min`, `max`, `unit`), `actuators[]`, `units[]` |
| `city/{zone}/sensor/{type}/{sensor_id}` | Twin | 0 | no | `sensor_id`, `zone_id`, `type`, `value`, `unit`, optional `origin`, `seq` |
| `city/{zone}/call` | Twin | 1 | no | `call_id`, `zone_id`, `category`, optional `text` (≤ 280) |
| `twin/actuator/{actuator_id}` | Twin | 1 | state: yes | `actuator_id`, `result`, `state`, `reason` |
| `twin/unit/{unit_id}` | Twin | 1 | yes | `unit_id`, `status`, `zone_id`, `result`, `reason` |
| `guardian/verdict/{sensor_id}` | Guardian | 1 | yes | `sensor_id`, `verdict` (`trusted` / `suspicious` or `suspect` / `rejected`), `reason`, optional `trust_score` |
| `guardian/quarantine/{device_id}` | Guardian | 1 | yes | `device_id`, `state` (`quarantined` / `released`), `reason` |
| `twin/status`, `guardian/status` | each | 1 | yes | `status` (`online` / `offline` / `degraded`), with Last Will |

**What the Brain refuses** (reported on `brain/error` with the code, the topic and the message id):

| Code | When |
|---|---|
| `E_FORMAT` | Bad envelope or body JSON, missing / wrong-type field, wrong unit, topic and body disagree, wrong `source` |
| `E_AUTH` | HMAC (or Ed25519 signature) missing or wrong |
| `E_STALE` | Timestamp more than 10 s from the Brain's clock (retained and status messages excepted) |
| `E_REPLAY` | Same `id` within 60 s, or `seq` not increasing for a device |
| `E_UNKNOWN_ID` | Sensor, zone, actuator, unit or device not in `twin/meta`, or no `twin/meta` yet |
| `E_RANGE` | Reading outside the sensor's `min` / `max` |

Unknown extra fields are ignored (MSG-5).

## Outputs

| Topic | QoS | Retained | Content |
|---|---|---|---|
| `brain/status` | 1 | yes | `status`: `online` / `offline` (Last Will) |
| `brain/error` | 0 | no | `code`, `topic`, `message_id`, `detail` |
| `brain/event` | 0 | no | timeline events: `event`, `summary`, `correlation_id`, `incident_id` |
| `brain/cmd/{actuator_id or unit_id}` | 1 | no | commands (output module) |

Outgoing messages use the same envelope, with `hmacs` for `twin` and `guardian`.
