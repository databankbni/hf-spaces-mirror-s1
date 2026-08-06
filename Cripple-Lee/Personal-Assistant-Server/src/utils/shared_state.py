"""Process-wide shared state.

This module holds the Hugging Face token and the cached agent instances in a
single, neutral location. Both the FastAPI login app and the LangGraph graph
import this module the same way (``utils.shared_state``), guaranteeing there
is only ONE copy of the state in the running process.

Do NOT store this state in ``web/login.py`` — the LangGraph server imports
that file under multiple module names, which would create duplicate module
objects each with their own independent state.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

# The Hugging Face token provided through the /login endpoint.
hf_token: Optional[str] = None

# Cached agent instances keyed by agent name.
agents: dict[str, Any] = {}

# Guards concurrent first-time initialization of the same agent.
locks: dict[str, asyncio.Lock] = {}
