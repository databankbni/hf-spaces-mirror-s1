from datetime import datetime, timezone
from html import escape

from public_demo.sample_data import COURSES, SOURCES


def _audit_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"


def _report(context="PASS", evidence="PASS", constraint="PASS", control="PASS"):
    return (
        "\n\n#### 4C verification summary\n"
        f"| Check | Status |\n|---|---|\n| Context | **{context}** |\n"
        f"| Citation | **{evidence}** |\n| Constraint | **{constraint}** |\n| Control | **{control}** |"
    )


def answer_question(question):
    q = (question or "").lower().strip()
    audit = _audit_id("QA")
    if not q:
        return "Please enter a course question."
    if "part-time" in q or "part time" in q:
        body = "**Verified answer:** Yes. The demonstration record states that the Bachelor of Applied Computing is available full-time or part-time. Delivery availability can depend on intake."
        source = SOURCES["course_bac"]
    elif "english" in q or "ielts" in q:
        body = "**Verified answer:** International applicants must provide evidence satisfying the published English-language requirement. This demo does not infer equivalence for unlisted tests or prior study. Those cases require human assessment."
        source = SOURCES["admission"]
    elif "diploma" in q and ("long" in q or "duration" in q):
        body = "**Verified answer:** The Diploma of Information Technology has a published full-time duration of one year in the demonstration catalogue."
        source = SOURCES["course_dit"]
    elif "fee" in q or "cost" in q:
        body = "**Verified answer:** The demonstration annual indicative fee for the Bachelor of Applied Computing is AUD 24,000 for 2026. Fees are time-sensitive and must be rechecked for the intended intake."
        source = SOURCES["fees"]
    elif "visa" in q:
        return ("**Human review required.** This agent does not provide visa or immigration advice. Please consult the relevant government authority or an authorised adviser."
                + _report(context="LIMITED", evidence="N/A", constraint="N/A", control="ESCALATE") + f"\n\n`Audit reference: {audit}`")
    else:
        return ("**Not verified from the current demonstration knowledge set.** Try asking about course duration, study mode, English evidence or published fees."
                + _report(context="UNRESOLVED", evidence="INSUFFICIENT", constraint="NOT RUN", control="ABSTAIN") + f"\n\n`Audit reference: {audit}`")
    citation = f"\n\n**Source:** [{source['title']}]({source['url']}) · Version {source['version']} · Effective {source['effective']}"
    return body + citation + _report() + f"\n\n`Audit reference: {audit}`"


def check_eligibility(target, applicant, qualification, relevant, experience, english):
    audit = _audit_id("ELIG")
    met, missing, review = [], [], []
    academic_ok = qualification in {"Diploma", "Bachelor degree"} and relevant
    alternative = qualification == "Certificate IV" and experience >= 2
    if target == "Diploma of Information Technology":
        academic_ok = qualification in {"Year 12", "Certificate IV", "Diploma", "Bachelor degree"}
        alternative = False
    if academic_ok:
        met.append("Published academic entry condition")
    elif alternative:
        met.append("Published alternative: relevant Certificate IV plus at least two years of relevant experience")
    elif qualification == "Other / overseas qualification":
        review.append("Qualification equivalence requires individual assessment")
    else:
        missing.append("A recognised academic qualification or an applicable alternative pathway")
    if applicant == "International":
        if english == "Published requirement met":
            met.append("Published English-language condition")
        elif english == "Needs individual assessment":
            review.append("English evidence equivalence")
        else:
            missing.append("Published English-language evidence")
    status = "LIKELY MEETS PUBLISHED CONDITIONS" if not missing and not review else ("HUMAN ASSESSMENT REQUIRED" if review else "ADDITIONAL EVIDENCE OR PATHWAY REQUIRED")
    lines = [f"## {escape(status)}", f"**Target:** {escape(target)}", ""]
    if met: lines += ["**Conditions supported**", *[f"- {escape(x)}" for x in met], ""]
    if missing: lines += ["**Missing or unmet**", *[f"- {escape(x)}" for x in missing], ""]
    if review: lines += ["**Needs human review**", *[f"- {escape(x)}" for x in review], ""]
    lines += ["**Next step:** " + ("Confirm documents with admissions before applying." if status.startswith("LIKELY") else "Contact admissions with the listed evidence or ask about the available pathway."),
              "", f"**Rules used:** `ENTRY-{target[:3].upper()}-2026` · [Published entry conditions]({SOURCES['admission']['url']})"]
    c = "PASS" if not missing and not review else ("REVIEW" if review else "CONDITIONAL")
    control = "HUMAN REVIEW" if review else "PASS"
    return "\n".join(lines) + _report(constraint=c, control=control) + f"\n\n`Audit reference: {audit}`"


def build_pathway(current, goal):
    audit = _audit_id("PATH")
    if current == "Diploma of Information Technology":
        text = "### Candidate pathway\n**Diploma of Information Technology** → credit assessment → **Bachelor of Applied Computing**\n\nCredit is not guaranteed; the amount requires human assessment."
        constraint, control = "PASS", "HUMAN CHECKPOINT"
    elif current == "Certificate IV":
        text = "### Candidate pathway\n**Certificate IV** → **Diploma of Information Technology** → credit assessment → **Bachelor of Applied Computing**\n\nA direct-entry alternative may exist where the published work-experience condition is also met."
        constraint, control = "PASS", "HUMAN CHECKPOINT"
    elif current == "Year 12":
        text = "### Candidate pathway\n**Year 12** → **Diploma of Information Technology** → credit assessment → **Bachelor of Applied Computing**"
        constraint, control = "PASS", "HUMAN CHECKPOINT"
    else:
        text = "### Human assessment required\nThe current qualification cannot be mapped safely to a published pathway. Admissions should first assess its level and relevance."
        constraint, control = "UNRESOLVED", "ESCALATE"
    return (text + f"\n\n**Pathway evidence:** [Articulation and credit policy]({SOURCES['pathway']['url']})"
            + _report(constraint=constraint, control=control) + f"\n\n`Audit reference: {audit}`")
