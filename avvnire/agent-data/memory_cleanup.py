#!/usr/bin/env python3
import os, json, ssl, time, threading, urllib.request

HINDSIGHT_BASE = "https://api.hindsight.vectorize.io"
BANK_ID = "hermes"
MAX_NODES_THRESHOLD = 2000
TARGET_NODES = 1500
CHECK_INTERVAL = 6 * 3600

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

def _headers():
    return {"Authorization": "Bearer " + os.environ.get("HINDSIGHT_API_KEY",""), "Content-Type": "application/json"}

def _get_stats():
    req = urllib.request.Request(HINDSIGHT_BASE + "/v1/default/banks/" + BANK_ID + "/stats", headers=_headers())
    with urllib.request.urlopen(req, context=_ssl_ctx, timeout=15) as resp:
        return json.loads(resp.read().decode())

def _list_memories(limit=200, offset=0):
    req = urllib.request.Request(HINDSIGHT_BASE + "/v1/default/banks/" + BANK_ID + "/memories/list?limit=" + str(limit) + "&offset=" + str(offset), headers=_headers())
    with urllib.request.urlopen(req, context=_ssl_ctx, timeout=15) as resp:
        return json.loads(resp.read().decode())

def _invalidate_memory(mid, reason="LFU eviction"):
    payload = json.dumps({"state": "invalidated", "reason": reason}).encode()
    req = urllib.request.Request(HINDSIGHT_BASE + "/v1/default/banks/" + BANK_ID + "/memories/" + mid, data=payload, method="PATCH", headers=_headers())
    with urllib.request.urlopen(req, context=_ssl_ctx, timeout=15) as resp:
        return json.loads(resp.read().decode())

def _clear_observations(mid):
    req = urllib.request.Request(HINDSIGHT_BASE + "/v1/default/banks/" + BANK_ID + "/memories/" + mid + "/observations", method="DELETE", headers=_headers())
    try:
        with urllib.request.urlopen(req, context=_ssl_ctx, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except:
        return None

def _trigger_consolidation():
    req = urllib.request.Request(HINDSIGHT_BASE + "/v1/default/banks/" + BANK_ID + "/consolidate", method="POST", headers=_headers())
    try:
        with urllib.request.urlopen(req, context=_ssl_ctx, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except:
        return None

def run_cleanup():
    try:
        stats = _get_stats()
        total = stats.get("total_nodes", 0)
        if total <= MAX_NODES_THRESHOLD:
            return "OK: " + str(total) + " nodes (under " + str(MAX_NODES_THRESHOLD) + ")"
        to_evict = total - TARGET_NODES
        evicted = 0
        candidates = []
        offset = 0
        while len(candidates) < to_evict + 100 and offset < total:
            data = _list_memories(limit=200, offset=offset)
            items = data.get("items", [])
            if not items:
                break
            for item in items:
                if item.get("state") == "valid" and item.get("fact_type") in ("experience", "world"):
                    candidates.append({"id": item["id"], "proof_count": item.get("proof_count", 0), "date": item.get("date", "")})
            offset += 200
        candidates.sort(key=lambda x: (x["proof_count"], x["date"]))
        for c in candidates[:to_evict]:
            _invalidate_memory(c["id"])
            _clear_observations(c["id"])
            evicted += 1
        if evicted > 0:
            _trigger_consolidation()
        return "Evicted " + str(evicted) + " LFU memories. " + str(total) + " -> " + str(total - evicted) + " nodes."
    except Exception as e:
        return "Error: " + str(e)

def _cleanup_loop():
    while True:
        time.sleep(CHECK_INTERVAL)
        try:
            print("[CLEANUP] " + run_cleanup(), flush=True)
        except Exception as e:
            print("[CLEANUP] Error: " + str(e), flush=True)

def start_cleanup():
    try:
        result = run_cleanup()
        print("[CLEANUP] Initial: " + result, flush=True)
    except Exception as e:
        print("[CLEANUP] Initial error: " + str(e), flush=True)
    t = threading.Thread(target=_cleanup_loop, daemon=True, name="memory_cleanup")
    t.start()
    print("[CLEANUP] LFU eviction thread started (6h interval)", flush=True)
