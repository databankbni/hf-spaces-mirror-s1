#!/usr/bin/env python3
"""open_pr.py — propose or review a paper in the MecCog final-set dataset.

The final set is a Hugging Face dataset; you curate it through native Hub Pull
Requests. This client opens include/exclude PRs (with the evidence rendered as a
table in the PR description) and posts reviews. It needs only `huggingface_hub`
and your HF login (`hf auth login`).

Every include PR carries a `--tag`, the whole relevance call:

  primary    experiments directly test this hypothesis
  secondary  related to the hypothesis, but less direct
  unrelated  doesn't bear on it — filed as a record, not a candidate

`primary`/`secondary` land in the final set (`data/{HYP}/{slug}.json`);
`unrelated` is filed at `rejected/{HYP}/{slug}.json` instead, so the call is on
record and nobody re-proposes the same paper without a new argument.

Examples
--------
# Propose adding a candidate paper (evidence pulled from candidates/{HYP}.json).
# --session must name a session whose FULL trace you've shared, or the bot won't merge:
python open_pr.py include --agent reader-a --hyp M1H1 --doi 10.1002/jnr.22073 \
    --tag primary --session 70514175-a3c3-... \
    --justification "directly measures APOE4-vs-APOE3 ABCA1 in human astrocytes"

# A paper that touches the hypothesis but only loosely:
python open_pr.py include --agent reader-a --hyp M1H1 --doi 10.1002/jnr.22074 \
    --tag secondary --session 70514175-a3c3-... \
    --justification "mouse model, not human astrocytes, but same pathway"

# A paper that doesn't bear on the hypothesis at all — filed, not discarded:
python open_pr.py include --agent reader-a --hyp M1H1 --doi 10.1002/jnr.22075 \
    --tag unrelated --session 70514175-a3c3-... \
    --justification "APOE4 in cardiac tissue, no astrocyte or ABCA1 data"

# Propose removing a paper already in the final set (or rejected/):
python open_pr.py exclude --agent reader-a --hyp M1H1 --doi 10.1002/jnr.22073 \
    --session 70514175-a3c3-... --justification "off-topic: not human astrocytes"

# Review someone else's PR:
python open_pr.py review --pr 12 --approve --message "checked the quote, solid"
python open_pr.py review --pr 12 --request-changes --message "wrong compartment"
"""
from __future__ import annotations

import argparse
import json
import re
import sys

from huggingface_hub import (
    CommitOperationAdd,
    CommitOperationDelete,
    HfApi,
    hf_hub_download,
)

DATASET = "MecCogAgenticChallenge/meccog-final-set"   # move to MecCogAgenticChallenge/... in production
HYPOTHESES = ("M1H1", "M1H2", "M3H1", "M3H2", "M3H3")
TAGS = ("primary", "secondary", "unrelated")
_LOCATION_BY_TAG = {"primary": "data", "secondary": "data", "unrelated": "rejected"}


def sanitize_doi_slug(doi: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]", "-", doi.replace(":", "-").replace("/", "-")).strip("-")


def _cell(x) -> str:
    return "" if x is None else str(x).replace("|", "\\|").replace("\n", " ").strip()


def render_evidence_md(quotes: list[dict]) -> str:
    if not quotes:
        return "_No quotes attached — filed as `unrelated`._"
    lines = [f"### Evidence — {len(quotes)} quote(s)", "",
             "| # | Finding | Quote | Data location | Effect | P | N | Rel | Sources |",
             "|---|---|---|---|---|---|---|---|---|"]
    for i, q in enumerate(quotes, 1):
        lines.append("| {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
            i, _cell(q.get("finding")), _cell(q.get("quote")), _cell(q.get("data_location")),
            _cell(q.get("effect_size")), _cell(q.get("p_value")), _cell(q.get("sample_size")),
            _cell(q.get("relevance")), _cell(", ".join(q.get("sources") or []))))
    return "\n".join(lines)


def _load_candidate(api: HfApi, hyp: str, doi: str) -> dict:
    path = hf_hub_download(DATASET, f"candidates/{hyp}.json", repo_type="dataset")
    cand = json.load(open(path))
    for p in cand["papers"]:
        if p["doi"] == doi:
            return p
    sys.exit(f"error: {doi} is not a candidate for {hyp}. See candidates/{hyp}.json")


def cmd_include(api: HfApi, args) -> None:
    paper = _load_candidate(api, args.hyp, args.doi)
    slug = sanitize_doi_slug(args.doi)
    location = _LOCATION_BY_TAG[args.tag]
    # `unrelated` doesn't need to manufacture a supporting quote — the whole
    # point of the tag is that none of the paper's evidence bears directly on
    # the hypothesis — so only primary/secondary carry the candidate's quotes.
    quotes = [] if args.tag == "unrelated" else paper["quotes"]
    entry = {
        "hypothesis": args.hyp, "doi": args.doi, "pubmed_id": paper.get("pubmed_id"),
        "paper_type": paper.get("paper_type"), "tag": args.tag, "quotes": quotes,
        "proposed_by": args.agent, "justification": args.justification,
    }
    path = f"{location}/{args.hyp}/{slug}.json"
    verb = "Filing as unrelated to" if args.tag == "unrelated" else f"Proposing ({args.tag}) for"
    desc = (f"agent: {args.agent}\nsession: {args.session}\n\n"
            f"{verb} **{args.hyp}**: **{args.doi}** "
            f"(PMID {paper.get('pubmed_id')}, {paper.get('paper_type')}).\n\n"
            f"**Justification:** {args.justification}\n\n"
            f"{render_evidence_md(quotes)}\n\n---\n"
            f"Reviewers: reply `/approve` or `/request-changes` (first line). See CONTRIBUTING.md.")
    c = api.create_commit(
        repo_id=DATASET, repo_type="dataset",
        operations=[CommitOperationAdd(path_in_repo=path,
                                       path_or_fileobj=json.dumps(entry, ensure_ascii=False, indent=1).encode())],
        commit_message=f"{args.tag}: {args.doi} for {args.hyp}",
        commit_description=desc, create_pr=True)
    print("opened include PR:", c.pr_url)


def _existing_path(api: HfApi, hyp: str, doi: str) -> str:
    """Where a live entry for (hyp, doi) actually sits — data/ or rejected/ —
    so exclude doesn't have to be told what an include already decided."""
    slug = sanitize_doi_slug(doi)
    files = set(api.list_repo_files(DATASET, repo_type="dataset"))
    for location in ("data", "rejected"):
        path = f"{location}/{hyp}/{slug}.json"
        if path in files:
            return path
    sys.exit(f"error: no entry for {doi} under {hyp} in data/ or rejected/ — "
             f"check GET /v1/final-set/{hyp} and /v1/rejected/{hyp}")


def cmd_exclude(api: HfApi, args) -> None:
    path = _existing_path(api, args.hyp, args.doi)
    desc = (f"agent: {args.agent}\nsession: {args.session}\n\n"
            f"Proposing to **remove** `{path}`.\n\n"
            f"**Justification:** {args.justification}\n\n---\n"
            f"Reviewers: reply `/approve` or `/request-changes` (first line). See CONTRIBUTING.md.")
    c = api.create_commit(
        repo_id=DATASET, repo_type="dataset",
        operations=[CommitOperationDelete(path_in_repo=path)],
        commit_message=f"Exclude {args.doi} from {args.hyp}",
        commit_description=desc, create_pr=True)
    print("opened exclude PR:", c.pr_url)


def cmd_review(api: HfApi, args) -> None:
    verdict = ("/approve" if args.approve else "/request-changes" if args.request_changes
               else "/comment")
    header = f"agent: {args.agent}\n" if args.agent else ""
    body = f"{verdict}\n{header}{args.message or ''}".rstrip()
    api.comment_discussion(repo_id=DATASET, repo_type="dataset",
                           discussion_num=args.pr, comment=body)
    print(f"posted {verdict} on PR #{args.pr}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("include")
    p.add_argument("--agent", required=True)
    p.add_argument("--hyp", required=True, choices=HYPOTHESES)
    p.add_argument("--doi", required=True)
    p.add_argument("--tag", required=True, choices=TAGS,
                   help="primary = directly tests the hypothesis; secondary = related but "
                        "less direct; unrelated = doesn't bear on it, filed as a record")
    p.add_argument("--justification", required=True)
    p.add_argument("--session", required=True,
                   help="your working session id — its full trace must be shared "
                        "(`share_trace.py --full`) or the bot won't merge")

    p = sub.add_parser("exclude")
    p.add_argument("--agent", required=True)
    p.add_argument("--hyp", required=True, choices=HYPOTHESES)
    p.add_argument("--doi", required=True)
    p.add_argument("--justification", required=True)
    p.add_argument("--session", required=True,
                   help="your working session id — its full trace must be shared "
                        "(`share_trace.py --full`) or the bot won't merge")

    p = sub.add_parser("review")
    p.add_argument("--pr", type=int, required=True)
    p.add_argument("--agent", default=None, help="only needed if reviewing from a different HF account")
    p.add_argument("--message", default="")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--approve", action="store_true")
    g.add_argument("--request-changes", dest="request_changes", action="store_true")
    g.add_argument("--comment", action="store_true")

    args = ap.parse_args()
    api = HfApi()
    {"include": cmd_include, "exclude": cmd_exclude, "review": cmd_review}[args.cmd](api, args)


if __name__ == "__main__":
    main()
