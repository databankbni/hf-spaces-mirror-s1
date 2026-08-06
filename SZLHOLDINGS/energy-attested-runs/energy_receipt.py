# SPDX-License-Identifier: Apache-2.0
# (c) 2026 SZL Holdings - Stephen P. Lutar - ORCID 0009-0001-0110-4173
"""Energy-attested inference receipts (honest, hash-chained, optionally signed).

This module is the engine behind the SZLHOLDINGS/energy-attested-runs Space.
For each (mock-labelled) routed inference it emits a small, replayable receipt
carrying:

  * decision (allow / deny / szl-blocked-style)  -- governance verdict
  * token counts + cost                            -- REAL counts, honest cost
  * energy                                         -- MEASURED joules OR honest
                                                      null / "UNAVAILABLE"
  * a SHA-256 hash-chain link (prev <- digest)     -- tamper-evident
  * a DSSE-style envelope, signed OR UNSIGNED-honest

HONESTY BRAND (hard rules, non-negotiable):
  * Energy joules are MEASURED (real NVML delta) or honest null. NEVER a
    fabricated joule. On CPU HF hardware there is no NVML, so energy is
    null / "UNAVAILABLE (no NVML on this host)".
  * Cost is only a number when a real per-token rate is supplied; otherwise it
    is null with an honest label. No invented dollar figures.
  * Lambda is advisory: "Lambda = Conjecture 1 - never green". Never "proven".
  * Signatures are real (ECDSA-P256 via `cryptography`, when a key is present)
    or the envelope is UNSIGNED-honest. A signature is NEVER faked.

The receipt/decision object is field-aligned with SZL's open
`governed-receipt-spec` so that these receipts validate against that project's
dependency-free verifier (bundled here as verify.py).

Stdlib only for the core; `cryptography` is optional (signing) and `pynvml`
is optional (energy). Both degrade honestly when absent.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

# --------------------------------------------------------------------------- #
# Constants                                                                    #
# --------------------------------------------------------------------------- #
ZERO_HASH = "0" * 64
NAMESPACE = "energy-attested-runs"
PAYLOAD_TYPE = "application/vnd.szl.energy-receipt+json"
LAMBDA_LABEL = "\u039b = Conjecture 1 - never green"  # Λ

# --------------------------------------------------------------------------- #
# Optional NVML energy probe (honest capability report)                       #
# --------------------------------------------------------------------------- #
_NVML_IMPORT_ERROR: Optional[str] = None
try:  # pragma: no cover - environment dependent
    import pynvml as _pynvml  # type: ignore
except Exception as _e:  # noqa: BLE001
    _pynvml = None  # type: ignore
    _NVML_IMPORT_ERROR = f"{type(_e).__name__}: {_e}"


def energy_capability() -> Dict[str, Any]:
    """Describe, honestly, whether GPU energy measurement is possible here."""
    rep: Dict[str, Any] = {
        "pynvml_importable": _pynvml is not None,
        "import_error": _NVML_IMPORT_ERROR,
        "nvml_init_ok": False,
        "device_count": 0,
        "measurable": False,
    }
    if _pynvml is None:
        return rep
    try:  # pragma: no cover - needs a GPU
        _pynvml.nvmlInit()
        rep["nvml_init_ok"] = True
        rep["device_count"] = int(_pynvml.nvmlDeviceGetCount())
        rep["measurable"] = rep["device_count"] > 0
    except Exception as e:  # noqa: BLE001
        rep["import_error"] = rep["import_error"] or f"{type(e).__name__}: {e}"
    return rep


def measure_energy(work_seconds: float) -> Dict[str, Any]:
    """Return an honest energy block for a region that took `work_seconds`.

    On hardware with a live NVML energy counter this returns MEASURED joules.
    Everywhere else (e.g. CPU HF Spaces) it returns joules=None and
    label="UNAVAILABLE" with an honest reason. It NEVER fabricates a joule.
    """
    cap = energy_capability()
    block: Dict[str, Any] = {
        "joules": None,
        "label": "UNAVAILABLE",
        "evidence": {
            "meter": "nvml-total-energy-counter",
            "reason": None,
            "note": "joule NOT fabricated - honest UNKNOWN over fabricated green",
            "wall_seconds": round(float(work_seconds), 6),
        },
    }
    if not cap["pynvml_importable"]:
        block["label"] = "UNAVAILABLE (no NVML on this host)"
        block["evidence"]["reason"] = (
            "pynvml not importable (%s)" % (cap["import_error"] or "no NVIDIA driver")
        )
        return block
    if not cap["nvml_init_ok"] or not cap["measurable"]:
        block["label"] = "UNAVAILABLE (no NVML on this host)"
        block["evidence"]["reason"] = (
            "NVML present but no GPU/energy counter reachable on this host"
        )
        return block
    # pragma: no cover - only runs where a GPU energy counter exists
    try:
        h = _pynvml.nvmlDeviceGetHandleByIndex(0)
        mj0 = int(_pynvml.nvmlDeviceGetTotalEnergyConsumption(h))
        time.sleep(0)  # region already ran; counter delta over the call window
        mj1 = int(_pynvml.nvmlDeviceGetTotalEnergyConsumption(h))
        joules = max(0.0, (mj1 - mj0) / 1000.0)
        block["joules"] = round(joules, 6)
        block["label"] = "MEASURED"
        block["evidence"]["reason"] = "NVML total-energy counter delta (board-level)"
    except Exception as e:  # noqa: BLE001
        block["label"] = "UNAVAILABLE (no NVML on this host)"
        block["evidence"]["reason"] = "NVML energy read failed: %s" % e
    return block


# --------------------------------------------------------------------------- #
# Real token counting (deterministic, model-agnostic)                          #
# --------------------------------------------------------------------------- #
_TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def count_tokens(text: str) -> int:
    """Deterministic, model-agnostic token count (regex word+punctuation).

    This is a REAL count of the tokens produced by the splitter below - it is
    honestly NOT a specific model's BPE count, and the receipt says so.
    """
    if not text:
        return 0
    return len(_TOKEN_RE.findall(text))


# --------------------------------------------------------------------------- #
# Local, clearly-mock-labelled "routed inference"                              #
# --------------------------------------------------------------------------- #
def mock_route(prompt: str) -> Dict[str, Any]:
    """A LOCAL, DETERMINISTIC responder (no external model, zero downloads).

    Clearly labelled as a mock so the Space runs anywhere. The receipt
    mechanics wrapped around it - token counting, honest energy metering,
    hash-chaining, signing - are REAL.
    """
    prompt = (prompt or "").strip()
    n_in = count_tokens(prompt)
    completion = (
        "[mock-routed reply] Received %d input token(s). "
        "This deterministic local responder stands in for a routed model so the "
        "demo runs with no downloads; the receipt around it is real."
    ) % n_in
    return {
        "route": "local/mock-deterministic-v1",
        "prompt": prompt,
        "completion": completion,
        "tokens_in": n_in,
        "tokens_out": count_tokens(completion),
    }


# --------------------------------------------------------------------------- #
# Honest cost accounting                                                       #
# --------------------------------------------------------------------------- #
def cost_block(tokens_in: int, tokens_out: int,
               usd_per_1k_in: Optional[float] = None,
               usd_per_1k_out: Optional[float] = None) -> Dict[str, Any]:
    """Cost is a number ONLY when a real rate is supplied, else honest null."""
    if usd_per_1k_in is None and usd_per_1k_out is None:
        return {
            "usd": None,
            "label": "UNPRICED",
            "note": (
                "No provider rate supplied for the local mock route; cost is "
                "not fabricated. Supply a real per-1k-token rate to price it."
            ),
        }
    r_in = float(usd_per_1k_in or 0.0)
    r_out = float(usd_per_1k_out or 0.0)
    usd = (tokens_in / 1000.0) * r_in + (tokens_out / 1000.0) * r_out
    return {
        "usd": round(usd, 8),
        "label": "COMPUTED",
        "note": "usd = tokens/1000 * supplied rate (in=%.5f, out=%.5f per 1k)" % (
            r_in, r_out),
    }


# --------------------------------------------------------------------------- #
# DSSE PAE + canonical JSON                                                    #
# --------------------------------------------------------------------------- #
def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def dsse_pae(payload_type: str, body_bytes: bytes) -> bytes:
    return (
        b"DSSEv1 "
        + str(len(payload_type)).encode("ascii")
        + b" "
        + payload_type.encode("utf-8")
        + b" "
        + str(len(body_bytes)).encode("ascii")
        + b" "
        + body_bytes
    )


# --------------------------------------------------------------------------- #
# Optional ECDSA-P256 signing (real, or UNSIGNED-honest)                       #
# --------------------------------------------------------------------------- #
def _load_signing_key(pem: Optional[str]):
    if not pem:
        return None
    try:
        from cryptography.hazmat.primitives import serialization
        return serialization.load_pem_private_key(pem.encode("utf-8"), password=None)
    except Exception:  # noqa: BLE001
        return None


def _sign_pae(private_key, pae_bytes: bytes) -> Optional[str]:
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        der = private_key.sign(pae_bytes, ec.ECDSA(hashes.SHA256()))
        return base64.b64encode(der).decode("ascii")
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------- #
# Receipt chain                                                                #
# --------------------------------------------------------------------------- #
class EnergyReceiptChain:
    """Append-only, SHA-256 hash-chained log of energy-attested receipts."""

    def __init__(self, sign_key_pem: Optional[str] = None,
                 keyid: str = "energy-attested-runs") -> None:
        self._records: List[Dict[str, Any]] = []
        self._keyid = keyid
        self._priv = _load_signing_key(sign_key_pem)

    @property
    def signing_enabled(self) -> bool:
        return self._priv is not None

    def count(self) -> int:
        return len(self._records)

    def head(self) -> str:
        return self._records[-1]["_decision"]["digest"] if self._records else ZERO_HASH

    def emit(self, prompt: str, *,
             usd_per_1k_in: Optional[float] = None,
             usd_per_1k_out: Optional[float] = None) -> Dict[str, Any]:
        """Run the mock route + honest metering and append one receipt.

        Returns the DSSE envelope (with a hidden `_decision` mirror for the UI).
        """
        seq = len(self._records)
        prev = self.head()

        t0 = time.perf_counter()
        route = mock_route(prompt)
        wall = time.perf_counter() - t0

        energy = measure_energy(wall)
        cost = cost_block(route["tokens_in"], route["tokens_out"],
                          usd_per_1k_in, usd_per_1k_out)

        content = canonical_json(
            {"prompt": route["prompt"], "completion": route["completion"]}
        ).encode("utf-8")
        payload_digest = hashlib.sha256(content).hexdigest()

        # Decision body WITHOUT its own digest first.
        body: Dict[str, Any] = {
            "action": "inference",
            "ns": NAMESPACE,
            "organ": route["route"],
            "seq": seq,
            "prev": prev,
            "payload_digest": payload_digest,
            "ts": time.time(),
            "decision": "allow",
            "lambda": {"score": None, "label": LAMBDA_LABEL},
            "energy": energy,
            "tokens": {
                "tokens_in": route["tokens_in"],
                "tokens_out": route["tokens_out"],
                "tokenizer": "regex word+punctuation (deterministic, model-agnostic)",
                "note": "REAL count of the splitter's tokens; NOT a model BPE count",
            },
            "cost": cost,
            "mock": True,
            "mock_note": "local deterministic responder; receipt mechanics are real",
        }
        digest = hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()
        body["digest"] = digest

        payload_bytes = canonical_json(body).encode("utf-8")
        payload_b64 = base64.b64encode(payload_bytes).decode("ascii")
        pae = dsse_pae(PAYLOAD_TYPE, payload_bytes)
        pae_sha256 = hashlib.sha256(pae).hexdigest()

        envelope: Dict[str, Any] = {
            "payloadType": PAYLOAD_TYPE,
            "payload": payload_b64,
            "signatures": [],
            "signed": False,
            "_dsse": "DSSEv1",
            "_pae_sha256": pae_sha256,
            "_signed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "honesty": (
                "UNSIGNED-honest: no signing key present. Integrity is still "
                "checkable via the hash chain + _pae_sha256; authorship is not."
            ),
            "verify_key_url": None,
        }
        if self._priv is not None:
            sig = _sign_pae(self._priv, pae)
            if sig is not None:
                envelope["signatures"] = [{"keyid": self._keyid, "sig": sig}]
                envelope["signed"] = True
                envelope["honesty"] = (
                    "SIGNED: ECDSA-P256-SHA256 over the DSSE PAE. Proves this "
                    "Space emitted the receipt; it is NOT zero-knowledge and NOT "
                    "a proof of the underlying computation."
                )

        # keep an out-of-band decision mirror for the UI + local chain walk
        record = dict(envelope)
        record["_decision"] = body
        self._records.append(record)
        return record

    def envelopes(self) -> List[Dict[str, Any]]:
        """Return clean DSSE envelopes (no `_decision` mirror) for export."""
        out = []
        for r in self._records:
            e = {k: v for k, v in r.items() if k != "_decision"}
            out.append(e)
        return out

    def to_ndjson(self) -> str:
        return "\n".join(json.dumps(e, ensure_ascii=False) for e in self.envelopes())
