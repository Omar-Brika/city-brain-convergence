"""Config overlay, secrets setup and launcher selection."""

from __future__ import annotations

import base64
import hashlib
import importlib
import importlib.util
import sys
from argparse import Namespace
from pathlib import Path

import yaml

from src.common import config

BRAIN = Path(__file__).resolve().parents[1]


def test_merge_is_deep_and_top_wins():
    base = {"backend": {"url": "a", "model": "m"}, "budget": {"answer_s": 8}, "x": [1]}
    top = {"backend": {"url": "b"}, "x": [2]}
    assert config.merge(base, top) == {"backend": {"url": "b", "model": "m"}, "budget": {"answer_s": 8}, "x": [2]}


def test_overlay_is_applied(tmp_path, monkeypatch):
    (tmp_path / "broker.yaml").write_text("host: broker\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG_OVERLAY", str(tmp_path))
    config.load.cache_clear()
    try:
        b = config.load("broker")
        assert b["host"] == "broker" and b["port"] == 8883          # port kept from the base file
    finally:
        monkeypatch.delenv("BRAIN_CONFIG_OVERLAY")
        config.load.cache_clear()


def test_docker_overlay_files_are_valid_partial_configs():
    for f in (BRAIN / "config" / "overlays" / "docker").glob("*.yaml"):
        assert (BRAIN / "config" / f.name).is_file(), f"overlay {f.name} has no base file"
        assert isinstance(yaml.safe_load(f.read_text(encoding="utf-8")), dict)


def test_mosquitto_hash_format_verifies():
    sys.path.insert(0, str(BRAIN / "tools"))
    setup = importlib.import_module("setup")
    h = setup.mosquitto_hash("s3cret")
    _, kind, iterations, salt, digest = h.split("$")
    assert kind == "7" and int(iterations) == setup.PBKDF2_ITERATIONS
    expected = hashlib.pbkdf2_hmac("sha512", b"s3cret", base64.b64decode(salt), int(iterations))
    assert base64.b64decode(digest) == expected


def test_launcher_selection():
    # loaded under its own name: scenarios/run.py is also imported as `run` by the scenario tests
    spec = importlib.util.spec_from_file_location("brain_launcher", BRAIN / "run.py")
    run = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run)
    cfg = config.load("launch")
    mods = run.select(Namespace(mock_llm=True, mocks=True, only=None, without="graph"), cfg)
    assert mods["llm"] == cfg["mock_llm"] and "twin" in mods and "graph" not in mods
    only = run.select(Namespace(mock_llm=False, mocks=False, only="input,llm", without=None), cfg)
    assert only == {"input": "src.input", "llm": "src.llm"}
