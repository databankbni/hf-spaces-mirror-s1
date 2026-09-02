"""Pure curation-mode logic: the PR protocol, review tallying, and the merge
decision for the MecCog final-set dataset. No I/O — every function here is
deterministic and unit-tested, so the merge-bot's correctness lives in tests,
not in a live Hub round trip.

PR protocol (see the dataset's CONTRIBUTING.md):
  - the PR description carries a header line `agent: <id>`;
  - a paper is proposed by ADDING one entry file (include) or removed by
    DELETING it (exclude). Where it lands depends on its `tag`:
      - tag "primary" | "secondary"  -> data/{HYP}/{doi-slug}.json (the final set)
      - tag "unrelated"              -> rejected/{HYP}/{doi-slug}.json
    `tag` is the whole relevance call — there is no separate ranking pass.
  - a review is a comment whose FIRST line is `/approve`, `/request-changes`,
    or `/comment`, followed by rationale;
  - a PR merges when it has >= min_approvals approvals from reviewers whose HF
    account differs from the author's (when distinct), and no open
    /request-changes (the veto).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.hub import PRComment


HYPOTHESES = ("M1H1", "M1H2", "M3H1", "M3H2", "M3H3")

# Where an entry lives, keyed by its `tag`. "primary"/"secondary" are both
# read from data/ — the final set does not otherwise distinguish them, a
# client reads the `tag` field to tell strong evidence from adequate evidence.
TAGS = ("primary", "secondary", "unrelated")
_LOCATION_BY_TAG = {"primary": "data", "secondary": "data", "unrelated": "rejected"}

# Posted by the merge-bot when it closes a PR for an unresolved veto. Shared
# between merge_bot.py (writes it) and routes/prs.py (reads it back off the
# thread to tell a veto-close apart from any other closed status).
VETO_MARKER = "<!-- merge-bot:vetoed -->"

_AGENT_HEADER_RE = re.compile(
    r"^\s*agent\s*:\s*([a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?)\s*$", re.M
)

# `session: <id>` in the PR description — the shared trace the merge gate checks.
_SESSION_HEADER_RE = re.compile(r"^\s*session\s*:\s*([A-Za-z0-9][A-Za-z0-9._-]{0,127})\s*$", re.M)

# An entry-file path: {data|rejected}/{HYP}/{doi-slug}.json.
_ENTRY_PATH_RE = re.compile(r"^(?P<loc>data|rejected)/(?P<hyp>[A-Za-z0-9]+)/(?P<slug>[^/]+)\.json$")

# verdict keyword -> canonical verdict
_VERDICTS = {
    "/approve": "approve",
    "/request-changes": "request-changes",
    "/request_changes": "request-changes",
    "/comment": "comment",
}


def sanitize_doi_slug(doi: str) -> str:
    """DOI -> filesystem-safe stem (must match the seed + open_pr client).
    `10.1038/s41586-025-09486-x` -> `10.1038-s41586-025-09486-x`."""
    return re.sub(r"[^a-zA-Z0-9._-]", "-", (doi or "").replace(":", "-").replace("/", "-")).strip("-")


def parse_agent_header(description: str) -> str | None:
    """Extract the `agent: <id>` declared in a PR description, or None."""
    if not description:
        return None
    m = _AGENT_HEADER_RE.search(description)
    return m.group(1) if m else None


def parse_session_header(description: str) -> str | None:
    """Extract the `session: <id>` declared in a PR description, or None. The
    session whose shared trace the merge-bot requires before merging."""
    if not description:
        return None
    m = _SESSION_HEADER_RE.search(description)
    return m.group(1) if m else None


def parse_review_verdict(comment_text: str) -> str | None:
    """Map a review comment to a verdict from its first non-empty line.
    Returns 'approve' | 'request-changes' | 'comment' | None."""
    for line in (comment_text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        token = line.split()[0].lower()
        return _VERDICTS.get(token)
    return None


def parse_entry_path(path: str) -> tuple[str, str, str] | None:
    """`{data|rejected}/{HYP}/{slug}.json` -> (location, HYP, slug); None for
    anything else. Only a recognised hypothesis id counts, so a stray file
    can't masquerade as an entry."""
    m = _ENTRY_PATH_RE.match(path or "")
    if not m:
        return None
    hyp = m.group("hyp")
    if hyp not in HYPOTHESES:
        return None
    return m.group("loc"), hyp, m.group("slug")


def entry_path(tag: str, hyp: str, slug: str) -> str:
    """Where an entry with this `tag` belongs."""
    return f"{_LOCATION_BY_TAG[tag]}/{hyp}/{slug}.json"


@dataclass
class ReviewTally:
    approvals: int = 0
    approvers: list[str] = field(default_factory=list)          # HF usernames or agents
    request_changes_by: list[str] = field(default_factory=list)
    ignored_self: int = 0    # approvals dropped because reviewer == author


def _is_self_approval(
    level: str, reviewer_user: str, reviewer_agent: str | None,
    author_user: str, author_agent: str | None,
) -> bool:
    """Whether an approval should be dropped as self-approval, given the level:
      - none:    never;
      - account: same HF account as the author (the secure default);
      - agent:   same account counts as self UNLESS a *different* agent: is
                 declared on the review (so different agents on one account can
                 review each other — weaker, the agent line is self-asserted)."""
    if level == "none":
        return False
    if not author_user or reviewer_user != author_user:
        return False  # a different HF account is never self-approval
    if level == "account":
        return True
    return (not reviewer_agent) or (reviewer_agent == author_agent)


def tally_reviews(
    comments: list[PRComment],
    *,
    author_hf_user: str,
    author_agent: str | None = None,
    distinct_level: str = "account",
) -> ReviewTally:
    """Tally verdicts. The LATEST verdict per reviewer wins (comments are in
    chronological order). ``distinct_level`` ('account' | 'agent' | 'none')
    controls anti-self-approval. `/comment` after a verdict withdraws it."""
    level = distinct_level or "account"
    # reviewer identity -> (verdict, hf_user, agent). Key by agent in 'agent'
    # mode so distinct agents on one account don't collapse onto each other.
    latest: dict[object, tuple[str, str, str | None]] = {}
    for c in comments:
        v = parse_review_verdict(c.text)
        agent = parse_agent_header(c.text)
        key = (c.author, agent) if level == "agent" else c.author
        if v in ("approve", "request-changes"):
            latest[key] = (v, c.author, agent)   # later comment overrides earlier
        elif v == "comment" and key in latest:
            del latest[key]   # an explicit /comment withdraws a prior verdict
    tally = ReviewTally()
    for verdict, user, agent in latest.values():
        who = agent or user   # credit the declared agent when present
        if verdict == "approve":
            if _is_self_approval(level, user, agent, author_hf_user, author_agent):
                tally.ignored_self += 1
                continue
            tally.approvals += 1
            tally.approvers.append(who)
        elif verdict == "request-changes":
            tally.request_changes_by.append(who)
    return tally


@dataclass
class MergeDecision:
    mergeable: bool
    approvals: int
    reason: str
    approvers: list[str] = field(default_factory=list)
    request_changes_by: list[str] = field(default_factory=list)


def decide_merge(
    tally: ReviewTally,
    *,
    min_approvals: int,
    block_on_request_changes: bool,
) -> MergeDecision:
    if block_on_request_changes and tally.request_changes_by:
        return MergeDecision(
            False, tally.approvals,
            f"blocked: open /request-changes from {', '.join(tally.request_changes_by)}",
            tally.approvers, tally.request_changes_by,
        )
    if tally.approvals < min_approvals:
        return MergeDecision(
            False, tally.approvals,
            f"needs {min_approvals} approval(s), has {tally.approvals}",
            tally.approvers, tally.request_changes_by,
        )
    return MergeDecision(
        True, tally.approvals,
        f"approved by {', '.join(tally.approvers)}",
        tally.approvers, tally.request_changes_by,
    )


_PAPER_TYPES = {
    "PubMed published", "PubMed preprint", "Web article", "Database", "Other",
}


def validate_paper_entry(entry: object, *, hyp: str, slug: str, location: str) -> list[str]:
    """Format-check one entry file. Returns a list of error strings (empty ==
    valid). Format only — not truth; the quotes' faithfulness is what
    human/peer review is for. Mirrors the spreadsheet column rules.

    ``location`` is the folder the file was added to ('data' or 'rejected'),
    checked against the entry's own `tag` so an agent can't write "primary" in
    the body while filing it as rejected (or vice versa)."""
    errs: list[str] = []
    if not isinstance(entry, dict):
        return ["entry is not a JSON object"]
    doi = entry.get("doi")
    if not isinstance(doi, str) or not doi.strip():
        errs.append("missing `doi`")
    elif sanitize_doi_slug(doi) != slug:
        errs.append(f"filename slug {slug!r} does not match doi {doi!r} "
                    f"(expected {sanitize_doi_slug(doi)!r})")
    if entry.get("hypothesis") != hyp:
        errs.append(f"`hypothesis` must be {hyp!r} to match its folder")
    ptype = entry.get("paper_type")
    if ptype not in _PAPER_TYPES:
        errs.append(f"`paper_type` must be one of {sorted(_PAPER_TYPES)}")

    tag = entry.get("tag")
    if tag not in TAGS:
        errs.append(f"`tag` must be one of {TAGS}")
    elif _LOCATION_BY_TAG[tag] != location:
        errs.append(
            f"tag {tag!r} belongs under `{_LOCATION_BY_TAG[tag]}/`, not `{location}/` "
            f"— the PR must add the file at the path matching its tag"
        )

    quotes = entry.get("quotes") or []
    if tag == "unrelated":
        # The whole point of "unrelated" is that there is no experiment
        # directly bearing on the hypothesis — requiring one would ask an
        # agent to manufacture relevance it just argued the paper doesn't have.
        if not isinstance(quotes, list):
            errs.append("`quotes` must be a list (may be empty for `unrelated`)")
    elif not isinstance(quotes, list) or not quotes:
        errs.append("`quotes` must be a non-empty list for `primary`/`secondary`")
    for i, q in enumerate(quotes, 1):
        if not isinstance(q, dict):
            errs.append(f"quote {i} is not an object")
            continue
        if not str(q.get("quote") or "").strip():
            errs.append(f"quote {i} missing `quote` text")
        if not str(q.get("finding") or "").strip():
            errs.append(f"quote {i} missing `finding`")
        if not str(q.get("data_location") or "").strip():
            errs.append(f"quote {i} missing `data_location`")

    if not str(entry.get("justification") or "").strip():
        errs.append("missing `justification`")
    if not str(entry.get("proposed_by") or "").strip():
        errs.append("missing `proposed_by`")
    return errs


def detect_direction(added: list[str], removed: list[str]) -> str:
    """Classify a curation PR by which entry files it touches:
      - 'include' — adds one or more entry files (data/ or rejected/);
      - 'exclude' — only deletes entry files;
      - 'mixed'   — both (unusual; still processed, direction reported as mixed);
      - 'none'    — touches nothing the bot recognises (ignored)."""
    adds = [p for p in added if parse_entry_path(p)]
    dels = [p for p in removed if parse_entry_path(p)]
    if adds and dels:
        return "mixed"
    if adds:
        return "include"
    if dels:
        return "exclude"
    return "none"
