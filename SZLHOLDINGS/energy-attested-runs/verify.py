#!/usr/bin/env python3
"""Offline verifier for SZL Governed Inference Receipts.

Dependency-free (Python standard library only). No third-party packages, no
network access. Verifies receipts published by the SZL Holdings estate
(e.g. SZLHOLDINGS/a11oy-verifiable-corpus, SZLHOLDINGS/readiness-runs,
SZLHOLDINGS/szl-evidence).

For each receipt the verifier:
  (a) validates the decoded decision object against schema/governed-receipt.schema.json,
  (b) recomputes the content hash and checks it:
        - DSSE receipts: sha256(PAE) == envelope._pae_sha256 (== receipt_uid),
        - readiness receipts: sha256(payload bytes) == payloadSha256,
  (c) checks the prev-hash chain across a receipt list (prev == previous.digest,
      genesis prev is 64 zeros, seq increments), and
  (d) structurally checks the DSSE envelope.

It prints a clear PASS / FAIL per receipt and per file with reasons.

Honesty note: this verifier does NOT re-derive the runtime's internal `digest`
(that serialization is internal to the emitting runtime). It verifies the
relations that an outside party can independently reproduce: the DSSE PAE
content hash, the payload-bytes hash, and the prev<->digest chain. A receipt is
an honest, replayable audit record -- it is NOT a zero-knowledge proof.

Usage:
    python verify.py <receipt.json> [<receipt2.json> ...]
    python verify.py --schema schema/governed-receipt.schema.json examples/*.json
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys

ZERO_HASH = "0" * 64
DEFAULT_SCHEMA = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "schema",
    "governed-receipt.schema.json",
)


# --------------------------------------------------------------------------- #
# Minimal JSON Schema (draft 2020-12) validator                               #
# Covers the keyword subset used by governed-receipt.schema.json:             #
# type, required, properties, additionalProperties, enum, const, pattern,     #
# minimum, items, oneOf, anyOf, $ref / $defs, and nullable via type arrays.   #
# --------------------------------------------------------------------------- #
class SchemaError(Exception):
    pass


def _type_ok(value, t):
    if t == "object":
        return isinstance(value, dict)
    if t == "array":
        return isinstance(value, list)
    if t == "string":
        return isinstance(value, str)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "null":
        return value is None
    raise SchemaError("unknown type in schema: %r" % t)


def _resolve_ref(ref, root):
    if not ref.startswith("#/"):
        raise SchemaError("only local #/ refs are supported: %r" % ref)
    node = root
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        node = node[part]
    return node


def validate(value, schema, root=None, path="$", errors=None):
    """Return a list of error strings (empty == valid)."""
    if root is None:
        root = schema
    if errors is None:
        errors = []

    if "$ref" in schema:
        schema = _resolve_ref(schema["$ref"], root)

    # type
    if "type" in schema:
        types = schema["type"]
        if isinstance(types, str):
            types = [types]
        if not any(_type_ok(value, t) for t in types):
            errors.append("%s: expected type %s, got %s"
                          % (path, "|".join(types), type(value).__name__))
            return errors  # further checks are meaningless

    # const / enum
    if "const" in schema and value != schema["const"]:
        errors.append("%s: must equal const %r" % (path, schema["const"]))
    if "enum" in schema and value not in schema["enum"]:
        errors.append("%s: %r not in enum %r" % (path, value, schema["enum"]))

    # oneOf / anyOf
    if "oneOf" in schema:
        matches = sum(
            1 for sub in schema["oneOf"]
            if not validate(value, sub, root, path, [])
        )
        if matches != 1:
            errors.append("%s: matched %d of oneOf branches (need exactly 1)"
                          % (path, matches))
    if "anyOf" in schema:
        if not any(not validate(value, sub, root, path, [])
                   for sub in schema["anyOf"]):
            errors.append("%s: matched none of anyOf branches" % path)

    # strings
    if isinstance(value, str):
        pat = schema.get("pattern")
        if pat is not None and re.search(pat, value) is None:
            errors.append("%s: %r does not match pattern %r" % (path, value, pat))

    # numbers
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append("%s: %r < minimum %r" % (path, value, schema["minimum"]))

    # objects
    if isinstance(value, dict):
        for req in schema.get("required", []):
            if req not in value:
                errors.append("%s: missing required property %r" % (path, req))
        props = schema.get("properties", {})
        for key, sub in props.items():
            if key in value:
                validate(value[key], sub, root, "%s.%s" % (path, key), errors)
        addl = schema.get("additionalProperties", True)
        if addl is False:
            for key in value:
                if key not in props:
                    errors.append("%s: additional property %r not allowed"
                                  % (path, key))
        elif isinstance(addl, dict):
            for key in value:
                if key not in props:
                    validate(value[key], addl, root,
                             "%s.%s" % (path, key), errors)

    # arrays
    if isinstance(value, list):
        items = schema.get("items")
        if isinstance(items, dict) and items:
            for i, item in enumerate(value):
                validate(item, items, root, "%s[%d]" % (path, i), errors)

    return errors


# --------------------------------------------------------------------------- #
# Receipt loading & shape extraction                                          #
# --------------------------------------------------------------------------- #
def load_records(path):
    """Load one path into a list of top-level records.

    Supports a single JSON object, a JSON array, or NDJSON (one JSON per line).
    """
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    text_stripped = text.strip()
    if not text_stripped:
        return []
    try:
        data = json.loads(text_stripped)
        return data if isinstance(data, list) else [data]
    except json.JSONDecodeError:
        records = []
        for line in text_stripped.splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))
        return records


def _find_envelope(record):
    """Locate the DSSE / signed envelope inside a record, if any."""
    if isinstance(record, dict):
        if "payloadType" in record and "payload" in record and isinstance(
            record.get("payload"), str
        ):
            return record
        payload = record.get("payload")
        if isinstance(payload, dict):
            for key in ("envelope", "dsse"):
                env = payload.get(key)
                if isinstance(env, dict) and "payloadType" in env:
                    return env
        for key in ("envelope", "dsse"):
            env = record.get(key)
            if isinstance(env, dict) and "payloadType" in env:
                return env
    return None


def _decode_envelope_payload(envelope):
    try:
        raw = base64.b64decode(envelope["payload"])
    except Exception as exc:  # noqa: BLE001
        return None, "payload is not valid base64 (%s)" % exc
    try:
        return json.loads(raw.decode("utf-8")), None
    except Exception as exc:  # noqa: BLE001
        return None, "decoded payload is not valid JSON (%s)" % exc


def extract_decision(record, envelope):
    """Return (decision_object, note).

    The decision object is what the schema describes. For lake receipts the
    governance fields are already in the clear on `payload`; for khipu receipts
    they live in the base64 DSSE payload; flat DSSE receipts carry them in the
    decoded payload too.
    """
    if isinstance(record, dict):
        payload = record.get("payload")
        if isinstance(payload, dict) and "seq" in payload and "prev" in payload:
            return payload, "decision fields read from record.payload (lake form)"
    if envelope is not None:
        decoded, err = _decode_envelope_payload(envelope)
        if decoded is not None:
            return decoded, "decision fields decoded from DSSE envelope payload"
        return None, err or "could not decode envelope payload"
    if isinstance(record, dict) and "seq" in record and "prev" in record:
        return record, "record is already a decoded decision object"
    return record if isinstance(record, dict) else None, "no envelope; using record as-is"


def is_inference_receipt(decision):
    return (
        isinstance(decision, dict)
        and "seq" in decision
        and "prev" in decision
        and "digest" in decision
    )


# --------------------------------------------------------------------------- #
# Content-hash & DSSE checks                                                   #
# --------------------------------------------------------------------------- #
def dsse_pae(payload_type, body_bytes):
    """DSSE Pre-Authentication Encoding."""
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


def check_content_hash(record, envelope):
    """Recompute and check the content hash. Returns (ok, message)."""
    if envelope is not None:
        try:
            body = base64.b64decode(envelope["payload"])
        except Exception as exc:  # noqa: BLE001
            return False, "envelope payload not base64: %s" % exc
        ptype = envelope.get("payloadType", "")
        # DSSE PAE hash
        if "_pae_sha256" in envelope:
            got = hashlib.sha256(dsse_pae(ptype, body)).hexdigest()
            want = envelope["_pae_sha256"]
            if got != want:
                return False, ("DSSE PAE sha256 mismatch: recomputed %s != _pae_sha256 %s"
                               % (got, want))
            # receipt_uid, when present, must equal the PAE hash
            uid = None
            if isinstance(record, dict) and isinstance(record.get("payload"), dict):
                uid = record["payload"].get("receipt_uid")
            if uid is not None and uid != got:
                return False, ("receipt_uid %s != recomputed PAE hash %s" % (uid, got))
            return True, "DSSE PAE sha256 verified (%s)" % got[:16]
        # readiness form: sha256 over raw payload bytes
        if "payloadSha256" in envelope:
            got = hashlib.sha256(body).hexdigest()
            want = envelope["payloadSha256"]
            if got != want:
                return False, ("payloadSha256 mismatch: recomputed %s != %s" % (got, want))
            return True, "payloadSha256 verified (%s)" % got[:16]
        return True, "no content-hash field present on envelope (n/a)"
    return True, "no DSSE/signed envelope (n/a)"


def check_dsse_structure(envelope):
    """Structural checks on a DSSE envelope. Returns (ok, message)."""
    if envelope is None:
        return True, "no envelope to check (n/a)"
    problems = []
    ptype = envelope.get("payloadType")
    if not isinstance(ptype, str) or not ptype:
        problems.append("payloadType missing/empty")
    if not isinstance(envelope.get("payload"), str):
        problems.append("payload missing/not a string")
    else:
        try:
            base64.b64decode(envelope["payload"])
        except Exception:  # noqa: BLE001
            problems.append("payload not base64-decodable")
    sigs = envelope.get("signatures")
    if not isinstance(sigs, list):
        problems.append("signatures missing/not a list")
        sigs = []
    signed = envelope.get("signed")
    if signed is True:
        if not sigs:
            problems.append("signed=true but signatures is empty")
        for i, s in enumerate(sigs):
            if not isinstance(s, dict) or "sig" not in s:
                problems.append("signature[%d] missing 'sig'" % i)
    if problems:
        return False, "; ".join(problems)
    kind = "signed" if signed else "unsigned"
    return True, "DSSE envelope well-formed (%s, %d signature(s))" % (kind, len(sigs))


# --------------------------------------------------------------------------- #
# Chain check                                                                  #
# --------------------------------------------------------------------------- #
def check_chain(decisions):
    """Check the prev-hash chain across an ordered list of decision objects.

    Returns (ok, [messages]).
    """
    msgs = []
    ok = True
    chainable = [d for d in decisions if isinstance(d, dict) and "prev" in d and "digest" in d]
    if len(chainable) < 1:
        return True, ["no chainable receipts (n/a)"]
    # order by seq when available
    if all("seq" in d for d in chainable):
        chainable = sorted(chainable, key=lambda d: d["seq"])
    first = chainable[0]
    if first.get("seq") == 0 and first.get("prev") != ZERO_HASH:
        ok = False
        msgs.append("genesis (seq 0) prev must be 64 zeros, got %s" % first.get("prev"))
    for i in range(1, len(chainable)):
        prev_rec = chainable[i - 1]
        cur = chainable[i]
        if cur.get("prev") != prev_rec.get("digest"):
            ok = False
            msgs.append(
                "seq %s prev %s != seq %s digest %s"
                % (cur.get("seq"), cur.get("prev"),
                   prev_rec.get("seq"), prev_rec.get("digest"))
            )
        if "seq" in cur and "seq" in prev_rec and cur["seq"] != prev_rec["seq"] + 1:
            ok = False
            msgs.append("seq not contiguous: %s follows %s"
                        % (cur["seq"], prev_rec["seq"]))
    if ok:
        msgs.append("hash chain intact across %d receipt(s)" % len(chainable))
    return ok, msgs


# --------------------------------------------------------------------------- #
# Top-level verification                                                       #
# --------------------------------------------------------------------------- #
def verify_records(records, schema):
    """Verify a list of records. Returns (ok, report_lines)."""
    lines = []
    ok = True
    decisions = []
    for idx, record in enumerate(records):
        tag = "receipt[%d]" % idx
        envelope = _find_envelope(record)
        decision, note = extract_decision(record, envelope)
        lines.append("- %s: %s" % (tag, note))

        # (d) DSSE structure
        s_ok, s_msg = check_dsse_structure(envelope)
        ok = ok and s_ok
        lines.append("    dsse:   %s %s" % ("PASS" if s_ok else "FAIL", s_msg))

        # (b) content hash
        h_ok, h_msg = check_content_hash(record, envelope)
        ok = ok and h_ok
        lines.append("    hash:   %s %s" % ("PASS" if h_ok else "FAIL", h_msg))

        # (a) schema (inference receipts only)
        if is_inference_receipt(decision):
            errs = validate(decision, schema)
            v_ok = not errs
            ok = ok and v_ok
            if v_ok:
                lines.append("    schema: PASS validates governed-receipt.schema.json")
            else:
                lines.append("    schema: FAIL")
                for e in errs:
                    lines.append("            - %s" % e)
            decisions.append(decision)
        else:
            lines.append("    schema: SKIP non-inference receipt "
                         "(envelope + hash checks only)")

    # (c) chain across inference receipts
    c_ok, c_msgs = check_chain(decisions)
    ok = ok and c_ok
    for m in c_msgs:
        lines.append("- chain: %s %s" % ("PASS" if c_ok else "FAIL", m))
    return ok, lines


def verify_file(path, schema):
    records = load_records(path)
    return verify_records(records, schema)


def load_schema(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Offline verifier for SZL Governed Inference Receipts.")
    parser.add_argument("receipts", nargs="+", help="receipt JSON / NDJSON file(s)")
    parser.add_argument("--schema", default=DEFAULT_SCHEMA,
                        help="path to governed-receipt.schema.json")
    args = parser.parse_args(argv)

    schema = load_schema(args.schema)
    all_ok = True
    for path in args.receipts:
        print("=== %s ===" % path)
        try:
            file_ok, lines = verify_file(path, schema)
        except Exception as exc:  # noqa: BLE001
            print("  FAIL could not process file: %s" % exc)
            all_ok = False
            continue
        for line in lines:
            print("  " + line)
        print("  RESULT: %s" % ("PASS" if file_ok else "FAIL"))
        all_ok = all_ok and file_ok

    print()
    print("OVERALL: %s" % ("PASS" if all_ok else "FAIL"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
