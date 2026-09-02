"""End-to-end curation: the merge-bot (tally → gate → merge → record → index)
and the read endpoints over PRs / final-set / rejected / merges."""
import json

from app.frontmatter import serialise
from fakes import seed_agent

DATASET = "test-org/final"

_LOCATION_BY_TAG = {"primary": "data", "secondary": "data", "unrelated": "rejected"}


def _env(make_env, **kw):
    # Trace gate is exercised by its own tests; keep the logic tests focused by
    # disabling it here unless a test opts back in.
    kw.setdefault("MERGE_REQUIRE_TRACE", "false")
    return make_env(
        CURATION_ENABLED="true",
        MERGE_BOT_ENABLED="true",
        CURATION_DATASET=DATASET,
        **kw,
    )


def _seed_trace(env, agent="reader-a", session="sess-1", share="full"):
    env.hub.seed(f"traces/{agent}/{session}/manifest.md",
                 serialise({"schema_version": 1, "session_id": session, "share": share}, ""))


def _entry_json(doi="10.1/x", hyp="M1H1", proposed_by="reader-a", tag="primary", quotes=None):
    if quotes is None:
        quotes = [] if tag == "unrelated" else [
            {"quote": "APOE4 lowers ABCA1", "finding": "f", "data_location": "Fig1C",
             "effect_size": "40%", "p_value": "0.05", "sample_size": 3},
        ]
    return json.dumps({
        "hypothesis": hyp, "doi": doi, "pubmed_id": "1",
        "paper_type": "PubMed published", "tag": tag, "quotes": quotes,
        "proposed_by": proposed_by, "justification": "directly on target for the hypothesis",
    })


def _both_agents(env):
    seed_agent(env.hub, "reader-a", hf_user="alice")
    seed_agent(env.hub, "reviewer-b", hf_user="bob")


def _include_pr(env, doi, *, comments, author="alice", agent="reader-a", hyp="M1H1", tag="primary",
                quotes=None):
    slug = doi.replace("/", "-").replace(":", "-")
    loc = _LOCATION_BY_TAG[tag]
    return env.hub.add_pr(
        DATASET, author=author,
        description=f"agent: {agent}\n\nAdds {doi}.",
        files={f"{loc}/{hyp}/{slug}.json":
               _entry_json(doi=doi, hyp=hyp, proposed_by=agent, tag=tag, quotes=quotes)},
        comments=comments,
    )


# ── merge happy path ─────────────────────────────────────────────────
def test_merges_approved_include_pr_and_records(make_env):
    env = _env(make_env)
    _both_agents(env)
    num = env.hub.add_pr(
        DATASET, author="alice",
        description="agent: reader-a\n\nAdds a paper.",
        title="Include 10.1/x for M1H1",
        files={"data/M1H1/10.1-x.json": _entry_json()},
        comments=[("bob", "/approve\nchecked the quote")],
    )
    assert env.merge_bot.poll_once() == [num]
    assert num in env.hub.merged_prs
    # entry now on main
    assert "data/M1H1/10.1-x.json" in env.hub.datasets[DATASET]
    # merge record written and attributed
    recs = env.read_model.records("curation_merges")
    assert len(recs) == 1
    fm = recs[0].frontmatter
    assert fm["agent"] == "reader-a" and fm["direction"] == "include"
    assert fm["approvers"] == ["reviewer-b"]  # bob's HF user mapped to their agent
    assert fm["included"] == ["M1H1/10.1-x"]
    assert fm["tags"] == {"M1H1/10.1-x": "primary"}
    # README index regenerated
    assert (DATASET, "README.md") in env.hub.dataset_uploads
    readme = env.hub.datasets[DATASET]["README.md"].decode("utf-8")
    assert "| M1H1 | 1 | 0 | 0 |" in readme
    # idempotent
    assert env.merge_bot.poll_once() == []


def test_challenge_closed_blocks_merge_and_comments_once(make_env):
    env = _env(make_env, CHALLENGE_CLOSED="true", CHALLENGE_ENDED_AT="2026-08-28")
    _both_agents(env)
    num = _include_pr(env, "10.1/x", comments=[("bob", "/approve")])
    assert env.merge_bot.poll_once() == []
    assert num not in env.hub.merged_prs
    thread = env.hub.get_pr_thread(DATASET, num)
    assert any("challenge-closed" in c.text for c in thread.comments)
    assert any("2026-08-28" in c.text for c in thread.comments)
    # idempotent: no duplicate comment on a second pass
    assert env.merge_bot.poll_once() == []
    thread2 = env.hub.get_pr_thread(DATASET, num)
    assert sum("challenge-closed" in c.text for c in thread2.comments) == 1


def test_exclude_pr_removes_entry(make_env):
    env = _env(make_env)
    _both_agents(env)
    env.hub.seed_dataset_file(DATASET, "data/M1H1/10.1-x.json", _entry_json())
    num = env.hub.add_pr(
        DATASET, author="alice",
        description="agent: reader-a\n\nRemove: off-topic on reflection.",
        removes=["data/M1H1/10.1-x.json"],
        comments=[("bob", "/approve agreed")],
    )
    assert env.merge_bot.poll_once() == [num]
    assert "data/M1H1/10.1-x.json" not in env.hub.datasets[DATASET]
    fm = env.read_model.records("curation_merges")[0].frontmatter
    assert fm["direction"] == "exclude" and fm["excluded"] == ["M1H1/10.1-x"]


# ── the tag protocol: where a paper lands ─────────────────────────────
def test_secondary_tag_still_lands_in_the_final_set(make_env):
    env = _env(make_env)
    _both_agents(env)
    num = _include_pr(env, "10.1/a", tag="secondary", comments=[("bob", "/approve\nrelated, less direct")])
    assert env.merge_bot.poll_once() == [num]
    assert "data/M1H1/10.1-a.json" in env.hub.datasets[DATASET]
    fm = env.read_model.records("curation_merges")[0].frontmatter
    assert fm["included"] == ["M1H1/10.1-a"] and fm["tags"]["M1H1/10.1-a"] == "secondary"


def test_unrelated_tag_lands_in_rejected_not_the_final_set(make_env):
    env = _env(make_env)
    _both_agents(env)
    num = _include_pr(env, "10.1/a", tag="unrelated", comments=[("bob", "/approve\nno bearing on it")])
    assert env.merge_bot.poll_once() == [num]
    assert "rejected/M1H1/10.1-a.json" in env.hub.datasets[DATASET]
    assert "data/M1H1/10.1-a.json" not in env.hub.datasets[DATASET]
    fm = env.read_model.records("curation_merges")[0].frontmatter
    assert fm["rejected"] == ["M1H1/10.1-a"] and fm["included"] == []
    assert fm["tags"]["M1H1/10.1-a"] == "unrelated"
    readme = env.hub.datasets[DATASET]["README.md"].decode("utf-8")
    assert "| M1H1 | 0 | 0 | 1 |" in readme


def test_unrelated_entry_needs_no_quotes_to_merge(make_env):
    env = _env(make_env)
    _both_agents(env)
    num = _include_pr(env, "10.1/a", tag="unrelated", quotes=[],
                      comments=[("bob", "/approve\nagreed, off-topic")])
    assert env.merge_bot.poll_once() == [num]


def test_tag_mismatched_with_folder_is_held_as_invalid(make_env):
    env = _env(make_env)
    _both_agents(env)
    # entry claims "unrelated" but is filed under data/ (final set)
    bad = json.loads(_entry_json(tag="unrelated"))
    num = env.hub.add_pr(
        DATASET, author="alice", description="agent: reader-a\n\nmislabeled",
        files={"data/M1H1/10.1-x.json": json.dumps(bad)},
        comments=[("bob", "/approve")],
    )
    assert env.merge_bot.poll_once() == []
    assert num not in env.hub.merged_prs
    assert any("invalid-entry" in c for _, c in env.hub.pr_comments_posted)


def test_excluding_a_rejected_entry_is_tracked_as_unrejected(make_env):
    env = _env(make_env)
    _both_agents(env)
    _include_pr(env, "10.1/a", tag="unrelated", comments=[("bob", "/approve")])
    env.merge_bot.poll_once()

    num = env.hub.add_pr(
        DATASET, author="alice", description="agent: reader-a\n\nreconsider it",
        removes=["rejected/M1H1/10.1-a.json"], comments=[("bob", "/approve worth another look")],
    )
    assert env.merge_bot.poll_once() == [num]
    assert "rejected/M1H1/10.1-a.json" not in env.hub.datasets[DATASET]
    fm = env.read_model.records("curation_merges")[-1].frontmatter
    assert fm["unrejected"] == ["M1H1/10.1-a"] and fm["excluded"] == []


def test_digest_curation_block_tallies_tags_per_hypothesis(make_env):
    env = _env(make_env)
    _both_agents(env)
    _include_pr(env, "10.1/a", tag="primary", comments=[("bob", "/approve")])
    _include_pr(env, "10.1/b", tag="secondary", comments=[("bob", "/approve")])
    _include_pr(env, "10.1/c", tag="unrelated", comments=[("bob", "/approve")])
    env.merge_bot.poll_once()

    body = env.client.get("/v1/digest?as=reviewer-b").json()["curation"]
    assert body["primary_total"] == 1 and body["secondary_total"] == 1 and body["unrelated_total"] == 1
    m1h1 = next(h for h in body["by_hypothesis"] if h["hypothesis"] == "M1H1")
    assert (m1h1["primary"], m1h1["secondary"], m1h1["unrelated"]) == (1, 1, 1)


def test_digest_curation_tallies_survive_a_later_exclude(make_env):
    env = _env(make_env)
    _both_agents(env)
    _include_pr(env, "10.1/a", tag="primary", comments=[("bob", "/approve")])
    env.merge_bot.poll_once()
    env.hub.add_pr(
        DATASET, author="alice", description="agent: reader-a\n\nremove",
        removes=["data/M1H1/10.1-a.json"], comments=[("bob", "/approve")],
    )
    env.merge_bot.poll_once()
    body = env.client.get("/v1/digest?as=reviewer-b").json()["curation"]
    assert body["primary_total"] == 0


# ── gates ────────────────────────────────────────────────────────────
def test_self_approval_does_not_merge(make_env):
    env = _env(make_env)   # default distinct_level=account
    _both_agents(env)
    env.hub.add_pr(
        DATASET, author="alice", description="agent: reader-a\n\nmine",
        files={"data/M1H1/10.1-x.json": _entry_json()},
        comments=[("alice", "/approve looks great if I say so myself")],
    )
    assert env.merge_bot.poll_once() == []


def test_request_changes_vetoes(make_env):
    env = _env(make_env)
    _both_agents(env)
    seed_agent(env.hub, "reviewer-c", hf_user="carol")
    env.hub.add_pr(
        DATASET, author="alice", description="agent: reader-a\n\np",
        files={"data/M1H1/10.1-x.json": _entry_json()},
        comments=[("bob", "/approve"), ("carol", "/request-changes wrong compartment")],
    )
    assert env.merge_bot.poll_once() == []


def test_veto_closes_the_pr_by_default(make_env):
    env = _env(make_env)
    _both_agents(env)
    seed_agent(env.hub, "reviewer-c", hf_user="carol")
    num = env.hub.add_pr(
        DATASET, author="alice", description="agent: reader-a\n\np",
        files={"data/M1H1/10.1-x.json": _entry_json()},
        comments=[("bob", "/approve"), ("carol", "/request-changes wrong compartment")],
    )
    assert env.merge_bot.poll_once() == []
    assert num in env.hub.closed_prs
    assert num not in env.hub.merged_prs
    assert any("vetoed" in c for _, c in env.hub.pr_comments_posted)
    # already closed -> the next poll pass (which only scans open PRs) can't
    # see it, so the closing comment is never posted twice.
    env.merge_bot.poll_once()
    assert sum("vetoed" in c for _, c in env.hub.pr_comments_posted) == 1


def test_veto_close_disabled_leaves_pr_open(make_env):
    env = _env(make_env, MERGE_CLOSE_ON_VETO="false")
    _both_agents(env)
    seed_agent(env.hub, "reviewer-c", hf_user="carol")
    num = env.hub.add_pr(
        DATASET, author="alice", description="agent: reader-a\n\np",
        files={"data/M1H1/10.1-x.json": _entry_json()},
        comments=[("bob", "/approve"), ("carol", "/request-changes wrong compartment")],
    )
    assert env.merge_bot.poll_once() == []
    assert num not in env.hub.closed_prs
    assert env.hub.list_dataset_prs(DATASET, status="open")[0].num == num


def test_veto_lifted_by_a_newer_approval_merges_instead_of_closing(make_env):
    env = _env(make_env)
    _both_agents(env)
    seed_agent(env.hub, "reviewer-c", hf_user="carol")
    num = env.hub.add_pr(
        DATASET, author="alice", description="agent: reader-a\n\np",
        files={"data/M1H1/10.1-x.json": _entry_json()},
        comments=[
            ("bob", "/approve"),
            ("carol", "/request-changes wrong compartment"),
            ("carol", "/approve looks fine now"),
        ],
    )
    assert env.merge_bot.poll_once() == [num]
    assert num not in env.hub.closed_prs


def test_mismatched_agent_header_ignored(make_env):
    env = _env(make_env)
    _both_agents(env)
    # declared agent belongs to alice, but the PR author is bob
    env.hub.add_pr(
        DATASET, author="bob", description="agent: reader-a\n\np",
        files={"data/M1H1/10.1-x.json": _entry_json()},
        comments=[("carol", "/approve")],
    )
    assert env.merge_bot.poll_once() == []


def test_invalid_entry_held_with_comment(make_env):
    env = _env(make_env)
    _both_agents(env)
    bad = json.loads(_entry_json())
    bad["justification"] = ""   # invalid: missing justification
    num = env.hub.add_pr(
        DATASET, author="alice", description="agent: reader-a\n\np",
        files={"data/M1H1/10.1-x.json": json.dumps(bad)},
        comments=[("bob", "/approve")],
    )
    assert env.merge_bot.poll_once() == []
    assert num not in env.hub.merged_prs
    assert any("invalid-entry" in c for _, c in env.hub.pr_comments_posted)
    # the nudge is posted at most once
    env.merge_bot.poll_once()
    assert sum("invalid-entry" in c for _, c in env.hub.pr_comments_posted) == 1


def test_distinct_level_none_allows_self_merge_for_testing(make_env):
    env = _env(make_env, MERGE_DISTINCT_LEVEL="none")
    seed_agent(env.hub, "reader-a", hf_user="alice")
    num = env.hub.add_pr(
        DATASET, author="alice", description="agent: reader-a\n\nsolo test",
        files={"data/M1H1/10.1-x.json": _entry_json()},
        comments=[("alice", "/approve")],
    )
    assert env.merge_bot.poll_once() == [num]


# ── read endpoints ───────────────────────────────────────────────────
def test_prs_endpoint_reports_tally_direction_and_tag(make_env):
    env = _env(make_env)
    _both_agents(env)
    env.hub.add_pr(
        DATASET, author="alice", description="agent: reader-a\n\np",
        files={"data/M1H1/10.1-x.json": _entry_json(tag="secondary")},
        comments=[("bob", "/approve"), ("bob-2", "/comment reading it now")],
    )
    r = env.client.get("/v1/prs").json()
    assert r["count"] == 1 and r["dataset"] == DATASET
    pr = r["items"][0]
    assert pr["agent"] == "reader-a" and pr["direction"] == "include"
    assert pr["approvals"] == 1 and pr["mergeable"] is True
    assert pr["targets"] == ["M1H1/10.1-x"]
    assert pr["tags"] == ["secondary"]


def test_prs_endpoint_reports_veto_closed(make_env):
    env = _env(make_env)
    _both_agents(env)
    seed_agent(env.hub, "reviewer-c", hf_user="carol")
    num = env.hub.add_pr(
        DATASET, author="alice", description="agent: reader-a\n\np",
        files={"data/M1H1/10.1-x.json": _entry_json()},
        comments=[("bob", "/approve"), ("carol", "/request-changes wrong compartment")],
    )
    env.merge_bot.poll_once()  # closes it for the veto

    closed = env.client.get("/v1/prs?status=closed").json()["items"]
    pr = next(p for p in closed if p["num"] == num)
    assert pr["status"] == "closed" and pr["veto_closed"] is True
    assert pr["request_changes_by"] == ["reviewer-c"]
    assert "vetoed" in pr["status_reason"]

    # a normally-merged PR is closed too, but never carries the veto flag.
    merged_num = env.hub.add_pr(
        DATASET, author="alice", description="agent: reader-a\n\nanother",
        files={"data/M1H2/10.2-y.json": _entry_json(doi="10.2/y", hyp="M1H2")},
        comments=[("bob", "/approve")],
    )
    env.merge_bot.poll_once()
    merged_row = next(
        p for p in env.client.get("/v1/prs?status=merged").json()["items"] if p["num"] == merged_num
    )
    assert merged_row["veto_closed"] is False


def test_final_set_and_merges_endpoints(make_env):
    env = _env(make_env)
    _both_agents(env)
    env.hub.add_pr(
        DATASET, author="alice", description="agent: reader-a\n\np",
        files={"data/M1H1/10.1-x.json": _entry_json()},
        comments=[("bob", "/approve")],
    )
    env.merge_bot.poll_once()
    fs = env.client.get("/v1/final-set").json()
    assert fs["count"] == 1 and fs["by_hypothesis"]["M1H1"] == 1
    fh = env.client.get("/v1/final-set/M1H1").json()
    assert fh["items"][0]["doi"] == "10.1/x" and fh["items"][0]["n_quotes"] == 1
    assert fh["items"][0]["tag"] == "primary"
    merges = env.client.get("/v1/merges").json()
    assert merges["count"] == 1 and merges["items"][0]["direction"] == "include"


def test_rejected_endpoint_separate_from_final_set(make_env):
    env = _env(make_env)
    _both_agents(env)
    _include_pr(env, "10.1/a", tag="primary", comments=[("bob", "/approve")])
    _include_pr(env, "10.1/b", tag="unrelated", comments=[("bob", "/approve")])
    env.merge_bot.poll_once()

    fs = env.client.get("/v1/final-set").json()
    assert fs["count"] == 1 and [i["slug"] for i in fs["items"]] == ["10.1-a"]

    rej = env.client.get("/v1/rejected").json()
    assert rej["count"] == 1 and rej["by_hypothesis"]["M1H1"] == 1
    rh = env.client.get("/v1/rejected/M1H1").json()
    assert rh["items"][0]["doi"] == "10.1/b"
    assert rh["items"][0]["justification"] == "directly on target for the hypothesis"


def test_trace_required_holds_merge_until_full_trace_shared(make_env):
    # LISTING_TTL_S=0 so a trace seeded mid-test is seen on the next poll (in
    # production the bot's own poll interval covers this staleness window).
    env = _env(make_env, MERGE_REQUIRE_TRACE="true", LISTING_TTL_S="0")   # gate on
    _both_agents(env)
    num = env.hub.add_pr(
        DATASET, author="alice",
        description="agent: reader-a\nsession: sess-1\n\np",
        files={"data/M1H1/10.1-x.json": _entry_json()},
        comments=[("bob", "/approve")],
    )
    # no trace shared yet → held with a one-time comment
    assert env.merge_bot.poll_once() == []
    assert any("trace-required" in c for _, c in env.hub.pr_comments_posted)
    assert sum("trace-required" in c for _, c in env.hub.pr_comments_posted) == 1
    env.merge_bot.poll_once()
    assert sum("trace-required" in c for _, c in env.hub.pr_comments_posted) == 1
    # share a full trace for that session → merges on the next pass
    _seed_trace(env, "reader-a", "sess-1", share="full")
    assert env.merge_bot.poll_once() == [num]


def test_trace_gate_rejects_missing_session_header_and_stats_only(make_env):
    env = _env(make_env, MERGE_REQUIRE_TRACE="true", LISTING_TTL_S="0")
    _both_agents(env)
    # PR with no session: header
    env.hub.add_pr(
        DATASET, author="alice", description="agent: reader-a\n\nno session line",
        files={"data/M1H1/10.1-x.json": _entry_json()},
        comments=[("bob", "/approve")],
    )
    assert env.merge_bot.poll_once() == []
    # a stats-only trace is not enough when a full trace is required
    n2 = env.hub.add_pr(
        DATASET, author="alice", description="agent: reader-a\nsession: sess-2\n\np",
        files={"data/M1H2/10.2-y.json": _entry_json(doi="10.2/y", hyp="M1H2")},
        comments=[("bob", "/approve")],
    )
    _seed_trace(env, "reader-a", "sess-2", share="stats")
    assert env.merge_bot.poll_once() == []
    # upgrade to full → merges
    _seed_trace(env, "reader-a", "sess-2", share="full")
    assert env.merge_bot.poll_once() == [n2]


def test_curation_endpoints_404_when_disabled(make_env):
    env = make_env()   # curation disabled
    assert env.client.get("/v1/prs").status_code == 404
    assert env.client.get("/v1/final-set").status_code == 404
    assert env.client.get("/v1/rejected").status_code == 404
    assert env.client.get("/v1/merges").status_code == 404
