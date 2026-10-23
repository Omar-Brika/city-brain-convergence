"""Strict check of the LLM answer (team doc 03-llm 4.1, 4.2).

The answer is treated as untrusted text: it may be broken JSON, name devices that
do not exist, or carry actions an injected call text asked for. Only devices and
actions of the incident context get through, at most `max_actions` of them.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any

from ..common.models import ProposalAction
from .context import Context, clean_text


@dataclass(slots=True)
class Checked:
    ok: bool
    actions: list[ProposalAction] = field(default_factory=list)
    justification: str = ""
    errors: list[str] = field(default_factory=list)     # why the answer (or an action) was refused


def extract_json(text: str) -> Any:
    """The JSON object in the answer. Tolerates a ```json fence or text around one object."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[4:] if text.lower().startswith("json") else text
    try:
        return json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(text[start:end + 1])


def check(answer: str, ctx: Context, cfg: dict[str, Any]) -> Checked:
    v = cfg["validation"]
    try:
        doc = extract_json(answer)
    except ValueError:
        return Checked(False, errors=["not_json"])
    if not isinstance(doc, dict):
        return Checked(False, errors=["not_an_object"])
    raw_actions = doc.get("actions")
    justification = doc.get("justification")
    if not isinstance(raw_actions, list):
        return Checked(False, errors=["actions_missing"])
    if not isinstance(justification, str) or not justification.strip():
        return Checked(False, errors=["justification_missing"])

    errors: list[str] = []
    actions: list[ProposalAction] = []
    seen: set[tuple[str, str]] = set()
    for i, item in enumerate(raw_actions):
        problem, action = _check_action(item, ctx, int(v["max_params"]))
        if problem:
            errors.append(f"action {i}: {problem}")
            continue
        key = (action.target_id, action.action)
        if key not in seen:
            seen.add(key)
            actions.append(action)

    if len(actions) > int(v["max_actions"]):
        errors.append(f"too_many_actions: {len(actions)} > {v['max_actions']}")
        return Checked(False, errors=errors)
    if errors and v.get("strict", True):
        return Checked(False, errors=errors)
    if not actions:
        return Checked(False, errors=errors or ["no_actions"])
    return Checked(True, actions, clean_text(justification, int(v["max_justification_chars"])), errors)


def _check_action(item: Any, ctx: Context, max_params: int) -> tuple[str | None, ProposalAction | None]:
    if not isinstance(item, dict):
        return "not_an_object", None
    target, action, params = item.get("target_id"), item.get("action"), item.get("params", {})
    if not isinstance(target, str) or not isinstance(action, str):
        return "target_or_action_missing", None
    if target in ctx.quarantined:
        return f"quarantined_target {target}", None
    known = ctx.targets.get(target)
    if known is None:
        return f"unknown_target {target}", None
    if action not in known.actions:
        return f"action_not_allowed {action} on {target}", None
    if params is None:
        params = {}
    if not isinstance(params, dict) or len(params) > max_params:
        return "bad_params", None
    clean: dict[str, str | int | float | bool] = {}
    for k, val in params.items():
        if not isinstance(k, str) or len(k) > 32 or not isinstance(val, (str, int, float, bool)):
            return "bad_params", None
        if isinstance(val, float) and not math.isfinite(val):
            return "bad_params", None
        clean[k] = clean_text(val, 64) if isinstance(val, str) else val
    return None, ProposalAction(target_id=target, action=action, params=clean)
