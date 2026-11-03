# brain

How to run this layer alone.

## Setup

Python 3.11+. From the `brain/` folder:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Keys and certificates go in `brain/secrets/` (git-ignored, never committed). Paths are set in `config/security.yaml`:

```
secrets/ca.crt                     # triplet CA, used to verify the broker
secrets/broker-password.txt        # password of the `brain` broker account
secrets/keys/twin-brain.key        # HMAC key Twin-Brain (UTF-8 text, >= 32 random bytes)
secrets/keys/guardian-brain.key    # HMAC key Guardian-Brain
secrets/keys/guardian-ed25519.pub  # only if guardian_signature.mode = ed25519
```

To create a key for local tests (the real keys come from the team lead):

```bash
mkdir -p secrets/keys
python -c "import secrets; print(secrets.token_hex(32))" > secrets/keys/twin-brain.key
```

## Modules

| Module | Run | Code | Team doc |
|---|---|---|---|
| Input (front door) | `python -m src.input` | `src/input/` | `01-input` |
| Detection (readings and calls -> incidents) | `python -m src.detection` | `src/detection/` | `02-graph` |
| Graph (city memory, context API on :8080) | `python -m src.graph` | `src/graph/` | `02-graph` |
| LLM (local model, proposals) | `python -m src.llm` | `src/llm/` | `03-llm` |
| Mock LLM (no model needed) | `python -m mocks.mock_llm [scripted\|slow\|offline\|invalid]` | `mocks/mock_llm/` | `03-llm` |
| Twin mock (test stand-in) | `python -m mocks.twin` | `mocks/twin/` | see `mocks/README.md` |

Every module reads `config/*.yaml`. To use another config folder (e.g. a local broker without TLS), set `BRAIN_CONFIG_DIR=/path/to/config`.

## Tests

```bash
.venv/bin/python -m pytest              # all tests
.venv/bin/python -m pytest tests/input  # input module only
.venv/bin/python -m src.common.schemas  # regenerate contracts/schemas/ after changing a model
```

## Shared code (`src/common/`)

| File | Use |
|---|---|
| `mqtt.py` | `BrainMqtt`: TLS / mTLS, auto-reconnect and re-subscribe, optional Last Will |
| `envelope.py` | `seal`, `seal_multi`, `verify_hmac`, `verify_ed25519`: the envelope of the interface spec |
| `models.py` | pydantic models of external bodies and of the internal messages |
| `config.py` | YAML loader, paths relative to `brain/` |
| `log.py` | JSON-lines logger (`logs/`) |
| `ids.py` | `in-000001` style ids |

---

## Input module

The front door of the Brain. Every Twin and Guardian message goes through 7 checks, in this order, stopping at the first failure:

| # | Check | Error |
|---|---|---|
| 1 | Envelope: JSON with `v`, `body`, `hmac` / `hmacs` | `E_FORMAT` |
| 2 | Signature: HMAC-SHA256 over the body text (`hmac` or `hmacs.brain`); Ed25519 for Guardian if enabled | `E_AUTH` |
| 3 | Freshness: timestamp within +-10 s | `E_STALE` |
| 4 | Replay: id not seen in the last 60 s; `seq` increasing per device if present | `E_REPLAY` |
| 5 | Format: fields and types; topic and body agree; `source` matches the topic | `E_FORMAT` |
| 6 | Known IDs: declared in `twin/meta` (zone, type of the sensor too) | `E_UNKNOWN_ID` |
| 7 | Range: value within the sensor's `min` / `max` | `E_RANGE` |

Accepted messages are republished on `brain/internal/…` (formats in `team-docs` overview, section 3; schemas in `contracts/schemas/`). Rejected ones are logged and published on `brain/error` (rate-limited).

**Published:**

| Topic | Retained | When |
|---|---|---|
| `brain/internal/meta` | yes | city description received |
| `brain/internal/reading` | no | valid reading |
| `brain/internal/call` | no | valid emergency call |
| `brain/internal/trust/{sensor_id}` | yes | Guardian verdict (`suspect` mapped to `suspicious`; `trust_score` or `null`) |
| `brain/internal/quarantine/{device_id}` | yes | quarantine / release |
| `brain/internal/ack` | no | Twin acknowledgement, actuator state, unit state |
| `brain/internal/layer-status/{twin,guardian}` | yes | layer online / offline / degraded |
| `brain/error` | no | rejected message (sealed for Twin and Guardian) |
| `brain/event` | no | city description received, layer online / offline, device quarantined / released |
| `brain/status` | yes | `online` on connect, `offline` as Last Will and on clean stop |

**`brain/internal/ack`** (not in the overview yet):

```json
{"id": "in-000612", "timestamp": "2026-11-14T10:22:04.420Z", "correlation_id": "brain-000042",
 "message_id": "twin-000205", "kind": "actuator", "target_id": "valve-port-up",
 "result": "done", "state": "open_80"}
```

`correlation_id` is the Brain command id when the Twin acknowledges a command (`result` present), otherwise the Twin message id. Unit messages add `status` and `zone_id`. Absent fields are omitted.

**Design choices to know:**

- **Retained messages skip freshness and replay.** The broker hands them over again on every (re)subscribe, so they are old by design. They still need a valid HMAC, format and IDs. Without this, a restarted Brain would refuse its own city description (IT-1).
- **Status topics skip freshness and replay.** A Last Will is written when the client connects, so it is always old when the broker fires it.
- **Guardian online / offline:** offline if `guardian/status` says so, **or** if no live verdict or quarantine has arrived for 30 s (`layers.guardian_silence_s`). Retained verdicts don't count as a sign of life.
- **`seq` restarts** are accepted when the Twin (or Guardian) comes back `online`.
- **Field-name differences** found at a joint run go in `config/input.yaml` → `field_map` (e.g. `event_id: id`), not in code. Topic names are in `config/topics.yaml`.
- A clock difference over 2 s is logged as `clock_drift` (ask the Twin to use NTP).
- Every 30 s the module logs `input_stats`: messages/s and average time per message.

**Measured:** about 0.07 ms per message through a real TLS broker, and well over 200 messages/s (unit test `tests/input/test_performance.py` checks < 5 ms and >= 200 msg/s).

**Switching to mTLS / Ed25519** (if agreed with Guardian): set `tls.client_cert` / `tls.client_key`, and `guardian_signature.mode: ed25519` with the public key path, in `config/security.yaml`. No code change.

---

## LLM module

A local LLM proposes actions for each incident. It only **proposes**: the math module scores the proposal against the rule fallback, and the output module applies the safety rules. If the LLM is slow, offline or answers badly, the rule fallback's proposal is used.

```
brain/internal/incident (opened / updated) ─▶ context ─▶ prompt ─▶ local LLM (Ollama) ─▶ validate ─▶ brain/internal/proposal
                                              ▲                                              │ refused
          meta, quarantine, ack, call ────────┘ (+ graph GET /context, optional)             └─▶ brain/event llm_invalid_output
```

**Consumes:** `brain/internal/incident`, `meta`, `call`, `ack`, `quarantine/+`, and optionally the graph `GET /context/{incident_id}` (`context.graph_url`).
**Publishes:**

| Topic | Retained | When |
|---|---|---|
| `brain/internal/proposal` | no | valid answer, `origin: llm` (schema `contracts/schemas/internal-proposal.schema.json`) |
| `brain/internal/llm-status` | yes | `online` / `offline` (Last Will, and on every health change) |
| `brain/event` | no | `llm_proposal`, `llm_timeout`, `llm_invalid_output`, `llm_skipped`, `llm_online`, `llm_offline` |

**Setup (edge device = the demo laptop):** install [Ollama](https://ollama.com), then `ollama pull <model>` for the model in `config/llm.yaml` (`backend.model`). The module warms the model up at start and keeps it loaded (`keep_alive`). No internet is needed once the model is pulled. Use `127.0.0.1`, not `localhost`, in `backend.url`: on Windows, `localhost` tries IPv6 first and adds about 2 s to every call.

**Benchmark** the candidates on the device (writes the table for the report):

```bash
python -m src.llm.bench --models qwen2.5:3b,llama3.2:3b,qwen2.5-coder:7b --repeat 10
```

Cases are in `tests/llm/cases.yaml` (B2, B5, B8, B10, B11 of the Test Book); each run goes through the real service (context, prompt, validation).

**Design choices to know:**

- **Time budget, hard.** The 8 s (`budget.answer_s`) start when the incident is received: queue wait, graph call and generation all count. The answer is streamed, and the connection is closed at the deadline, which also stops Ollama generating. Late answers are dropped with `llm_timeout`.
- **Latest version wins.** A newer update of the same incident replaces the queued request; a `closed` incident cancels it; an answer for an incident that changed meanwhile is dropped.
- **Context is built locally** from the retained internal topics, so the LLM works even if the graph API is down. The graph only adds related events and quarantined devices. The prompt stays under 1,500 characters (`context.max_chars`); related events, then older calls, then extra evidence are dropped first.
- **Only relevant devices are offered** (`relevant_targets` per incident type): on an accident the model never sees a valve, whatever a call says. Quarantined devices and busy units are left out.
- **Structured output.** The answer JSON Schema given to Ollama lists only this incident's devices and actions as enums, so the model cannot even produce an unknown id.
- **Strict validation anyway** (`validate.py`): known device, allowed action, not quarantined, at most 3 actions, bounded params and justification. In `strict` mode one bad action refuses the whole answer.
- **Call text is data.** It sits in a `<call_text>` block; `<` and `>` are neutralised so it cannot close the block, and the system prompt says it is never an instruction.
- **Action hints** (`action_hints`) tell the model what each action does (e.g. valve `open` drains the zone). They must match the Twin's simulation.
- **Everything is logged** (`logs/llm.jsonl`): prompt version, model, prompt, raw answer, latency.

**Mock LLM** (`python -m mocks.mock_llm <mode>`): the same service with a scripted backend, for teams without the GPU. `scripted` answers from `mock.playbook`, `slow` answers after 15 s (→ `llm_timeout`), `offline` never answers (→ `llm-status offline`), `invalid` returns broken JSON (→ `llm_invalid_output`).

---

## Detection module

Turns the stream of readings and calls into incidents: `opened`, `updated`, `closed`, never one message per reading.

```
reading ─▶ per-sensor baseline (EWMA) ─▶ abnormal? ─┐
call ──────────────────────────────────────────────┼─▶ per zone + type: weighted signals x Guardian trust ─▶ confidence ─▶ lifecycle ─▶ brain/internal/incident
trust/+, layer-status/guardian ─▶ weights ─────────┘                                                                    └─▶ brain/event
```

**Consumes:** `brain/internal/meta`, `reading`, `call`, `trust/+`, `layer-status/+`. Zones, neighbours, sensors and alert levels all come from `meta`; no id is in the code.
**Publishes:**

| Topic | Retained | When |
|---|---|---|
| `brain/internal/incident` | no | incident `opened` / `updated` / `closed` (schema `contracts/schemas/internal-incident.schema.json`), ids `inc-0001`... |
| `brain/event` | no | `incident_opened`, `incident_updated`, `incident_closed`, `evidence_rejected` (sealed for Twin and Guardian) |

**Method** (all numbers in `config/detection.yaml`):

1. **Per sensor.** Running mean and variance (cumulative for the first 20 readings, then EWMA, weight 0.05). A reading is *bad* when it is at the sensor's `alert` level, or (after warm-up) more than 3 standard deviations away in the bad direction of its type (water, air, power, density: up; speed, flow: down). Three bad readings in a row make the sensor abnormal, three good ones (z < 2 and below 0.9 x alert) normal again. Only quiet readings (|z| <= 2) are learned, so a flood or a slow rush-hour ramp is never learned as normal. A sensor silent for 10 s stops counting.
2. **Per zone and incident type.** Each source (one sensor, or *all* recent calls of one category in the zone) gives `p = min(cap, weight x strength x trust)`; `confidence = 1 - prod(1 - p)`. Strength is 1 at alert level, else `z / 6`; for calls `count / 3`. Caps: 0.6 for one reading, 0.95 for a reading at alert level for 3 readings, 0.55 for calls, so one source alone stays low unless it is a sustained alert-level reading.

   | Incident | Primary signals | Support (only with a primary) | Gates |
   |---|---|---|---|
   | `flood` | water level (0.9), flood calls (0.6) | water in a neighbouring zone (x 0.3) | rising to open (unless a call confirms) |
   | `fire` | air quality (0.85), fire calls (0.6) | power spike (0.3), air in a neighbour | |
   | `accident` | sudden speed drop (0.45), accident calls (0.6) | density (0.2) | without a call capped at 0.45: a drop alone may be a jam |
   | `traffic_jam` | speed down >= 30 % for 20 s (0.7) | density (0.4), flow (0.3) | not during a city-wide pattern (>= 50 % of zones slow: rush hour) unless the zone is under half the city median; not when an accident explains it |
   | `power_problem` | power load (0.8) | | not when a fire is in the zone or a neighbour |
3. **Guardian trust:** trusted = `trust_score` or 1.0, suspicious = `trust_score` or 0.3, rejected = 0 (ignored, `evidence_rejected` on the timeline once), no verdict or Guardian offline = 0.6 and `verified: false`. Calls are not checked by Guardian: an incident with no reading evidence is never `verified`.
4. **Lifecycle:** open at confidence >= 0.5 on 2 checks in a row; one open incident per zone + type; `updated` on a new evidence source or a severity change, at most every 5 s (a lower severity only after 15 s); closed after 2 checks below 0.25 or with no live evidence. Checks run every second and when a sensor changes state or a call arrives. `correlation_id` = the first bad reading (or first call) of the chain.

**Severity:** low under 0.6 confidence; high when the value is 50 % over alert or 2 sources agree at >= 0.75; critical only with 3 sources, >= 0.9 and 50 % over alert.

**Ten fake calls (B7)** are one source capped at 0.55: one `low`, unverified incident at most, closed when the calls age out (120 s). A fake flood whose sensor Guardian rejects (B3) opens nothing.

---

## Graph module

The Brain's memory: the city map and every event, linked, in memory (stdlib only, no database server), with a small read-only HTTP API.

**Consumes:** `brain/internal/meta`, `reading`, `call`, `trust/+`, `quarantine/+`, `ack`, `layer-status/+`, `incident`, `proposal`, `decision`, `outcome`. **Publishes:** nothing on MQTT; HTTP on `http.host:http.port` (`config/graph.yaml`, default `127.0.0.1:8080`, the `context.graph_url` of the LLM module).

| Nodes | Links |
|---|---|
| zone, sensor, actuator, unit (from `meta`) | zone `NEXT_TO` zone, sensor `IN` zone, actuator `IN` / `CONTROLS` zone, unit `BASED_IN` zone |
| reading, verdict, call, quarantine | reading `FROM` sensor, verdict `ON` reading, call `IN` zone, quarantine `ON` device |
| incident, proposal, decision, action, ack | incident `IN` zone, incident `EVIDENCE` reading / call, proposal / decision `FOR` incident, decision `CHOSE` proposal, action `EXECUTES` decision, action `TARGETS` device, ack `CONFIRMS` action |

| Endpoint | Returns |
|---|---|
| `GET /context/{incident_id}` | incident, evidence, zone and neighbours, actuators (own zone first) with state and quarantine, free units, `quarantined`, `related` (incidents, calls, actions in the area, last 15 min); compact JSON under 1,500 characters |
| `GET /zone/{zone_id}` | neighbours, sensors with latest value and trust, actuators that control it, units in it, open incidents |
| `GET /actuators?zone_id=` | actuators that control the zone with state and quarantine (all without `zone_id`) |
| `GET /chain/{correlation_id}` | ordered steps reading -> verdict -> call -> incident -> proposals -> decision -> action -> ack |
| `GET /graph` | nodes and edges: the city + the 20 most recent incidents and what is linked to them (for a visualization) |
| `GET /health` | node counts per kind, dropped nodes, layer status |

Unknown ids and paths answer 404 with a JSON body.

**Design choices to know:**

- **Normal readings are not stored.** The sensor node keeps its latest value; the last 5,000 readings and verdicts wait in a ring. A reading becomes a node when it is at alert level, when Guardian rejects or suspects it, or when an incident uses it (its chain start and its evidence).
- **Linked by correlation_id.** Every event is indexed by the id of the external message that started its chain. Acks carry the Brain command id, so they are linked through the action that holds that `command_id`.
- **One action node per action of a decision**; the outcomes `sent`, `acknowledged`, `failed`, `refused` update its status and history.
- **Bounded memory:** a cap per kind (`caps`), the oldest node dropped with its links; the city is never dropped.
- **Thread safety:** one lock; MQTT callbacks write, HTTP threads read. Answers take about a millisecond (test: < 100 ms).
