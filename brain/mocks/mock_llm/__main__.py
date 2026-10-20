"""Run the mock LLM: python -m mocks.mock_llm [scripted|slow|offline|invalid] (from brain/).

Same LLM service, topics and timeline events as python -m src.llm, but answers come
from the scripted backend, so no model or GPU is needed.
"""

from __future__ import annotations

import sys

from src.common import config
from src.llm.__main__ import run

from .backend import MODES, MockBackend


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else None
    if mode is not None and mode not in MODES:
        sys.exit(f"usage: python -m mocks.mock_llm [{'|'.join(MODES)}]")
    run(MockBackend(config.load("llm").get("mock", {}), mode), client_suffix="llm")


if __name__ == "__main__":
    main()
