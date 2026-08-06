"""decision_engine.py -- DeviceWiki-Underwriter runtime decision engine.

PUBLIC-SAFE MODULE: this file ships inside the HF Space together with the
compiled artifact verified_rules.json. It contains NO knowledge extraction,
NO rule compilation, NO verification logic -- those live in the private core.
It only evaluates an already-verified rule artifact against one session.

Semantics (fixed, mirrors the private Prolog reference model):
  1. missing required slot -> refer(insufficient_information)  [never guess]
  2. any hard exclusion    -> ineligible(all firing reasons)
  3. any referral          -> refer(all firing reasons)
  4. eligibility passes    -> eligible(tier, endorsements)
  5. eligibility fails     -> ineligible(diagnosed failure reasons)
  6. otherwise             -> refer(uncovered_case)  [proven unreachable at
                              compile time; kept as a runtime guarantee]

Every verdict carries the assertion ids behind each fired rule, plus the
sha256 of the rule artifact, so the UI can render a full provenance trace
and the audit log is self-describing.

ASCII only.
"""

import hashlib
import json
import os
import time

ENGINE_VERSION = "0.1.0-stage1"

SEV_RANK = {"none": 0, "cosmetic": 1, "moderate": 2, "severe": 3}


def load_rules(path):
    with open(path, "r", encoding="ascii") as f:
        raw = f.read()
    rules = json.loads(raw)
    rules["_sha256"] = hashlib.sha256(raw.encode("ascii")).hexdigest()
    return rules


class DecisionEngine:
    def __init__(self, rules, audit_path=None):
        self.rules = rules
        self.audit_path = audit_path

    # ---------------- session accessors ----------------

    @staticmethod
    def _declared(session, key):
        return session.get("declared", {}).get(key)

    @staticmethod
    def _damage_list(session):
        return session.get("damage", [])

    def _worst_confirmed(self, session, component, dtype=None):
        worst = 0
        for d in self._damage_list(session):
            if d.get("component") != component:
                continue
            if dtype is not None and d.get("type") != dtype:
                continue
            if d.get("status") != "confirmed":
                continue
            worst = max(worst, SEV_RANK.get(d.get("severity"), 0))
        return worst

    def _in_catalog(self, session):
        model = self._declared(session, "model")
        return model in self.rules.get("catalog", {})

    # ---------------- condition evaluation ----------------

    def _cond(self, cond, session):
        kind = cond["kind"]
        if kind == "powers_on_is":
            return session.get("powers_on") is cond["value"]
        if kind == "challenge_is":
            return session.get("challenge_verified") is cond["value"]
        if kind == "fraud_band_in":
            return session.get("fraud_band") in cond["bands"]
        if kind == "stale_path":
            return bool(session.get("stale_path"))
        if kind == "not_in_catalog":
            return not self._in_catalog(session)
        if kind == "damage_type_present":
            return any(d.get("type") == cond["type"]
                       for d in self._damage_list(session))
        if kind == "damage_at_least":
            need = SEV_RANK[cond["min_severity"]]
            for d in self._damage_list(session):
                if d.get("component") != cond["component"]:
                    continue
                if d.get("type") != cond["type"]:
                    continue
                if d.get("status") != cond.get("status", "confirmed"):
                    continue
                if SEV_RANK.get(d.get("severity"), 0) >= need:
                    return True
            return False
        if kind == "suspected_at_least":
            need = SEV_RANK[cond["min_severity"]]
            return any(d.get("status") == "suspected"
                       and SEV_RANK.get(d.get("severity"), 0) >= need
                       for d in self._damage_list(session))
        if kind == "declaration_conflict":
            if self._declared(session, cond["declared_key"]) != cond["declared_value"]:
                return False
            return self._cond(dict(cond["damage"], kind="damage_at_least"), session)
        if kind == "over_age_for_tier":
            tier = self._declared(session, "requested_tier")
            age = self._declared(session, "purchase_months_ago")
            limits = self.rules["max_enrol_age_months"]
            if tier not in limits or not isinstance(age, (int, float)):
                return False
            return age > limits[tier]
        raise ValueError("unknown condition kind: %s" % kind)

    # ---------------- rule families ----------------

    def _missing_slots(self, session):
        missing = []
        for slot in self.rules["required_slots"]:
            if self._declared(session, slot) is None:
                missing.append(slot)
        return missing

    def _fired(self, family, session):
        out = []
        for rule in self.rules[family]:
            if self._cond(rule["condition"], session):
                out.append(rule)
        return out

    def _endorsements(self, session, tier):
        seen, out = set(), []
        for rule in self.rules["endorsements"]:
            if tier in rule.get("excluded_on_tiers", []):
                continue
            if rule["name"] in seen:
                continue
            if self._cond(rule["condition"], session):
                seen.add(rule["name"])
                out.append({"name": rule["name"], "rule_id": rule["id"],
                            "assertions": rule["assertions"]})
        return out

    def _screen_ok(self, session, tier):
        worst = self._worst_confirmed(session, "screen")
        ceiling = SEV_RANK[self.rules["tier_screen_ceiling"][tier]]
        if worst <= ceiling:
            return True
        # above ceiling: admissible only via a screen endorsement on this tier
        return any(e["name"] == "screen_exclusion"
                   for e in self._endorsements(session, tier))

    # ---------------- top-level decision ----------------

    def decide(self, session):
        verdict = self._decide_inner(session)
        verdict["engine_version"] = ENGINE_VERSION
        verdict["rules_sha256"] = self.rules.get("_sha256", "")
        verdict["session_id"] = session.get("session_id", "")
        self._audit(verdict)
        return verdict

    def _decide_inner(self, session):
        missing = self._missing_slots(session)
        if missing:
            return {"verdict": "refer",
                    "reasons": ["insufficient_information"],
                    "missing_slots": missing,
                    "assertions": list(self.rules["required_slots_assertions"]),
                    "trace": "required_slots"}

        excl = self._fired("hard_exclusions", session)
        if excl:
            return {"verdict": "ineligible",
                    "reasons": [r["reason"] for r in excl],
                    "assertions": sorted({a for r in excl for a in r["assertions"]}),
                    "fired_rules": [r["id"] for r in excl],
                    "trace": "hard_exclusions"}

        refs = self._fired("referrals", session)
        if refs:
            return {"verdict": "refer",
                    "reasons": [r["reason"] for r in refs],
                    "assertions": sorted({a for r in refs for a in r["assertions"]}),
                    "fired_rules": [r["id"] for r in refs],
                    "trace": "referrals"}

        tier = self._declared(session, "requested_tier")
        if tier not in self.rules["plan_tiers"]:
            fr = self.rules["eligibility_failure_reasons"]["invalid_tier_requested"]
            return {"verdict": "ineligible",
                    "reasons": ["invalid_tier_requested"],
                    "assertions": list(fr["assertions"]),
                    "trace": "eligibility_diagnostics"}

        # hard exclusions already handled catalog, power, age; remaining gate:
        if self._screen_ok(session, tier):
            ends = self._endorsements(session, tier)
            ids = (list(self.rules["catalog_assertions"])
                   + list(self.rules["max_enrol_age_assertions"])
                   + list(self.rules["tier_screen_ceiling_assertions"])
                   + [a for e in ends for a in e["assertions"]])
            return {"verdict": "eligible",
                    "tier": tier,
                    "endorsements": ends,
                    "reasons": [],
                    "assertions": sorted(set(ids)),
                    "trace": "eligibility"}

        fr = self.rules["eligibility_failure_reasons"][
            "screen_condition_exceeds_tier_ceiling"]
        return {"verdict": "ineligible",
                "reasons": ["screen_condition_exceeds_tier_ceiling"],
                "assertions": list(fr["assertions"]),
                "trace": "eligibility_diagnostics"}

    # ---------------- audit log ----------------

    def _audit(self, verdict):
        if not self.audit_path:
            return
        rec = dict(verdict)
        rec["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        os.makedirs(os.path.dirname(self.audit_path), exist_ok=True)
        with open(self.audit_path, "a", encoding="ascii") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
