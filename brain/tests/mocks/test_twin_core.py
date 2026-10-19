from __future__ import annotations

import pytest

from mocks.twin.core import ACTUATORS, SCENARIOS, SENSORS, UNITS, Fault, SimConfig, Twin


def run(twin: Twin, n: int) -> list[dict]:
    out = []
    for _ in range(n):
        out += twin.step()
    return out


def readings(out, sid):
    return [o["reading"]["value"] for o in out if o["kind"] == "reading" and o["reading"]["sensor_id"] == sid]


def cmd(cid="c1", target="valve-01", action="open", parameters=None):
    return {"command_id": cid, "target_id": target, "action": action, "parameters": parameters or {}}


def test_meta_describes_every_device():
    meta = Twin().meta()
    assert {s["sensor_id"] for s in meta["sensors"]} == set(SENSORS)
    assert {a["actuator_id"] for a in meta["actuators"]} == set(ACTUATORS)
    assert {u["unit_id"] for u in meta["units"]} == set(UNITS)
    assert all(s["min"] < s["max"] for s in meta["sensors"])


def test_calm_gives_one_reading_per_sensor_and_no_calls():
    out = run(Twin(), 3)
    assert len([o for o in out if o["kind"] == "reading"]) == 3 * len(SENSORS)
    assert not [o for o in out if o["kind"] == "call"]
    assert all(abs(v - 0.4) < 0.05 for v in readings(out, "water-01"))


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_values_stay_inside_declared_ranges(scenario):
    t = Twin()
    t.trigger(scenario)
    for o in run(t, 12):
        if o["kind"] == "reading":
            r = o["reading"]
            _type, _unit, lo, hi, _ = SENSORS[r["sensor_id"]]
            assert lo <= r["value"] <= hi


def test_flood_rises_above_alert():
    t = Twin()
    t.trigger("flood")
    water = readings(run(t, 5), "water-01")
    assert water[0] > 1.3 and water == sorted(water)


def test_fire_has_particulates_and_calls_in_the_same_tick():
    t = Twin()
    t.trigger("fire")
    out = t.step()
    assert readings(out, "air-01")[0] > 200
    assert [o["category"] for o in out if o["kind"] == "call"] == ["fire"]


def test_accident_drops_traffic_after_two_ticks():
    t = Twin()
    t.trigger("accident")
    out = run(t, 4)
    speed = readings(out, "traffic-speed-01")
    assert speed[0] > 30 and speed[-1] < 10
    assert any(o["kind"] == "call" and o["category"] == "accident" for o in out)


def test_same_seed_same_output():
    a, b = Twin(SimConfig(seed=3)), Twin(SimConfig(seed=3))
    assert run(a, 5) == run(b, 5)


def test_actuator_ack_comes_after_the_delay_and_effect_follows():
    t = Twin(SimConfig(noise=0))
    base = readings(run(t, 1), "water-01")[0]
    assert t.submit(cmd(parameters={"opening": 1.0})) == []
    out = run(t, 2)
    acks = [o for o in out if o["kind"] == "actuator" and o.get("result")]
    assert len(acks) == 1 and acks[0]["result"] == "done" and acks[0]["correlation_id"] == "c1"
    assert acks[0]["state"] == "open_100"
    assert readings(out, "water-01")[-1] < base - 0.2


def test_unknown_action_and_bad_parameter_are_rejected():
    t = Twin()
    assert t.submit(cmd("c1", action="explode"))[0]["reason"] == "unknown_action"
    assert t.submit(cmd("c2", parameters={"opening": 3}))[0]["reason"] == "invalid_parameters"
    assert t.submit(cmd("c3", target="unit-fire-01", action="dispatch", parameters={"zone_id": "mars"}))[0]["reason"] == "unknown_zone"


def test_retry_with_same_id_applies_once_and_changed_payload_is_rejected():
    t = Twin()
    t.submit(cmd())
    t.submit(cmd())
    out = run(t, 3)
    assert len([o for o in out if o["kind"] == "actuator" and o.get("result") == "done"]) == 1
    retry = t.submit(cmd())
    assert retry[0]["result"] == "done"
    assert t.submit(cmd(action="close"))[0]["reason"] == "command_id_reused"


def test_lost_ack_is_recovered_by_retrying_the_same_id():
    t = Twin(SimConfig(faults=[Fault("lost_ack", 0, 20, "valve-01")]))
    t.submit(cmd())
    assert not [o for o in run(t, 3) if o["kind"] == "actuator" and o.get("result")]
    assert t.submit(cmd())[0]["result"] == "done"


@pytest.mark.parametrize("mode,result,reason", [("reject", "rejected", "scripted_rejection"), ("failure", "failed", "scripted_actuator_failure")])
def test_actuator_faults(mode, result, reason):
    t = Twin(SimConfig(faults=[Fault(mode, 0, 20, "valve-01")]))
    out = t.submit(cmd()) + run(t, 3)
    ack = [o for o in out if o["kind"] == "actuator" and o.get("result")][0]
    assert (ack["result"], ack["reason"]) == (result, reason)


def test_no_effect_acks_done_but_readings_do_not_change():
    t = Twin(SimConfig(noise=0, faults=[Fault("no_effect", 0, 20, "valve-01")]))
    t.trigger("flood")
    before = readings(run(t, 1), "water-01")[0]
    t.submit(cmd(parameters={"opening": 1}))
    out = run(t, 3)
    assert any(o.get("result") == "done" for o in out if o["kind"] == "actuator")
    assert readings(out, "water-01")[0] >= before


def test_unit_lifecycle_dispatch_to_free():
    t = Twin(SimConfig(travel_ticks=1, scene_ticks=1))
    t.submit(cmd("d1", "unit-fire-01", "dispatch", {"zone_id": "zone-01"}))
    seen = [o["status"] for o in run(t, 8) if o["kind"] == "unit" and o["unit_id"] == "unit-fire-01"]
    assert seen == ["en_route", "on_scene", "returning", "free"]


def test_busy_unit_rejects_a_second_dispatch():
    t = Twin()
    t.submit(cmd("d1", "unit-police-01", "dispatch"))
    run(t, 3)
    assert t.submit(cmd("d2", "unit-police-01", "dispatch"))[0]["reason"] == "unit_busy"


def test_fire_truck_on_scene_lowers_particulates():
    t = Twin(SimConfig(noise=0))
    t.trigger("fire")
    base = readings(run(t, 1), "air-01")[0]
    t.submit(cmd("d1", "unit-fire-01", "dispatch"))
    assert readings(run(t, 6), "air-01")[-1] < base * 0.75


def test_quarantine_stops_readings_and_blocks_commands():
    t = Twin()
    t.contain({"request_id": "q1", "device_id": "water-01", "action": "quarantine"})
    t.contain({"request_id": "q2", "device_id": "valve-01", "action": "quarantine"})
    out = run(t, 2)
    assert readings(out, "water-01") == []
    assert t.submit(cmd())[0]["reason"] == "device_unavailable"
    t.contain({"request_id": "q3", "device_id": "water-01", "action": "release"})
    assert readings(run(t, 2), "water-01")


@pytest.mark.parametrize("mode", ["malformed", "impossible", "wrong_type", "wrong_unit", "falsify", "unknown_id", "bad_hmac"])
def test_reading_faults_change_only_the_faulty_sensor(mode):
    t = Twin(SimConfig(faults=[Fault(mode, 1, 1, "water-01")]))
    out = [o["reading"] for o in t.step() if o["kind"] == "reading"]
    assert len(out) == len(SENSORS)
    clean = Twin().step()
    healthy = {o["reading"]["sensor_id"]: o["reading"] for o in clean if o["kind"] == "reading"}
    for r in out:
        if r["sensor_id"] in healthy and r["sensor_id"] != "water-01":
            assert r["value"] == healthy[r["sensor_id"]]["value"]
    assert sum(r["sensor_id"] == "water-01" for r in out) == (0 if mode == "unknown_id" else 1)


def test_missing_duplicate_and_delay():
    t = Twin(SimConfig(faults=[Fault("missing", 1, 1, "water-01"), Fault("duplicate", 1, 1, "power-01"),
                               Fault("delay", 1, 1, "air-01", delay_ticks=2)]))
    first = t.step()
    assert readings(first, "water-01") == [] and len(readings(first, "power-01")) == 2 and readings(first, "air-01") == []
    assert len(readings(run(t, 2), "air-01")) == 3   # the delayed one plus two live ones


def test_replay_resends_the_same_reading_id():
    t = Twin(SimConfig(faults=[Fault("replay", 2, 2, "water-01")]))
    first = [o for o in t.step() if o["reading"]["sensor_id"] == "water-01"][0]
    second = [o for o in t.step() if o["kind"] == "reading" and o["reading"]["sensor_id"] == "water-01"][0]
    assert first["reading"]["reading_id"] == second["reading"]["reading_id"]


def test_unknown_fault_mode_is_refused():
    with pytest.raises(ValueError):
        Fault("nope", 0)
