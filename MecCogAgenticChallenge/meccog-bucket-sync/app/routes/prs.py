"""Read API over the curation Pull Requests and the final-set dataset.

These endpoints are a thin, cached view of native Hub PRs (opened/merged on the
dataset itself, not through this Space) plus the merge records the merge-bot
writes to the central bucket. All are 404 when curation is disabled. Opening,
reviewing, and merging happen on the Hub directly — see the dataset's
CONTRIBUTING.md — so there are no write endpoints here.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query

from app.config import Settings
from app.curation import (
    decide_merge,
    detect_direction,
    parse_agent_header,
    parse_entry_path,
    tally_reviews,
    HYPOTHESES,
    VETO_MARKER,
)
from app.deps import get_hub, get_read_model, get_settings_dep
from app.errors import NotFound
from app.hub import HubClient, PullRequest
from app.models import (
    FinalSetEntry,
    FinalSetResponse,
    MergeInfo,
    MergeListing,
    PRInfo,
    PRListing,
    RejectedEntry,
    RejectedResponse,
)
from app.read_model import ReadModel


router = APIRouter()


def _require_curation(settings: Settings) -> None:
    if not settings.curation_enabled or not settings.curation_dataset:
        raise NotFound("curation is not enabled for this challenge")


def _dataset_url(settings: Settings) -> str:
    return f"https://huggingface.co/datasets/{settings.curation_dataset}"


def _agent_to_user(read_model: ReadModel) -> dict[str, str]:
    out: dict[str, str] = {}
    for r in read_model.records("agents"):
        if getattr(r, "parse_error", False):
            continue
        agent = r.filename.removesuffix(".md")
        user = str(r.frontmatter.get("hf_user") or "")
        if agent and user:
            out[agent] = user
    return out


def _as_agents(names: list[str], agent_to_user: dict[str, str]) -> list[str]:
    """HF usernames -> the agent ids they registered, where we know them.

    A reviewer only writes an `agent:` line when reviewing from an account that
    isn't its own, so most verdicts come back credited to a bare HF username.
    The board speaks in agent ids, so resolve them here — the same thing the
    merge records already do — and leave anything unrecognised as it came."""
    user_to_agent: dict[str, str] = {}
    for agent, user in agent_to_user.items():
        user_to_agent.setdefault(user, agent)
    return [user_to_agent.get(n, n) for n in names]


def _pr_info(
    settings: Settings, hub: HubClient, pr: PullRequest,
    agent_to_user: dict[str, str], main_tree: dict[str, str],
) -> PRInfo:
    thread = hub.get_pr_thread(settings.curation_dataset, pr.num)
    declared = parse_agent_header(thread.description)
    agent = declared if (declared and agent_to_user.get(declared) == pr.author) else None

    pr_tree = hub.list_dataset_tree(settings.curation_dataset, f"refs/pr/{pr.num}")
    added = [p for p in (set(pr_tree) - set(main_tree)) if parse_entry_path(p)]
    removed = [p for p in (set(main_tree) - set(pr_tree)) if parse_entry_path(p)]
    direction = detect_direction(added, removed)
    targets = sorted(
        f"{parse_entry_path(p)[1]}/{parse_entry_path(p)[2]}" for p in (*added, *removed)
    )

    # The tag(s) this PR proposes — read straight off the added files, so a
    # reviewer sees the classification without opening the diff.
    tags: list[str] = []
    for path in added:
        raw = hub.read_dataset_bytes(settings.curation_dataset, path, revision=f"refs/pr/{pr.num}")
        if raw:
            try:
                tag = json.loads(raw.decode("utf-8")).get("tag")
                if tag:
                    tags.append(str(tag))
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

    tally = tally_reviews(
        thread.comments, author_hf_user=pr.author, author_agent=declared,
        distinct_level=settings.distinct_level,
    )
    decision = decide_merge(
        tally, min_approvals=settings.merge_min_approvals,
        block_on_request_changes=settings.merge_block_on_request_changes,
    )
    conflicts = thread.conflicting_files if pr.status == "open" else []
    veto_closed = pr.status == "closed" and any(VETO_MARKER in c.text for c in thread.comments)
    if veto_closed:
        vetoers = ", ".join(_as_agents(tally.request_changes_by, agent_to_user)) or "a reviewer"
        reason = f"vetoed: closed by the merge-bot — unresolved /request-changes from {vetoers}"
    elif not agent:
        reason = "ignored: no valid `agent:` header matching the PR author"
    elif direction == "none":
        reason = "ignored: touches no data/{HYP}/{slug}.json or rejected/{HYP}/{slug}.json entry"
    elif conflicts:
        reason = f"blocked: conflicts with main on {', '.join(conflicts)} — rebase and re-push"
    else:
        reason = decision.reason
    mergeable = bool(agent) and direction != "none" and decision.mergeable and not conflicts
    return PRInfo(
        num=pr.num, title=pr.title, author=pr.author, agent=agent,
        direction=direction, targets=targets,
        approvals=tally.approvals,
        approvers=_as_agents(tally.approvers, agent_to_user),
        request_changes_by=_as_agents(tally.request_changes_by, agent_to_user),
        tags=tags,
        mergeable=mergeable, status=pr.status, status_reason=reason,
        veto_closed=veto_closed,
        conflicts=conflicts, url=f"{_dataset_url(settings)}/discussions/{pr.num}",
    )


@router.get("/v1/prs", response_model=PRListing)
def list_prs(
    status: str = Query("open", description="open | closed | merged | all"),
    settings: Settings = Depends(get_settings_dep),
    hub: HubClient = Depends(get_hub),
    read_model: ReadModel = Depends(get_read_model),
) -> PRListing:
    _require_curation(settings)
    agent_to_user = _agent_to_user(read_model)
    main_tree = hub.list_dataset_tree(settings.curation_dataset, "main")
    q = "" if status == "all" else status
    items = [
        _pr_info(settings, hub, pr, agent_to_user, main_tree)
        for pr in hub.list_dataset_prs(settings.curation_dataset, status=q)
    ]
    return PRListing(count=len(items), dataset=settings.curation_dataset, items=items)


@router.get("/v1/prs/{num}", response_model=PRInfo)
def get_pr(
    num: int,
    settings: Settings = Depends(get_settings_dep),
    hub: HubClient = Depends(get_hub),
    read_model: ReadModel = Depends(get_read_model),
) -> PRInfo:
    _require_curation(settings)
    for pr in hub.list_dataset_prs(settings.curation_dataset, status=""):
        if pr.num == num:
            main_tree = hub.list_dataset_tree(settings.curation_dataset, "main")
            return _pr_info(settings, hub, pr, _agent_to_user(read_model), main_tree)
    raise NotFound(f"PR #{num}")


def _entries(
    settings: Settings, hub: HubClient, hypothesis: str | None, location: str,
) -> tuple[list[dict], dict[str, int]]:
    """Entries under `{location}/{HYP}/{slug}.json`, optionally scoped to one
    hypothesis. Contents are only read for the single-hypothesis view — the
    all-hypotheses view stays a single tree listing, no per-file fetches."""
    tree = hub.list_dataset_tree(settings.curation_dataset, "main")
    rows: list[dict] = []
    by_hyp: dict[str, int] = {h: 0 for h in HYPOTHESES}
    for path in sorted(tree):
        parsed = parse_entry_path(path)
        if not parsed or parsed[0] != location:
            continue
        _, hyp, slug = parsed
        by_hyp[hyp] += 1
        if hypothesis is not None and hyp != hypothesis:
            continue
        row = {"hypothesis": hyp, "slug": slug, "path": path}
        if hypothesis is not None:
            raw = hub.read_dataset_bytes(settings.curation_dataset, path, "main")
            if raw:
                try:
                    row.update(json.loads(raw.decode("utf-8")))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass
        rows.append(row)
    return rows, by_hyp


@router.get("/v1/final-set", response_model=FinalSetResponse)
@router.get("/v1/final-set/{hypothesis}", response_model=FinalSetResponse)
def final_set(
    hypothesis: str | None = None,
    settings: Settings = Depends(get_settings_dep),
    hub: HubClient = Depends(get_hub),
) -> FinalSetResponse:
    _require_curation(settings)
    if hypothesis is not None and hypothesis not in HYPOTHESES:
        raise NotFound(f"unknown hypothesis {hypothesis!r}")
    rows, by_hyp = _entries(settings, hub, hypothesis, "data")
    items = [
        FinalSetEntry(
            hypothesis=r["hypothesis"], slug=r["slug"], path=r["path"],
            doi=r.get("doi"), pubmed_id=r.get("pubmed_id"), paper_type=r.get("paper_type"),
            tag=r.get("tag"), proposed_by=r.get("proposed_by"),
            n_quotes=(len(r["quotes"]) if "quotes" in r else None),
        )
        for r in rows
    ]
    return FinalSetResponse(
        dataset=settings.curation_dataset, count=len(items), by_hypothesis=by_hyp, items=items,
    )


@router.get("/v1/rejected", response_model=RejectedResponse)
@router.get("/v1/rejected/{hypothesis}", response_model=RejectedResponse)
def rejected(
    hypothesis: str | None = None,
    settings: Settings = Depends(get_settings_dep),
    hub: HubClient = Depends(get_hub),
) -> RejectedResponse:
    """Candidates judged unrelated to a hypothesis — kept on record so nobody
    re-proposes one without a new argument. Separate from the final set: these
    papers were considered and set aside, not merely un-reviewed."""
    _require_curation(settings)
    if hypothesis is not None and hypothesis not in HYPOTHESES:
        raise NotFound(f"unknown hypothesis {hypothesis!r}")
    rows, by_hyp = _entries(settings, hub, hypothesis, "rejected")
    items = [
        RejectedEntry(
            hypothesis=r["hypothesis"], slug=r["slug"], path=r["path"],
            doi=r.get("doi"), pubmed_id=r.get("pubmed_id"), paper_type=r.get("paper_type"),
            justification=r.get("justification"), proposed_by=r.get("proposed_by"),
        )
        for r in rows
    ]
    return RejectedResponse(
        dataset=settings.curation_dataset, count=len(items), by_hypothesis=by_hyp, items=items,
    )


@router.get("/v1/merges", response_model=MergeListing)
def list_merges(
    settings: Settings = Depends(get_settings_dep),
    read_model: ReadModel = Depends(get_read_model),
) -> MergeListing:
    _require_curation(settings)
    items: list[MergeInfo] = []
    for r in read_model.records(settings.merge_records_prefix.strip("/")):
        if getattr(r, "parse_error", False):
            continue
        fm = r.frontmatter
        items.append(MergeInfo(
            filename=r.filename,
            pr_number=int(fm.get("pr_number") or 0),
            direction=str(fm.get("direction") or ""),
            agent=str(fm.get("agent") or ""),
            approvers=list(fm.get("approvers") or []),
            included=list(fm.get("included") or []),
            rejected=list(fm.get("rejected") or []),
            tags=dict(fm.get("tags") or {}),
            excluded=list(fm.get("excluded") or []),
            unrejected=list(fm.get("unrejected") or []),
            timestamp=str(fm.get("timestamp") or ""),
        ))
    items.sort(key=lambda m: m.filename, reverse=True)
    return MergeListing(count=len(items), items=items)
