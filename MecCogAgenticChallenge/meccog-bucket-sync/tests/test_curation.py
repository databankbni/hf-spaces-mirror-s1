"""Pure curation logic: verdict parsing, review tally, merge decision, entry
validation, path/direction/tag detection."""
from app.curation import (
    decide_merge,
    detect_direction,
    entry_path,
    parse_agent_header,
    parse_entry_path,
    parse_review_verdict,
    sanitize_doi_slug,
    tally_reviews,
    validate_paper_entry,
)
from app.hub import PRComment


def C(author, text):
    return PRComment(author=author, text=text)


def _tally(comments, author_user="carol", author_agent=None, level="account"):
    return tally_reviews(comments, author_hf_user=author_user,
                         author_agent=author_agent, distinct_level=level)


# ── parsing ──────────────────────────────────────────────────────────
def test_parse_agent_header():
    assert parse_agent_header("agent: reader-a\n\nbody") == "reader-a"
    assert parse_agent_header("no header here") is None
    assert parse_agent_header("AGENT: X") is None  # case-sensitive key, lowercase id


def test_parse_review_verdict_first_line_only():
    assert parse_review_verdict("/approve\nlgtm") == "approve"
    assert parse_review_verdict("/request-changes wait") == "request-changes"
    assert parse_review_verdict("/comment just chatting") == "comment"
    assert parse_review_verdict("looks good /approve") is None  # not first token


def test_sanitize_and_parse_entry_path():
    assert sanitize_doi_slug("10.1038/s41586-025-09486-x") == "10.1038-s41586-025-09486-x"
    assert parse_entry_path("data/M1H1/10.1038-x.json") == ("data", "M1H1", "10.1038-x")
    assert parse_entry_path("rejected/M3H1/10.1038-x.json") == ("rejected", "M3H1", "10.1038-x")
    assert parse_entry_path("data/NOPE/x.json") is None  # unknown hypothesis
    assert parse_entry_path("candidates/M1H1.json") is None
    assert parse_entry_path("other/M1H1/x.json") is None  # not a recognised location


def test_entry_path_by_tag():
    assert entry_path("primary", "M1H1", "10.1-x") == "data/M1H1/10.1-x.json"
    assert entry_path("secondary", "M1H1", "10.1-x") == "data/M1H1/10.1-x.json"
    assert entry_path("unrelated", "M1H1", "10.1-x") == "rejected/M1H1/10.1-x.json"


# ── tally ────────────────────────────────────────────────────────────
def test_latest_verdict_wins_and_comment_withdraws():
    t = _tally([C("bob", "/request-changes no"), C("bob", "/approve ok now")])
    assert t.approvals == 1 and t.approvers == ["bob"] and not t.request_changes_by
    t2 = _tally([C("bob", "/approve"), C("bob", "/comment nvm withdrawing")])
    assert t2.approvals == 0 and not t2.request_changes_by


def test_self_approval_dropped_by_account_but_not_none():
    me = [C("carol", "/approve self")]
    assert _tally(me, author_user="carol", level="account").approvals == 0
    assert _tally(me, author_user="carol", level="account").ignored_self == 1
    assert _tally(me, author_user="carol", level="none").approvals == 1


def test_support_is_not_a_verdict():
    """`/support` (from the earlier vote system) and `/rank` (from the earlier
    ranking system) are both gone; only /approve, /request-changes, /comment
    are recognised. An unrecognised leading token must not withdraw a real
    prior verdict."""
    assert parse_review_verdict("/support nice") is None
    assert parse_review_verdict("/rank above 10.1/x") is None
    t = _tally([C("bob", "/support nice")])
    assert t.approvals == 0 and not t.approvers and not t.request_changes_by
    t2 = _tally([C("bob", "/approve ok"), C("bob", "/support also nice")])
    assert t2.approvals == 1 and t2.approvers == ["bob"]


# ── decide (veto model) ──────────────────────────────────────────────
def test_decide_needs_min_approvals():
    t = _tally([C("bob", "/comment just looking")])
    d = decide_merge(t, min_approvals=1, block_on_request_changes=True)
    assert not d.mergeable and "needs 1 approval" in d.reason


def test_decide_request_changes_vetoes_even_with_approval():
    t = _tally([C("bob", "/approve"), C("dave", "/request-changes")])
    d = decide_merge(t, min_approvals=1, block_on_request_changes=True)
    assert not d.mergeable and "request-changes" in d.reason
    # ... unless blocking is disabled
    d2 = decide_merge(t, min_approvals=1, block_on_request_changes=False)
    assert d2.mergeable


def test_decide_mergeable_on_clean_approval():
    t = _tally([C("bob", "/approve solid")])
    d = decide_merge(t, min_approvals=1, block_on_request_changes=True)
    assert d.mergeable and d.approvers == ["bob"]


# ── direction ────────────────────────────────────────────────────────
def test_detect_direction():
    assert detect_direction(["data/M1H1/a.json"], []) == "include"
    assert detect_direction(["rejected/M1H1/a.json"], []) == "include"
    assert detect_direction([], ["data/M3H1/b.json"]) == "exclude"
    assert detect_direction([], ["rejected/M3H1/b.json"]) == "exclude"
    assert detect_direction(["data/M1H1/a.json"], ["data/M1H1/b.json"]) == "mixed"
    assert detect_direction(["README.md"], []) == "none"


# ── entry validation ─────────────────────────────────────────────────
def _entry(**over):
    e = {
        "hypothesis": "M1H1", "doi": "10.1/x", "pubmed_id": "1",
        "paper_type": "PubMed published", "tag": "primary",
        "quotes": [{"quote": "q", "finding": "f", "data_location": "Fig1"}],
        "proposed_by": "reader-a", "justification": "on target",
    }
    e.update(over)
    return e


def test_valid_entry_passes():
    assert validate_paper_entry(_entry(), hyp="M1H1", slug="10.1-x", location="data") == []
    assert validate_paper_entry(_entry(tag="secondary"), hyp="M1H1", slug="10.1-x", location="data") == []


def test_entry_errors():
    assert "missing `justification`" in validate_paper_entry(
        _entry(justification=""), hyp="M1H1", slug="10.1-x", location="data")
    assert any("hypothesis" in e for e in validate_paper_entry(
        _entry(), hyp="M3H1", slug="10.1-x", location="data"))  # folder mismatch
    assert any("slug" in e for e in validate_paper_entry(
        _entry(), hyp="M1H1", slug="wrong-slug", location="data"))
    assert any("paper_type" in e for e in validate_paper_entry(
        _entry(paper_type="Blog"), hyp="M1H1", slug="10.1-x", location="data"))
    assert any("quotes" in e for e in validate_paper_entry(
        _entry(quotes=[]), hyp="M1H1", slug="10.1-x", location="data"))
    assert any("quote 1 missing `data_location`" in e for e in validate_paper_entry(
        _entry(quotes=[{"quote": "q", "finding": "f"}]), hyp="M1H1", slug="10.1-x", location="data"))


def test_entry_requires_a_known_tag():
    assert any("`tag`" in e for e in validate_paper_entry(
        _entry(tag=None), hyp="M1H1", slug="10.1-x", location="data"))
    assert any("`tag`" in e for e in validate_paper_entry(
        _entry(tag="maybe"), hyp="M1H1", slug="10.1-x", location="data"))


def test_entry_tag_must_match_its_folder():
    # a primary/secondary entry filed under rejected/, or vice versa
    errs = validate_paper_entry(_entry(tag="primary"), hyp="M1H1", slug="10.1-x", location="rejected")
    assert any("data/" in e for e in errs)
    errs = validate_paper_entry(_entry(tag="unrelated"), hyp="M1H1", slug="10.1-x", location="data")
    assert any("rejected/" in e for e in errs)


def test_unrelated_entries_do_not_need_quotes():
    entry = _entry(tag="unrelated", quotes=[])
    assert validate_paper_entry(entry, hyp="M1H1", slug="10.1-x", location="rejected") == []


def test_unrelated_entry_quotes_are_still_checked_if_present():
    entry = _entry(tag="unrelated", quotes=[{"quote": "q"}])   # missing finding/data_location
    errs = validate_paper_entry(entry, hyp="M1H1", slug="10.1-x", location="rejected")
    assert any("missing `finding`" in e for e in errs)
