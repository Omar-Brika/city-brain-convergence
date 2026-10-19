"""The Twin mock against the Brain's real input module: everything the mock sends must pass
all 7 checks, and each scripted fault must be refused with the error code it is meant to trigger."""
from __future__ import annotations

import json

import pytest

from src.common.envelope import seal
from tests.mocks.conftest import TWIN_KEY


def test_connect_sends_status_meta_and_states_in_order(make_rig):
    rig = make_rig()
    rig.twin.on_connect()
    topics = [t for t, *_ in rig.twin_bus.sent]
    assert topics[:2] == ["twin/status", "twin/meta"]
    assert all(r for _, _, _, r in rig.twin_bus.sent)                      # all retained
    assert "twin/unit/unit-fire-01" in topics and "twin/actuator/valve-01" in topics
    assert rig.twin.status_payload("offline") and json.loads(json.loads(rig.twin.status_payload("offline"))["body"])["status"] == "offline"


def test_every_message_passes_the_brain_input_checks(make_rig):
    rig = make_rig(scenario="fire", scenario_after_ticks=2)
    rig.connect()
    rig.tick(10)
    assert rig.errors() == []
    assert len(rig.internal("brain/internal/reading")) == 10 * 6
    assert {c["category"] for c in rig.internal("brain/internal/call")} == {"fire"}
    assert rig.internal("brain/internal/meta")[0]["sensors"]
    assert rig.internal("brain/internal/layer-status/twin")[-1]["status"] == "online"


def test_command_is_acknowledged_and_the_brain_accepts_the_ack(make_rig):
    rig = make_rig()
    rig.connect()
    rig.command("valve-01", "open", {"opening": 0.8}, cid="brain-000042")
    rig.tick(3)
    assert rig.errors() == []
    acks = [a for a in rig.internal("brain/internal/ack") if a.get("result")]
    assert len(acks) == 1
    assert acks[0]["correlation_id"] == "brain-000042" and acks[0]["target_id"] == "valve-01"
    assert (acks[0]["result"], acks[0]["state"]) == ("done", "open_80")


def test_unit_dispatch_status_updates_reach_the_brain(make_rig):
    rig = make_rig(travel_ticks=1, scene_ticks=1)
    rig.connect()
    rig.command("unit-ambulance-01", "dispatch", {"zone_id": "zone-01"}, cid="brain-000007")
    rig.tick(8)
    assert rig.errors() == []
    statuses = [a["status"] for a in rig.internal("brain/internal/ack")
                if a["target_id"] == "unit-ambulance-01" and a.get("status")]
    assert statuses[-4:] == ["en_route", "on_scene", "returning", "free"]


@pytest.mark.parametrize("kwargs", [
    {"age_s": 60},                                # stale timestamp
])
def test_stale_command_gets_no_ack(make_rig, kwargs):
    rig = make_rig()
    rig.connect()
    rig.command("valve-01", "open", **kwargs)
    rig.tick(3)
    assert rig.twin.refused == 1
    assert not [a for a in rig.internal("brain/internal/ack") if a.get("result")]


def test_command_with_wrong_key_or_unknown_target_is_refused(make_rig):
    rig = make_rig()
    rig.connect()
    body = {"id": "x1", "timestamp": rig.clock.iso(), "source": "brain", "target_id": "valve-01", "action": "open"}
    rig.twin.handle("brain/cmd/valve-01", seal(body, b"not-the-key"))
    rig.twin.handle("brain/cmd/ghost", seal({**body, "target_id": "ghost"}, TWIN_KEY))
    rig.twin.handle("brain/cmd/valve-01", b"not json")
    assert rig.twin.refused == 3


def test_retried_command_is_acknowledged_again_not_applied_twice(make_rig):
    rig = make_rig()
    rig.connect()
    rig.command("grid-01", "shed", cid="brain-000009")
    rig.tick(3)
    rig.command("grid-01", "shed", cid="brain-000009")
    done = [a for a in rig.internal("brain/internal/ack") if a.get("result") == "done"]
    assert len(done) == 2 and done[0]["state"] == done[1]["state"] == "shed"
    assert len([e for e in rig.twin.core.events if e["kind"] == "command_application"]) == 1


# --- faults: each one must trigger the Brain check it is meant to exercise ---------------------

@pytest.mark.parametrize("mode,code", [
    ("malformed", "E_FORMAT"),
    ("wrong_type", "E_FORMAT"),
    ("wrong_unit", "E_FORMAT"),
    ("impossible", "E_RANGE"),
    ("unknown_id", "E_UNKNOWN_ID"),
    ("bad_hmac", "E_AUTH"),
    ("duplicate", "E_REPLAY"),
    ("replay", "E_REPLAY"),
])
def test_fault_is_refused_with_the_expected_code(make_rig, mode, code):
    rig = make_rig(faults=[{"mode": mode, "tick": 2, "end_tick": 2, "device_id": "water-01"}])
    rig.connect()
    rig.tick(3)
    assert [e["code"] for e in rig.errors()] == [code]


def test_old_reading_is_stale(make_rig):
    rig = make_rig(faults=[{"mode": "old", "tick": 2, "end_tick": 2, "device_id": "water-01", "delay_ticks": 2}])
    rig.connect()
    rig.tick(1)
    rig.clock.t += 20          # the Twin's tick 2 is stamped 2 s late, the Brain's clock is 20 s ahead
    rig.twin.tick()
    rig.feed()
    assert {e["code"] for e in rig.errors()} == {"E_STALE"}


def test_falsified_value_passes_the_brain_it_is_guardians_job(make_rig):
    rig = make_rig(faults=[{"mode": "falsify", "tick": 2, "end_tick": 2, "device_id": "water-01", "value": 1.8}])
    rig.connect()
    rig.tick(3)
    assert rig.errors() == []
    assert 1.8 in [r["value"] for r in rig.internal("brain/internal/reading") if r["sensor_id"] == "water-01"]


def test_control_messages_need_the_key(make_rig):
    rig = make_rig()
    rig.connect()
    rig.twin.handle("twin/control", seal({"op": "trigger", "scenario": "flood"}, b"not-the-key"))
    assert rig.twin.refused == 1
    rig.twin.handle("twin/control", seal({"op": "trigger", "scenario": "flood"}, TWIN_KEY))
    rig.tick(1)
    assert [r["value"] for r in rig.internal("brain/internal/reading") if r["sensor_id"] == "water-01"][-1] > 1.3


def test_control_reset_republishes_the_city_with_fresh_ids(make_rig):
    rig = make_rig()
    rig.connect()
    rig.tick(2)
    rig.twin.handle("twin/control", seal({"op": "reset"}, TWIN_KEY))
    rig.feed()
    rig.tick(2)
    assert rig.errors() == []
