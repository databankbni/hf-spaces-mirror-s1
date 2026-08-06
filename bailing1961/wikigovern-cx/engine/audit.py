# audit.py - decision audit log (PUBLIC runtime). ASCII only. Stdlib only.
# Every gate decision is appended as one JSON line. No record contents
# and no PII are ever written - only the query shape, verdict, rule ids
# and counts, stamped with the KB hash.

import datetime
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "..", "audit", "decisions.jsonl")


def log_decision(query, decision):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    entry = {"ts": datetime.datetime.utcnow().isoformat() + "Z",
             "query": query,
             "verdict": decision.get("verdict"),
             "n_selected": decision.get("n_selected",
                                        decision.get("group_size")),
             "n_allowed": decision.get("n_allowed"),
             "blocked_by": decision.get("blocked_by"),
             "unknown_slots": decision.get("unknown_slots"),
             "kb_hash": decision.get("kb_hash", "")[:16],
             "release": decision.get("release")}
    with open(LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


def recent(n=10):
    if not os.path.isfile(LOG):
        return []
    with open(LOG) as f:
        lines = f.readlines()
    return [json.loads(x) for x in lines[-n:]][::-1]
