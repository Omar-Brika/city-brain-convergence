"""Deterministic city simulator. No MQTT, no clock, no signing: it only produces messages.

Time advances only when `step()` is called. Every call that changes something returns
the list of *outputs* the transport must publish (readings, calls, acks, unit states).
Each output is a plain dict with a `kind`; `messages.py` turns them into wire bodies.

Scenario effects are small scripted perturbations, not city physics.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from random import Random
from threading import RLock
from typing import Any, Literal

ZONE = "zone-01"
ZONES = [{"zone_id": ZONE, "name": "Mock district", "type": "mixed", "exposure": "medium", "adjacent": []}]

# sensor_id: (type, unit, min, max, alert)
SENSORS = {
    "traffic-speed-01": ("traffic_speed", "km/h", 0, 200, None),
    "traffic-density-01": ("traffic_density", "vehicles/km", 0, 300, 150),
    "traffic-flow-01": ("traffic_flow", "vehicles/min", 0, 300, None),
    "water-01": ("water_level", "m", 0, 5, 1.3),
    "power-01": ("power_load", "kW", 0, 2000, None),
    "air-01": ("air_quality", "ug/m3", 0, 1000, 150),
}
# actuator_id: (type, actions)
ACTUATORS = {
    "valve-01": ("valve", ["open", "close"]),
    "signal-01": ("traffic_signal", ["normal", "priority"]),
    "grid-01": ("power_grid", ["normal", "shed"]),
}
# unit_id: type
UNITS = {"unit-fire-01": "fire_truck", "unit-ambulance-01": "ambulance", "unit-police-01": "police"}
UNIT_ACTIONS = ["dispatch", "recall"]
SCENARIOS = ("calm", "flood", "fire", "accident", "traffic-jam")

FAULT_MODES = (
    # reading faults
    "malformed", "impossible", "wrong_type", "wrong_unit", "missing", "freeze", "duplicate",
    "old", "replay", "delay", "falsify", "unknown_id", "bad_hmac",
    # actuator / unit faults
    "reject", "failure", "lost_ack", "no_effect",
)
_NOT_READING_FAULTS = {"reject", "failure", "lost_ack", "no_effect"}


class Fault:
    def __init__(self, mode: str, tick: int, end_tick: int | None = None, device_id: str | None = None,
                 delay_ticks: int = 2, value: float = 1.8):
        if mode not in FAULT_MODES:
            raise ValueError(f"unknown fault mode {mode!r}")
        if end_tick is not None and end_tick < tick:
            raise ValueError("end_tick must not precede tick")
        self.mode, self.tick, self.end_tick, self.device_id = mode, tick, end_tick, device_id
        self.delay_ticks, self.value = delay_ticks, value

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Fault":
        return cls(**d)

    def matches(self, tick: int, device_id: str | None = None) -> bool:
        last = self.end_tick if self.end_tick is not None else self.tick
        return self.tick <= tick <= last and (self.device_id is None or self.device_id == device_id)


class SimConfig:
    def __init__(self, *, seed: int = 7, run_id: str = "twin", epoch: datetime | None = None, tick_s: float = 1.0,
                 command_delay_ticks: int = 2, noise: float = 0.02, travel_ticks: int = 2, scene_ticks: int = 3,
                 faults: list[Fault] | None = None):
        self.seed, self.run_id, self.tick_s = seed, run_id, tick_s
        self.epoch = epoch or datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.command_delay_ticks, self.noise = command_delay_ticks, noise
        self.travel_ticks, self.scene_ticks = travel_ticks, scene_ticks
        self.faults = faults or []


class ConflictError(ValueError):
    pass


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


class Twin:
    def __init__(self, config: SimConfig | None = None):
        self._lock = RLock()
        self.reset(config or SimConfig())

    # --- time and logging -----------------------------------------------------------

    def timestamp(self, tick: int) -> str:
        t = self.config.epoch + timedelta(seconds=tick * self.config.tick_s)
        return t.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def emit(self, tick: int, kind: str, causal_id: str, **data: Any) -> None:
        self.events.append({"event_id": f"twin:e{len(self.events) + 1:06d}", "timestamp": self.timestamp(tick),
                            "tick": tick, "kind": kind, "causal_id": causal_id, "data": deepcopy(data)})

    # --- state ----------------------------------------------------------------------

    def reset(self, config: SimConfig | None = None) -> list[dict]:
        with self._lock:
            self.config = config or self.config
            self.tick = 0
            self._rng = Random(self.config.seed)
            self._scenario, self._trigger_tick = "calm", 0
            self._truth: dict[str, float] = {}
            self._calls: list[dict] = []
            self.events: list[dict] = []
            self._devices = {d: {"device_id": d, "status": "active", "reason": "reset"}
                             for d in (*SENSORS, *ACTUATORS, *UNITS)}
            self._act_state = {a: "default" for a in ACTUATORS}
            self._units = {u: {"status": "free", "zone_id": ZONE, "until": 0, "command": None} for u in UNITS}
            self._commands: dict[str, dict] = {}
            self._effects: dict[str, dict] = {}
            self._pending_containment: list[tuple[int, dict]] = []
            self._delayed: list[tuple[int, dict]] = []
            self._history: dict[str, dict] = {}
            self._frozen: dict[tuple, Any] = {}
            self.emit(0, "reset", self.config.run_id, seed=self.config.seed)
            return self.snapshot()

    def meta(self) -> dict[str, Any]:
        """City description (twin/meta)."""
        return {
            "zones": deepcopy(ZONES),
            "sensors": [{"sensor_id": s, "zone_id": ZONE, "type": t, "unit": u, "min": lo, "max": hi,
                         **({"alert": a} if a is not None else {})}
                        for s, (t, u, lo, hi, a) in SENSORS.items()],
            "actuators": [{"actuator_id": a, "type": t, "zone_id": ZONE, "controls": [ZONE], "actions": list(acts)}
                          for a, (t, acts) in ACTUATORS.items()],
            "units": [{"unit_id": u, "type": t, "home_zone": ZONE} for u, t in UNITS.items()],
        }

    def snapshot(self) -> list[dict]:
        """Retained states published after (re)connecting: actuator states and unit statuses."""
        with self._lock:
            out = [{"kind": "actuator", "actuator_id": a, "state": s} for a, s in self._act_state.items()]
            out += [self._unit_output(u) for u in UNITS]
            return out

    def trigger(self, scenario: str) -> None:
        with self._lock:
            if scenario not in SCENARIOS:
                raise ValueError(f"unknown scenario {scenario!r}")
            self._scenario, self._trigger_tick = scenario, self.tick
            self.emit(self.tick, "scenario_trigger", self.config.run_id, scenario=scenario)

    def _faults(self, device_id: str | None = None) -> list[Fault]:
        return [f for f in self.config.faults if f.matches(self.tick, device_id)]

    # --- commands -------------------------------------------------------------------

    def submit(self, command: dict[str, Any]) -> list[dict]:
        """Command from the Brain: {command_id, target_id, action, parameters}. Returns outputs."""
        with self._lock:
            cid = command["command_id"]
            payload = json.loads(json.dumps({k: command.get(k) for k in ("target_id", "action", "parameters")}))
            target = payload["target_id"]
            kind = "actuator" if target in ACTUATORS else "unit" if target in UNITS else None
            if cid in self._commands:
                rec = self._commands[cid]
                if rec["payload"] != payload:
                    self.emit(self.tick, "command_conflict", cid)
                    return [self._ack(kind or "actuator", target, cid, "rejected", reason="command_id_reused")]
                self.emit(self.tick, "command_retry", cid)
                return [rec["ack"]] if rec["ack"] else []
            rec = {"payload": payload, "kind": kind, "ack": None, "lost": False, "tick": self.tick,
                   "due": self.tick + self.config.command_delay_ticks, "state": "accepted",
                   "faults": {f.mode for f in self._faults(target)}}
            self._commands[cid] = rec
            self.emit(self.tick, "command_submitted", cid, command=payload)
            problem = self._validate(kind, payload)
            if problem is None and self._devices[target]["status"] != "active":
                problem = "device_unavailable"
            if problem is None and "reject" in rec["faults"]:
                problem = "scripted_rejection"
            if problem is None and kind == "unit" and payload["action"] == "dispatch" \
                    and self._units[target]["status"] != "free":
                problem = "unit_busy"
            if problem:
                rec["state"] = "rejected"
                return self._finish(cid, rec, "rejected", reason=problem)
            return []

    def _validate(self, kind: str | None, p: dict) -> str | None:
        if kind is None:
            return "unknown_target"
        action, params = p["action"], p.get("parameters") or {}
        if not isinstance(params, dict):
            return "invalid_parameters"
        if kind == "actuator":
            if action not in ACTUATORS[p["target_id"]][1]:
                return "unknown_action"
            if action == "open" and "opening" in params:
                o = params["opening"]
                if isinstance(o, bool) or not isinstance(o, (int, float)) or not 0 <= o <= 1:
                    return "invalid_parameters"
        else:
            if action not in UNIT_ACTIONS:
                return "unknown_action"
            if action == "dispatch" and params.get("zone_id", ZONE) != ZONE:
                return "unknown_zone"
        return None

    def _ack(self, kind: str, target: str, cid: str, result: str, **extra: Any) -> dict:
        out = self._unit_output(target) if kind == "unit" else {"kind": "actuator", "actuator_id": target,
                                                                "state": self._act_state.get(target)}
        out.update(correlation_id=cid, result=result, **extra)
        return out

    def _finish(self, cid: str, rec: dict, result: str, **extra: Any) -> list[dict]:
        """Build the acknowledgement; a `lost_ack` fault drops the first one (the Brain must retry)."""
        ack = self._ack(rec["kind"] or "actuator", rec["payload"]["target_id"], cid, result, **extra)
        rec["ack"] = ack
        if "lost_ack" in rec["faults"] and not rec["lost"]:
            rec["lost"] = True
            self.emit(self.tick, "acknowledgment_lost", cid)
            return []
        return [ack]

    # --- containment (harness / Guardian-driven tests) -------------------------------------

    def contain(self, request: dict[str, Any]) -> None:
        """isolate / quarantine / release a device from the next tick on."""
        with self._lock:
            device, action = request["device_id"], request["action"]
            if device not in self._devices:
                raise ValueError("unknown device")
            if action not in ("isolate", "quarantine", "release"):
                raise ValueError("unknown containment action")
            if action == "isolate" and device not in SENSORS:
                raise ValueError("isolation requires a sensor")
            self._pending_containment.append((self.tick + 1, request))
            self.emit(self.tick, "containment_scheduled", request.get("request_id", device), request=request)

    # --- one tick -------------------------------------------------------------------

    def step(self) -> list[dict]:
        with self._lock:
            self.tick += 1
            out: list[dict] = []
            for due, req in self._pending_containment[:]:
                if due <= self.tick:
                    state = {"isolate": "isolated", "quarantine": "quarantined", "release": "active"}[req["action"]]
                    self._devices[req["device_id"]].update(status=state, reason=req.get("reason", "containment"))
                    self._pending_containment.remove((due, req))
                    self.emit(self.tick, "containment_applied", req.get("request_id", req["device_id"]), device_id=req["device_id"], status=state)
            for cid, rec in self._commands.items():
                if rec["state"] == "accepted" and rec["due"] <= self.tick:
                    out += self._apply(cid, rec)
            out += self._advance_units()
            self._generate_truth()
            for due, reading in self._delayed[:]:
                if due <= self.tick:
                    out += self._deliver(reading)
                    self._delayed.remove((due, reading))
            for sid, (kind, unit, _lo, _hi, _alert) in SENSORS.items():
                out += self._sense(sid, kind, unit)
            out += self._calls
            self.emit(self.tick, "tick_completed", self.config.run_id)
            return out

    def _apply(self, cid: str, rec: dict) -> list[dict]:
        p = rec["payload"]
        target, action, params = p["target_id"], p["action"], p.get("parameters") or {}
        if self._devices[target]["status"] != "active":
            rec["state"] = "failed"
            return self._finish(cid, rec, "failed", reason="device_unavailable_at_application")
        if "failure" in rec["faults"]:
            rec["state"] = "failed"
            return self._finish(cid, rec, "failed", reason="scripted_actuator_failure")
        rec["state"] = "applied"
        effective = "no_effect" not in rec["faults"]
        if rec["kind"] == "actuator":
            if action == "open":
                self._act_state[target] = f"open_{round(float(params.get('opening', 1.0)) * 100)}"
            elif action == "close":
                self._act_state[target] = "closed"
            else:
                self._act_state[target] = action
            if effective:
                self._effects[cid] = {"target": target, "action": action, "parameters": params}
        else:
            u = self._units[target]
            if action == "dispatch":
                u.update(status="en_route", zone_id=params.get("zone_id", ZONE),
                         until=self.tick + self.config.travel_ticks, command=cid if effective else None)
            elif u["status"] != "free":
                u.update(status="returning", until=self.tick + self.config.travel_ticks, command=None)
        self.emit(self.tick, "command_application", cid, effective=effective)
        return self._finish(cid, rec, "done")

    def _advance_units(self) -> list[dict]:
        out = []
        for uid, u in self._units.items():
            if u["status"] == "free" or u["until"] > self.tick:
                continue
            if u["status"] == "en_route":
                u.update(status="on_scene", until=self.tick + self.config.scene_ticks)
                if u["command"]:
                    self._effects[u["command"]] = {"target": uid, "action": "dispatch", "parameters": {}}
            elif u["status"] == "on_scene":
                u.update(status="returning", until=self.tick + self.config.travel_ticks)
            else:
                u.update(status="free", zone_id=ZONE, command=None)
            self.emit(self.tick, "unit_state", uid, status=u["status"])
            out.append(self._unit_output(uid))
        return out

    def _unit_output(self, uid: str) -> dict:
        u = self._units[uid]
        return {"kind": "unit", "unit_id": uid, "status": u["status"], "zone_id": u["zone_id"]}

    # --- readings -------------------------------------------------------------------

    def _sense(self, sid: str, kind: str, unit: str) -> list[dict]:
        if self._devices[sid]["status"] != "active":
            self.emit(self.tick, "reading_suppressed", sid, reason="device_unavailable")
            return []
        rid = f"{self.config.run_id}-{sid}-{self.tick:06d}"
        reading = {"reading_id": rid, "sensor_id": sid, "zone_id": ZONE, "type": kind, "value": self._truth[sid],
                   "unit": unit, "origin": "simulated", "tick": self.tick, "sequence": self.tick,
                   "observed_at": self.timestamp(self.tick)}
        dropped, delay, duplicate, tamper = False, None, False, []
        for fault in self._faults(sid):
            if fault.mode in _NOT_READING_FAULTS:
                continue
            self.emit(self.tick, "reading_fault", rid, mode=fault.mode, sensor_id=sid)
            if fault.mode == "malformed": reading.pop("value", None)
            elif fault.mode == "impossible": reading["value"] = -999.0
            elif fault.mode == "wrong_type": reading["value"] = "not-a-number"
            elif fault.mode == "wrong_unit": reading["unit"] = "bananas"
            elif fault.mode == "falsify": reading["value"] = fault.value
            elif fault.mode == "unknown_id": reading["sensor_id"] = "ghost-01"
            elif fault.mode == "bad_hmac": tamper.append("bad_hmac")
            elif fault.mode == "missing": dropped = True
            elif fault.mode == "freeze":
                key = (sid, fault.tick)
                if key not in self._frozen:
                    self._frozen[key] = self._history.get(sid, reading).get("value")
                reading["value"] = self._frozen[key]
            elif fault.mode == "duplicate": duplicate = True
            elif fault.mode == "old":
                old = max(0, self.tick - fault.delay_ticks)
                reading.update(observed_at=self.timestamp(old), sequence=old)
            elif fault.mode == "replay":
                if sid in self._history: reading = deepcopy(self._history[sid])
                else: dropped = True
            elif fault.mode == "delay": delay = fault.delay_ticks
        self._history[sid] = deepcopy(reading)
        item = {"kind": "reading", "reading": reading, "tamper": tamper}
        if dropped:
            self.emit(self.tick, "reading_dropped", rid)
            return []
        if delay:
            self._delayed.append((self.tick + delay, item))
            if duplicate: self._delayed.append((self.tick + delay, deepcopy(item)))
            self.emit(self.tick, "reading_delivery_scheduled", rid, due_tick=self.tick + delay)
            return []
        return self._deliver(item) * (2 if duplicate else 1)

    def _deliver(self, item: dict) -> list[dict]:
        sid = item["reading"]["sensor_id"]
        if sid in self._devices and self._devices[sid]["status"] != "active":
            self.emit(self.tick, "reading_suppressed", item["reading"]["reading_id"], reason="contained_before_delivery")
            return []
        self.emit(self.tick, "reading_delivered", item["reading"]["reading_id"], applied_command_ids=list(self._effects))
        return [deepcopy(item)]

    def _generate_truth(self) -> None:
        def jitter(base: float) -> float:
            return round(base * (1 + self._rng.uniform(-self.config.noise, self.config.noise)), 3)

        speed, density, flow, water, power, air = 45., 30., 25., .4, 500., 12.
        self._calls = []
        age = self.tick - self._trigger_tick

        def call(category: str) -> dict:
            return {"kind": "call", "call_id": f"call-{self.tick:06d}", "zone_id": ZONE, "category": category,
                    "text": f"{category} reported in {ZONE}", "tick": self.tick}

        if self._scenario == "flood":
            water = min(2.5, 1.4 + age * .15)
        elif self._scenario == "fire":
            air, power = 250., 650.
            self._calls = [call("fire")]
        elif self._scenario == "accident" and age >= 2:
            speed, density, flow = 5., 160., 2.
            self._calls = [call("accident")]
        elif self._scenario == "traffic-jam":
            speed, density, flow = 7., 180., 4.
        for e in self._effects.values():
            t, a, p = e["target"], e["action"], e["parameters"]
            if t in ACTUATORS and a == "open": water = max(.1, water - .3 * float(p.get("opening", 1.0)))
            elif t in ACTUATORS and a == "priority": speed, flow = speed + 8., flow + 5.
            elif t in ACTUATORS and a == "shed": power *= .85
            elif t in UNITS and UNITS[t] == "fire_truck": air *= .7
            elif t in UNITS: speed, flow = speed + 5., flow + 3.
        values = {"traffic-speed-01": speed, "traffic-density-01": density, "traffic-flow-01": flow,
                  "water-01": water, "power-01": power, "air-01": air}
        self._truth = {s: _clamp(jitter(v), SENSORS[s][2], SENSORS[s][3]) for s, v in values.items()}
