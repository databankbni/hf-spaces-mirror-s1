# gate.py - WikiGovern-CX deterministic governance gate (PUBLIC runtime).
# ASCII only. Stdlib only. No LLM anywhere in a verdict path.
#
# v2 (P5): optional LINKS MODE. Construct Gate(art, data) for the P3
# behaviour (no identity links), or Gate(art, data, links_path=...) to
# load resolved identity links, which:
#   - turns RET-003 (partner_linked retention max) from declared-
#     unenforced into ENFORCED: transactions of partner-linked customers
#     older than the limit are use-blocked;
#   - extends A<->B joins with ER-discovered pairs, which are then gated:
#     quarantined components (deletion requests, RET-010) are blocked,
#     non-subscriber pairs are blocked by SHR-001;
#   - link knowledge is only ever used restrictively: links may block
#     more, never allow more.
# When RET-003 blocks a record that RET-001 simultaneously requires to be
# kept, the decision carries a conflict note: use blocked, record
# retained, destruction escalated to humans (the Z3-detected conflict).
#
# Query dict: see decide().

import csv
import datetime
import hashlib
import json
import os

PURPOSES = ("service_delivery", "marketing", "analytics_internal")
REF_DATE = datetime.date(2026, 7, 3)


class GateError(Exception):
    pass


def _load_json(path):
    with open(path) as f:
        return json.load(f)


class _UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


class Gate:
    def __init__(self, artifacts_dir, data_dir, links_path=None):
        self.rules = _load_json(os.path.join(artifacts_dir,
                                             "rules.compiled.json"))
        self.prov = _load_json(os.path.join(artifacts_dir,
                                            "provenance.json"))
        self.catalog = {d["dataset"]: d for d in
                        _load_json(os.path.join(
                            artifacts_dir,
                            "catalog.compiled.json"))["datasets"]}
        wl_path = os.path.join(artifacts_dir, "whitelist.json")
        self.whitelist = set(_load_json(wl_path)["approved_use_cases"]) \
            if os.path.isfile(wl_path) else set()
        self.data_dir = data_dir
        self._cache = {}
        self.k = next(r["k"] for r in
                      self.rules["rules"]["aggregation"]
                      if r["kind"] == "aggregation_k")
        self._deletions = None
        self._roster = None
        # ---- retention max map: (record_class, scope) -> years ------
        self.ret_max = {}
        for r in self.rules["rules"]["retention"]:
            if r["kind"] == "retention_max":
                self.ret_max[(r["record_class"], r["scope"])] = \
                    (int(r["years"]), r["id"])
        # ---- links mode ---------------------------------------------
        self.links = None
        self.partner_linked_a = set()
        self._ab_link_pairs = None
        if links_path and os.path.isfile(links_path):
            with open(links_path) as f:
                self.links = [json.loads(line) for line in f]
            uf = _UnionFind()
            for l in self.links:
                uf.union(l["left"], l["right"])
            comp = {}
            for l in self.links:
                for node in (l["left"], l["right"]):
                    comp.setdefault(uf.find(node), set()).add(node)
            for members in comp.values():
                has_partner = any(m.startswith("partner:")
                                  for m in members)
                if has_partner:
                    for m in members:
                        if m.startswith("brand_a:"):
                            self.partner_linked_a.add(m.split(":", 1)[1])
        # ---- capability notes ----------------------------------------
        self.capability_notes = []
        for r in self.rules["rules"]["retention"]:
            if r["kind"] == "retention_max" and \
                    r.get("scope") == "partner_linked":
                if self.links is not None:
                    self.capability_notes.append(
                        {"rule_id": r["id"], "enforced": True,
                         "reason": "identity links loaded; partner-"
                                   "linked customers resolved from link "
                                   "components (%d customers)"
                                   % len(self.partner_linked_a)})
                else:
                    self.capability_notes.append(
                        {"rule_id": r["id"], "enforced": False,
                         "reason": "requires resolved identity links "
                                   "(entity resolution phase)"})

    # ------------------------------------------------------------ data
    def _rows(self, dataset):
        if dataset in self._cache:
            return self._cache[dataset]
        if dataset not in self.catalog:
            raise GateError("unknown dataset: %s" % dataset)
        src = self.catalog[dataset]["source_file"]
        path = os.path.join(self.data_dir, src)
        rows = []
        if src.endswith(".csv"):
            with open(path, newline="") as f:
                rows = list(csv.DictReader(f))
        elif src.endswith(".jsonl"):
            with open(path) as f:
                rows = [json.loads(line) for line in f]
        elif src.endswith(".json"):
            rows = _load_json(path)["members"]
        self._cache[dataset] = rows
        return rows

    def _pk(self, dataset):
        return self.catalog[dataset]["primary_key"]

    def deletions(self):
        if self._deletions is None:
            self._deletions = set()
            path = os.path.join(self.data_dir, "deletion_requests.csv")
            if os.path.isfile(path):
                with open(path, newline="") as f:
                    for r in csv.DictReader(f):
                        self._deletions.add((r["source"], r["local_id"]))
        return self._deletions

    def roster(self):
        if self._roster is None:
            emails, mobiles = set(), set()
            path = os.path.join(self.data_dir, "subscription_members.csv")
            if os.path.isfile(path):
                with open(path, newline="") as f:
                    for r in csv.DictReader(f):
                        emails.add(r["email"].strip().lower())
                        mobiles.add(r["mobile"].strip())
            self._roster = (emails, mobiles)
        return self._roster

    # ------------------------------------------------- per-record checks
    def _deletion_blocked(self, dataset, row):
        brand = self.catalog[dataset]["brand"]
        return (brand, row[self._pk(dataset)]) in self.deletions()

    def _retention_blocked(self, dataset, row):
        """Links-mode RET-003: partner-linked transactions past max."""
        if self.links is None:
            return None
        if dataset != "brand_a_transactions":
            return None
        if row.get("cust_id") not in self.partner_linked_a:
            return None
        lim = self.ret_max.get(("transaction_record", "partner_linked"))
        if not lim:
            return None
        years, rule_id = lim
        ts = datetime.date.fromisoformat(row["ts"])
        if (REF_DATE - ts).days > years * 365:
            return rule_id
        return None

    def _consent_state(self, dataset, row):
        """-> ('ok', None) | ('blocked', rule_id) | ('unknown', slot)"""
        if dataset == "brand_a_customers":
            if str(row.get("consent_marketing")).lower() == "true":
                if row.get("consent_date"):
                    return ("ok", None)
                return ("unknown", "consent_date")
            return ("blocked", "CON-001")
        if dataset == "brand_b_members":
            if row.get("marketing_pref") == "none":
                return ("blocked", "CON-001")
            return ("unknown", "consent_date")
        if dataset == "brand_c_customers":
            if str(row.get("newsletter")).lower() == "true":
                return ("blocked", "CON-002")
            return ("blocked", "CON-001")
        return ("blocked", "CON-001")

    def _purpose_state(self, dataset, row, purpose, use_case):
        if self._deletion_blocked(dataset, row):
            return ("blocked", "RET-010")
        ret = self._retention_blocked(dataset, row)
        if ret:
            return ("blocked", ret)
        if purpose == "service_delivery":
            return ("ok", "CON-003")
        if purpose == "marketing":
            return self._consent_state(dataset, row)
        if purpose == "analytics_internal":
            state, ref = self._consent_state(dataset, row)
            if state == "ok":
                return ("ok", "CON-004")
            if use_case and use_case in self.whitelist:
                return ("ok", "CON-004")
            if state == "unknown":
                return ("unknown", ref)
            return ("blocked", "CON-004")
        raise GateError("unknown purpose: %s" % purpose)

    # ------------------------------------------------------------ scopes
    def _select(self, dataset, filters):
        rows = self._rows(dataset)
        filters = filters or {}
        want_del = filters.pop("__deletion_requested", None)
        out = []
        for row in rows:
            if any(str(row.get(k)) != str(v) for k, v in filters.items()):
                continue
            if want_del is not None and \
                    self._deletion_blocked(dataset, row) != bool(want_del):
                continue
            out.append(row)
        return out

    def _finish(self, dataset, rows, purpose, use_case):
        blocked, unknown = {}, {}
        n_ok = 0
        for row in rows:
            state, ref = self._purpose_state(dataset, row, purpose,
                                             use_case)
            if state == "ok":
                n_ok += 1
            elif state == "blocked":
                blocked[ref] = blocked.get(ref, 0) + 1
            else:
                unknown[ref] = unknown.get(ref, 0) + 1
        return n_ok, blocked, unknown

    def _ab_pairs_links(self):
        """A<->B pairs from resolved links, with pre-block reasons."""
        if self._ab_link_pairs is not None:
            return self._ab_link_pairs
        a_by_id = {r["cust_id"]: r for r in
                   self._rows("brand_a_customers")}
        b_by_id = {r["member_no"]: r for r in
                   self._rows("brand_b_members")}
        out = []
        for l in self.links:
            if not (l["left"].startswith("brand_a:") and
                    l["right"].startswith("brand_b:")):
                continue
            a = a_by_id.get(l["left"].split(":", 1)[1])
            b = b_by_id.get(l["right"].split(":", 1)[1])
            if not (a and b):
                continue
            if l["status"] == "quarantined":
                out.append((a, b, "RET-010"))
            elif l["status"] == "member_level_blocked":
                out.append((a, b, "SHR-001"))
            else:
                out.append((a, b, None))
        self._ab_link_pairs = out
        return out

    def _join_pairs(self, left, right):
        """Returns (pairs, share_rule, note) with pairs of
        (lrow, rrow, pre_block_rule_or_None)."""
        pair = {left, right}
        if pair == {"brand_a_customers", "brand_b_members"}:
            if self.links is not None:
                return self._ab_pairs_links(), "SHR-001", None
            emails, mobiles = self.roster()
            a_rows = {r["email"].strip().lower(): r
                      for r in self._rows("brand_a_customers")
                      if r["email"].strip().lower() in emails}
            out = []
            with open(os.path.join(self.data_dir,
                                   "subscription_members.csv"),
                      newline="") as f:
                roster_rows = list(csv.DictReader(f))
            b_by_mobile = {r["mobile"]: r
                           for r in self._rows("brand_b_members")}
            for rr in roster_rows:
                a = a_rows.get(rr["email"].strip().lower())
                brow = b_by_mobile.get(rr["mobile"].strip())
                if a and brow:
                    out.append((a, brow, None))
            return out, "SHR-001", None
        if "partner_loyalty" in pair and "brand_b_members" in pair:
            hashes = {}
            for r in self._rows("brand_b_members"):
                h = hashlib.sha256(
                    r["mobile"].encode("ascii")).hexdigest()
                hashes[h] = r
            out = []
            for prow in self._rows("partner_loyalty"):
                brow = hashes.get(prow["mobile_hash"])
                if brow:
                    out.append((prow, brow, None))
            return out, "SHR-010", None
        if "partner_loyalty" in pair:
            return [], None, ("E-NO-JOIN-KEY",
                              "no deterministic identifier shared with "
                              "partner records for this pair before "
                              "entity resolution")
        return [], "SHR-020", None

    # ------------------------------------------------------------ decide
    def decide(self, query):
        try:
            return self._decide(query)
        except GateError as e:
            return {"verdict": "unknown", "error": str(e),
                    "kb_hash": self.rules["kb_hash"],
                    "release": self.rules["release"]}

    def _decide(self, query):
        purpose = query.get("purpose")
        if purpose not in PURPOSES:
            raise GateError("unknown purpose: %s" % purpose)
        scope = query.get("scope") or {}
        use_case = query.get("use_case")
        filters = dict(query.get("filters") or {})
        base = {"kb_hash": self.rules["kb_hash"],
                "release": self.rules["release"],
                "capability_notes": self.capability_notes,
                "purpose": purpose}

        if scope.get("type") == "single_source":
            rows = self._select(scope["dataset"], filters)
            n_ok, blocked, unknown = self._finish(scope["dataset"], rows,
                                                  purpose, use_case)
            out = base | self._verdict(len(rows), n_ok, blocked, unknown)
            self._add_conflict_note(out)
            return out

        if scope.get("type") == "aggregate":
            rows = self._select(scope["dataset"], filters)
            usable = [r for r in rows
                      if not self._deletion_blocked(scope["dataset"], r)]
            n_excluded = len(rows) - len(usable)
            reasons = ["AGG-001"]
            if scope["dataset"] == "partner_loyalty":
                reasons.append("AGG-002")
            if len(usable) >= self.k:
                v = {"verdict": "allow", "group_size": len(usable),
                     "k": self.k, "excluded_deletion_requests": n_excluded,
                     "reasons": self._cite(reasons)}
            else:
                v = {"verdict": "deny", "group_size": len(usable),
                     "k": self.k, "excluded_deletion_requests": n_excluded,
                     "reasons": self._cite(["AGG-001"]),
                     "blocked_by": {"AGG-001": 1}}
            return base | v

        if scope.get("type") == "join":
            left, right = scope["left"], scope["right"]
            for d in (left, right):
                if d not in self.catalog:
                    raise GateError("unknown dataset: %s" % d)
            pairs, share_rule, note = self._join_pairs(left, right)
            if note:
                return base | {"verdict": "unknown", "n_pairs": 0,
                               "note": {"code": note[0],
                                        "detail": note[1]}}
            if share_rule == "SHR-020":
                return base | {"verdict": "deny", "n_pairs": 0,
                               "blocked_by": {"SHR-020": 1},
                               "reasons": self._cite(["SHR-020"])}
            blocked, unknown = {}, {}
            n_ok = 0
            for lrow, rrow, pre_block in pairs:
                if pre_block:
                    blocked[pre_block] = blocked.get(pre_block, 0) + 1
                    continue
                states = [self._purpose_state(left, lrow, purpose,
                                              use_case),
                          self._purpose_state(right, rrow, purpose,
                                              use_case)]
                if share_rule == "SHR-010":
                    prow = lrow if left == "partner_loyalty" else rrow
                    if prow.get("share_scope") != "member_level":
                        states.append(("blocked", "SHR-010"))
                if any(s == "blocked" for s, _ in states):
                    ref = next(refx for s, refx in states
                               if s == "blocked")
                    blocked[ref] = blocked.get(ref, 0) + 1
                elif any(s == "unknown" for s, _ in states):
                    ref = next(refx for s, refx in states
                               if s == "unknown")
                    unknown[ref] = unknown.get(ref, 0) + 1
                else:
                    n_ok += 1
            out = self._verdict(len(pairs), n_ok, blocked, unknown)
            out["share_rule"] = share_rule
            out["n_pairs"] = len(pairs)
            out = base | out
            self._add_conflict_note(out)
            return out

        raise GateError("unknown scope type: %s" % scope.get("type"))

    # ---------------------------------------------------------- verdicts
    def _add_conflict_note(self, out):
        if "RET-003" in out.get("blocked_by", {}):
            out["conflict_notes"] = [{
                "rules": ["RET-001", "RET-003"],
                "posture": "use blocked under RET-003; records retained "
                           "under RET-001 (7-year minimum); destruction "
                           "requires human resolution of the detected "
                           "retention conflict"}]

    def _verdict(self, n_sel, n_ok, blocked, unknown):
        if n_sel == 0:
            verdict = "deny"
            reasons = [{"rule_id": "E-NO-RECORDS",
                        "statement": "no records match the selection",
                        "sources": []}]
        elif n_ok == n_sel:
            verdict = "allow"
            reasons = []
        elif n_ok > 0:
            verdict = "partial"
            reasons = self._cite(sorted(blocked) + sorted(unknown))
        else:
            verdict = "deny"
            reasons = self._cite(sorted(blocked) + sorted(unknown))
        return {"verdict": verdict, "n_selected": n_sel,
                "n_allowed": n_ok, "blocked_by": blocked,
                "unknown_slots": unknown, "reasons": reasons}

    def _cite(self, rule_ids):
        out = []
        for rid in rule_ids:
            if rid in self.prov:
                p = self.prov[rid]
                out.append({"rule_id": rid, "statement": p["statement"],
                            "sources": p["source_refs"]})
            else:
                out.append({"rule_id": rid, "statement": "", "sources": []})
        return out
