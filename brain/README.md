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
