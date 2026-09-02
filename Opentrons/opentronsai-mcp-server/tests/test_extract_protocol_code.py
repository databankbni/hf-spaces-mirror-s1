"""Unit tests for protocol extraction helpers used by the live MCP smoke script."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "test_local_mcp.py"
SPEC = importlib.util.spec_from_file_location("test_local_mcp", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def test_extract_prefers_python_fence_with_run() -> None:
    text = """
Here is a protocol:

```python
from opentrons import protocol_api

def run(protocol: protocol_api.ProtocolContext):
    tiprack = protocol.load_labware("opentrons_flex_96_tiprack_200ul", "D1")
```
"""
    code = mod.extract_protocol_code(text)
    assert "def run(" in code
    assert "load_labware" in code


def test_extract_raises_when_no_protocol() -> None:
    with pytest.raises(RuntimeError, match="Could not extract"):
        mod.extract_protocol_code("Sorry, I cannot help with that.")


def test_infra_error_detection() -> None:
    assert mod.is_simulation_success("Simulation Success: succeeded")
    assert mod.is_simulator_infra_error(
        "Simulator unavailable: HTTP 404 HTML response from https://example"
    )
    assert not mod.is_simulator_infra_error("Protocol Error: missing trash bin")
