"""Twin mock service: the simulator on MQTT.

Independent of MQTT like the Brain's input module: `handle()` takes (topic, payload, retained)
and everything goes out through `publish(topic, payload, qos, retain)`, so it is testable
without a broker.

In:   brain/cmd/{target_id}   command from the Brain, sealed with the twin-brain key
      twin/control            test control (trigger / reset / contain / faults / step), same key
Out:  twin/meta, twin/status, city/{zone}/sensor/{type}/{id}, city/{zone}/call,
      twin/actuator/{id}, twin/unit/{id}, every payload sealed with the twin-brain key
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

from src.common import config
from src.common.envelope import EnvelopeError, parse_envelope, seal, verify_hmac
from src.common.log import EventLogger, utc_now_iso

from .core import Fault, SimConfig, Twin
from .messages import Mapper

Publisher = Callable[[str, str, int, bool], None]   # topic, payload, qos, retain


def build_sim_config(sim: dict[str, Any], faults: list[dict[str, Any]], now: float, run_id: str | None = None) -> SimConfig:
    epoch = datetime.fromtimestamp(now, timezone.utc) if sim.get("epoch", "now") == "now" \
        else datetime.fromisoformat(str(sim["epoch"]))
    return SimConfig(
        seed=int(sim["seed"]), run_id=run_id or str(sim["run_id"]), epoch=epoch, tick_s=float(sim["tick_s"]),
        command_delay_ticks=int(sim["command_delay_ticks"]), noise=float(sim["noise"]),
        travel_ticks=int(sim["travel_ticks"]), scene_ticks=int(sim["scene_ticks"]),
        faults=[Fault.from_dict(f) for f in faults],
    )


class TwinService:
    def __init__(
        self,
        publish: Publisher,
        *,
        key: bytes,
        clock: Callable[[], float] = time.time,
        logger: EventLogger | None = None,
        twin_cfg: dict[str, Any] | None = None,
        topics_cfg: dict[str, Any] | None = None,
    ):
        self.cfg = twin_cfg or config.load("twin-mock")
        self.topics_cfg = topics_cfg or config.load("topics")
        self._publish = publish
        self._key = key
        self.clock = clock
        self.log = logger or EventLogger("twin-mock")
        self._lock = threading.RLock()
        sim = self.cfg["sim"]
        self._resets = 0
        self.run_id = self._new_run_id()
        self.core = Twin(build_sim_config(sim, self.cfg.get("faults") or [], clock(), self.run_id))
        self.mapper = Mapper(self.topics_cfg, self.run_id, self._now_iso)
        self.max_age = float(sim["max_command_age_s"])
        self.refused = 0

    def _new_run_id(self) -> str:
        """Unique per start and per reset, so reading ids never repeat inside the Brain's replay window."""
        base = self.cfg["sim"]["run_id"]
        base = f"tw{int(self.clock())}" if base == "auto" else str(base)
        return base if self._resets == 0 else f"{base}r{self._resets}"

    # --- helpers --------------------------------------------------------------------

    def _now_iso(self) -> str:
        return datetime.fromtimestamp(self.clock(), timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def _send(self, topic: str, body: dict[str, Any], qos: int, retain: bool, tamper: list[str] | None = None) -> None:
        key = b"wrong-key-" + self._key if tamper and "bad_hmac" in tamper else self._key
        self._publish(topic, seal(body, key), qos, retain)

    def _send_outputs(self, outputs: list[dict[str, Any]]) -> None:
        for out in outputs:
            topic, body, qos, retain = self.mapper.map(out)
            self._send(topic, body, qos, retain, out.get("tamper"))

    def status_payload(self, status: str) -> str:
        """twin/status body, sealed (used for the Last Will and on every connect)."""
        return seal(self.mapper.status(status)[1], self._key)

    def subscriptions(self) -> list[tuple[str, int]]:
        return [(self.cfg["topics"]["cmd"], 1), (self.cfg["topics"]["control"], 1)]

    # --- publishing -----------------------------------------------------------------

    def on_connect(self) -> None:
        """After every (re)connect: online, then the city description (retained), then states."""
        with self._lock:
            for message in (self.mapper.status("online"), self.mapper.meta(self.core.meta())):
                self._send(*message)
            self._send_outputs(self.core.snapshot())
            self.log.info("twin_online", run_id=self.run_id, scenario=self.cfg["sim"]["scenario"])

    def tick(self) -> None:
        """One simulation step; publishes the readings, calls, acks and unit states of the tick."""
        with self._lock:
            sim = self.cfg["sim"]
            if self.core.tick == int(sim["scenario_after_ticks"]) and sim["scenario"] != "calm":
                self.core.trigger(sim["scenario"])
            self._send_outputs(self.core.step())

    # --- inputs ---------------------------------------------------------------------

    def handle(self, topic: str, payload: bytes | str, retained: bool = False) -> None:
        """Process one incoming message. Never raises."""
        if retained:
            return
        try:
            with self._lock:
                if topic == self.cfg["topics"]["control"]:
                    self._control(self._open(payload))
                elif topic.startswith("brain/cmd/"):
                    self._command(topic.removeprefix("brain/cmd/"), self._open(payload))
        except (EnvelopeError, ValueError, KeyError, TypeError) as e:
            self._refuse(topic, str(getattr(e, "detail", e)))
        except Exception as e:  # a bug must not stop the loop
            self.log.error("twin_internal_error", topic=topic, error=repr(e))

    def _open(self, payload: bytes | str) -> dict[str, Any]:
        env = parse_envelope(payload)
        verify_hmac(env, self._key, "twin")
        body = json.loads(env.body)
        if not isinstance(body, dict):
            raise ValueError("body is not a JSON object")
        return body

    def _refuse(self, topic: str, reason: str) -> None:
        self.refused += 1
        self.log.warning("message_refused", topic=topic, reason=reason)

    def _command(self, topic_target: str, body: dict[str, Any]) -> None:
        if body.get("source") != "brain":
            raise ValueError("command source must be brain")
        ts = datetime.fromisoformat(str(body["timestamp"]))
        if ts.tzinfo is None or abs(ts.timestamp() - self.clock()) > self.max_age:
            raise ValueError(f"command timestamp outside +-{self.max_age:g} s")
        target = body.get("target_id", topic_target)
        meta = self.core.meta()
        known = {a["actuator_id"] for a in meta["actuators"]} | {u["unit_id"] for u in meta["units"]}
        if target != topic_target or target not in known:
            raise ValueError(f"unknown or mismatching target {target!r}")
        if not isinstance(body.get("id"), str) or not isinstance(body.get("action"), str):
            raise ValueError("command needs string `id` and `action`")
        outputs = self.core.submit({"command_id": body["id"], "target_id": target, "action": body["action"],
                                    "parameters": body.get("parameters") or {}})
        self.log.info("command_received", correlation_id=body["id"], target_id=target, action=body["action"],
                      acknowledged=bool(outputs))
        self._send_outputs(outputs)

    def _control(self, body: dict[str, Any]) -> None:
        op = body["op"]
        if op == "trigger":
            self.core.trigger(body["scenario"])
        elif op == "contain":
            self.core.contain(body)
        elif op == "step":
            self._send_outputs(self.core.step())
        elif op in ("faults", "reset"):
            faults = body.get("faults") if op == "faults" else self.cfg.get("faults") or []
            if op == "faults":
                self.core.config.faults = [Fault.from_dict(f) for f in faults]
            else:
                self._resets += 1
                self.run_id = self._new_run_id()
                self.core.reset(build_sim_config(self.cfg["sim"], faults, self.clock(), self.run_id))
                self._send(*self.mapper.status("offline"))   # a restart: the Brain then restarts its seq counters
                self.mapper = Mapper(self.topics_cfg, self.run_id, self._now_iso)
                self.on_connect()
        else:
            raise ValueError(f"unknown control op {op!r}")
        self.log.info("control", op=op)
