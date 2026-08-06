# CRIA — Usability Test Facilitator Script

**Tool:** CRIA — Colorado River Integrated Assessment
**Purpose:** Measure how easily a target user (water manager, researcher, student) can complete real tasks, and capture a System Usability Scale (SUS) score for the manuscript.
**Participants:** 5–8 is enough (Nielsen: ~5 users surface ~80% of usability issues). Aim for a mix — e.g. a CAP/Reclamation/ADWR analyst, an ASU researcher, a graduate student, and (if possible) a Tribal water manager.
**Time:** ~20–25 minutes per participant.
**Setup:** Live tool at https://praddyk-cria-dst.hf.space · a screen to share · SUS form (CRIA_Usability_SUS_Form.html) open in another tab.

---

## Before you start (facilitator says)
> "Thanks for helping. We're testing the tool, not you — nothing you do is wrong, and it's most useful to us when you get stuck. Please **think aloud**: say what you're looking at, what you expect, and what's confusing. I can't help during a task, but I'll answer everything afterward."

Ask permission to take notes / record. Note their role.

## Warm-up (1 min)
> "Open the tool. Without clicking yet — what do you think this is, and where would you start? Take the guided **'Take a tour'** if you like."

Note their first impression and whether the role-based entry / tour helps.

---

## Tasks (think-aloud; note time, success, and any struggle points)

**Task 1 — Where is the water going?**
> "Find out whether the basin's water loss is coming mostly from the surface or from underground, and roughly how confident the tool is about it."
*(Looks for: Subsurface Storage / GRACE, the 96% figure, the p-value / validation.)*

**Task 2 — Shortage tier (manager task).**
> "You need to brief your team. Find the current Lake Mead shortage tier and the delivery cut it triggers for Arizona / CAP."
*(Looks for: Reservoirs & Shortage Tiers, the tier ladder, live level link.)*

**Task 3 — A what-if.**
> "Estimate how the basin's streamflow would change under about +2 °C warming and 10% less precipitation."
*(Looks for: Scenario Explorer, the ΔT/ΔP dials, the projected % with confidence band.)*

**Task 4 — The early signal.**
> "Find the 'October Signal' and tell me in one sentence what it means for a manager."
*(Looks for: October Signal tab; can they read the dry-vs-wet outlook and the skill caveat?)*

**Task 5 — Ask the assistant.**
> "Use the built-in assistant (RIA) to ask a question about drought, then open the analysis it points you to."
*(Looks for: RIA usage, and whether the suggested tab is relevant.)*

For each task note: ✅ completed unaided / 🟡 completed with hesitation / ❌ needed help — and *where* they hesitated.

---

## After the tasks
1. Ask the participant to fill the **SUS form** (10 statements) → record the score.
2. Three open questions:
   - "What was the single most useful thing?"
   - "What was the most confusing or frustrating?"
   - "Would you trust these numbers in a real decision — why / why not?"

## Afterwards (analysis)
- Average the SUS scores → report as **"SUS = X (n = N)"** in the paper.
- List the top recurring struggle points (usually 2–4) → prioritise fixes.
- One iteration on those fixes, then (optionally) a quick re-test.

> Reporting line for the manuscript: *"The tool was usability-tested with N target users using task-based think-aloud protocol and the System Usability Scale; mean SUS = X."*
