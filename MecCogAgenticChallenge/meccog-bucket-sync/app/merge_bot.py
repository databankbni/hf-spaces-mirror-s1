"""The curation merge-bot.

A background poller that scans open Pull Requests on the final-set dataset,
tallies `/approve` reviews under the veto policy, and merges those that clear
the bar with the Space's admin token — agents can open PRs but cannot merge, so
"accepted by other agents" is enforced here. On a merge it writes a merge record
to the central bucket (the audit trail of what entered/left the final set) and
regenerates the README index. All work is best-effort: any Hub hiccup is logged
and retried on the next pass; the loop never dies.

A PR left blocked by an unresolved veto is closed (not just held) — the
review, not silence, has already spoken. `VETO_MARKER` on the closing comment
lets the read API keep reporting it as vetoed rather than indistinguishable
from any other closed PR.

Integrity: a PR is only considered if its description declares `agent: <id>`,
that agent is registered, and the agent's registered HF account matches the PR
author. An include PR's added entry files must pass `validate_paper_entry`
before the merge; a failing entry gets one explanatory comment and is held.
Relevance is decided once, by the entry's own `tag` (primary/secondary/
unrelated) — the bot only checks that the file landed at the path its tag
requires; there is no separate ranking pass to maintain.
"""
from __future__ import annotations

import json
import logging
import re
import threading

from app.config import Settings
from app.curation import (
    decide_merge,
    detect_direction,
    parse_agent_header,
    parse_entry_path,
    parse_session_header,
    tally_reviews,
    validate_paper_entry,
    HYPOTHESES,
    TAGS,
    VETO_MARKER,
)
from app.frontmatter import serialise
from app.hub import HubClient, PullRequest
from app.announce import unique_stamp_time
from app.naming import TRACES_FOLDER, stamp_filename, stamp_yaml, utc_now
from app.read_model import ReadModel


log = logging.getLogger(__name__)

_INDEX_START = "<!-- TOPIC-INDEX:START"
_INDEX_END = "<!-- TOPIC-INDEX:END -->"
_INVALID_MARKER = "<!-- merge-bot:invalid-entry -->"
_CONFLICT_MARKER = "<!-- merge-bot:conflict -->"
_TRACE_MARKER = "<!-- merge-bot:trace-required -->"
_CLOSED_MARKER = "<!-- merge-bot:challenge-closed -->"


def _thread_spawn(name: str, fn) -> None:
    threading.Thread(target=fn, name=name, daemon=True).start()


class MergeBot:
    def __init__(self, settings: Settings, hub: HubClient, read_model: ReadModel):
        self._settings = settings
        self._hub = hub
        self._rm = read_model
        self._repo = settings.curation_dataset
        self._merge_folder = settings.merge_records_prefix.strip("/")
        self._lock = threading.Lock()
        self._in_flight: set[int] = set()
        self._stop = threading.Event()

    # ── identity ─────────────────────────────────────────────────────
    def _agent_to_user(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for r in self._rm.records("agents"):
            if getattr(r, "parse_error", False):
                continue
            agent = r.filename.removesuffix(".md")
            user = str(r.frontmatter.get("hf_user") or "")
            if agent and user:
                out[agent] = user
        return out

    def _as_agents(self, names: list[str]) -> list[str]:
        """HF usernames -> registered agent ids, where known. Reviews are
        credited by agent id, because that is the name the board and every
        other agent use — a reviewer only declares `agent:` when reviewing
        from an account other than the one they registered with."""
        user_to_agent: dict[str, str] = {}
        for agent, user in self._agent_to_user().items():
            user_to_agent.setdefault(user, agent)
        return [user_to_agent.get(n, n) for n in names]

    def _already_merged(self, pr_num: int) -> bool:
        for r in self._rm.records(self._merge_folder):
            if not getattr(r, "parse_error", False) and int(r.frontmatter.get("pr_number") or 0) == pr_num:
                return True
        return False

    # ── the poll loop ────────────────────────────────────────────────
    def run_forever(self) -> None:
        log.info("merge-bot polling %s every %ss", self._repo, self._settings.merge_poll_s)
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception:  # never let the loop die
                log.exception("merge-bot poll pass failed")
            self._stop.wait(self._settings.merge_poll_s)

    def start(self) -> None:
        _thread_spawn("merge-bot", self.run_forever)

    def stop(self) -> None:
        self._stop.set()

    # ── one merge pass (also the unit-test entry point) ──────────────
    def poll_once(self) -> list[int]:
        """Process every open PR once; returns the PR numbers merged this pass."""
        merged: list[int] = []
        for pr in self._hub.list_dataset_prs(self._repo, status="open"):
            try:
                if self.process_pr(pr):
                    merged.append(pr.num)
            except Exception:
                log.exception("merge-bot: PR #%s failed", pr.num)
        return merged

    def process_pr(self, pr: PullRequest) -> bool:
        thread = self._hub.get_pr_thread(self._repo, pr.num)
        if self._settings.challenge_closed:
            self._note_closed(pr, thread)
            return False
        agent_to_user = self._agent_to_user()
        declared = parse_agent_header(thread.description)
        if not declared:
            log.info("PR #%s ignored: no `agent:` header", pr.num)
            return False
        if declared not in agent_to_user:
            log.info("PR #%s ignored: agent '%s' is not registered", pr.num, declared)
            return False
        if agent_to_user[declared] != pr.author:
            log.warning(
                "PR #%s ignored: declared agent '%s' belongs to '%s', not PR author '%s'",
                pr.num, declared, agent_to_user[declared], pr.author,
            )
            return False

        tally = tally_reviews(
            thread.comments,
            author_hf_user=pr.author,
            author_agent=declared,
            distinct_level=self._settings.distinct_level,
        )
        decision = decide_merge(
            tally,
            min_approvals=self._settings.merge_min_approvals,
            block_on_request_changes=self._settings.merge_block_on_request_changes,
        )
        if not decision.mergeable:
            vetoed = self._settings.merge_block_on_request_changes and tally.request_changes_by
            if vetoed and self._settings.merge_close_on_veto:
                self._close_on_veto(pr, thread, tally)
            return False

        # Trace gate: a merged curation decision must be backed by a shared
        # (full) trace for the author's declared session, mirroring the
        # requirement on POST /v1/results.
        trace_missing = self._trace_missing_reason(declared, thread.description)
        if trace_missing:
            self._note_missing_trace(pr, thread, trace_missing)
            return False

        with self._lock:  # single-flight + idempotency
            if pr.num in self._in_flight or self._already_merged(pr.num):
                return False
            self._in_flight.add(pr.num)
        try:
            return self._merge_and_record(pr, declared, decision, thread)
        finally:
            with self._lock:
                self._in_flight.discard(pr.num)

    def _merge_and_record(self, pr, declared, decision, thread) -> bool:
        main_tree = self._hub.list_dataset_tree(self._repo, "main")
        pr_tree = self._hub.list_dataset_tree(self._repo, f"refs/pr/{pr.num}")
        added = sorted(set(pr_tree) - set(main_tree))
        removed = sorted(set(main_tree) - set(pr_tree))
        direction = detect_direction(added, removed)
        if direction == "none":
            log.info("PR #%s ignored: touches no entry file", pr.num)
            return False

        # Include integrity: every added entry must be a well-formed paper
        # entry, and its `tag` must match the folder it was filed under.
        entries: list[tuple[str, str, str, str]] = []  # (location, hyp, slug, tag)
        for path in added:
            parsed = parse_entry_path(path)
            if not parsed:
                continue
            loc, hyp, slug = parsed
            raw = self._hub.read_dataset_bytes(self._repo, path, revision=f"refs/pr/{pr.num}")
            entry: object = None
            errs = ["could not read the added file"] if raw is None else []
            if raw is not None:
                try:
                    entry = json.loads(raw.decode("utf-8"))
                    errs = validate_paper_entry(entry, hyp=hyp, slug=slug, location=loc)
                except (json.JSONDecodeError, UnicodeDecodeError) as e:
                    errs = [f"invalid JSON: {e}"]
            if errs:
                self._note_invalid(pr, thread, path, errs)
                return False
            tag = str((entry or {}).get("tag") or "") if isinstance(entry, dict) else ""
            entries.append((loc, hyp, slug, tag))

        removed_entries = [parse_entry_path(p) for p in removed if parse_entry_path(p)]

        if not self._hub.merge_pr(self._repo, pr.num, comment="Merged by the MecCog merge-bot."):
            if thread.conflicting_files:
                self._note_conflict(pr, thread, thread.conflicting_files)
            return False

        self._write_merge_record(pr, declared, decision, direction, entries, removed_entries)
        self._regen_index()
        log.info("merged PR #%s (%s) by %s — approvers %s",
                 pr.num, direction, declared, decision.approvers)
        return True

    # ── side effects ─────────────────────────────────────────────────
    def _write_merge_record(self, pr, declared, decision, direction, entries, removed_entries) -> None:
        # Monotonic per-agent stamp: two PRs by the same agent merging in one
        # poll pass would otherwise mint the same `{stamp}_{agent}` filename
        # and silently overwrite each other's merge record.
        now = unique_stamp_time(declared, utc_now())
        approvers = self._as_agents(decision.approvers)
        fm = {
            "type": "curation_merge",
            "pr_number": pr.num,
            "direction": direction,
            "agent": declared,
            "author_hf_user": pr.author,
            "approvers": approvers,
            "timestamp": stamp_yaml(now),
            "included": [f"{h}/{s}" for loc, h, s, _ in entries if loc == "data"],
            "rejected": [f"{h}/{s}" for loc, h, s, _ in entries if loc == "rejected"],
            "tags": {f"{h}/{s}": tag for _, h, s, tag in entries},
            "excluded": [f"{h}/{s}" for loc, h, s in removed_entries if loc == "data"],
            "unrejected": [f"{h}/{s}" for loc, h, s in removed_entries if loc == "rejected"],
        }
        body = (f"PR [#{pr.num}]({self._dataset_url()}/discussions/{pr.num}) "
                f"({direction}) merged. Approved by {', '.join(approvers) or 'n/a'}.")
        path = f"{self._merge_folder}/{stamp_filename(declared, now)}"
        try:
            self._hub.write_text_central(path, serialise(fm, body))
            self._rm.write_through(path, fm, body, len(serialise(fm, body).encode("utf-8")),
                                   folder=self._merge_folder)
        except Exception as e:
            log.warning("merge record write failed for PR #%s: %s", pr.num, e)

    def _regen_index(self) -> None:
        """Rewrite the README index block with current counts per hypothesis,
        by tag, from the dataset's main tree."""
        tree = self._hub.list_dataset_tree(self._repo, "main")
        by_tag: dict[str, dict[str, int]] = {h: {t: 0 for t in TAGS} for h in HYPOTHESES}
        for path in tree:
            parsed = parse_entry_path(path)
            if not parsed:
                continue
            loc, hyp, slug = parsed
            raw = self._hub.read_dataset_bytes(self._repo, path, revision="main")
            tag = None
            if raw:
                try:
                    tag = json.loads(raw.decode("utf-8")).get("tag")
                except (json.JSONDecodeError, UnicodeDecodeError):
                    tag = None
            if tag not in TAGS:
                tag = "unrelated" if loc == "rejected" else "secondary"
            by_tag[hyp][tag] += 1

        final_total = sum(c["primary"] + c["secondary"] for c in by_tag.values())
        rejected_total = sum(c["unrelated"] for c in by_tag.values())
        lines = [
            _INDEX_START + " — auto-generated by the merge-bot; do not edit by hand -->",
            f"_Final set: {final_total} paper(s) across "
            f"{sum(1 for c in by_tag.values() if c['primary'] + c['secondary']) } hypotheses "
            f"&middot; {rejected_total} recorded as unrelated._",
            "",
            "| Hypothesis | Primary | Secondary | Unrelated |",
            "|---|---|---|---|",
        ]
        for h in HYPOTHESES:
            c = by_tag[h]
            lines.append(f"| {h} | {c['primary']} | {c['secondary']} | {c['unrelated']} |")
        lines.append(_INDEX_END)
        block = "\n".join(lines)

        raw = self._hub.read_dataset_bytes(self._repo, "README.md", revision="main")
        readme = raw.decode("utf-8") if raw else ""
        if _INDEX_START in readme and _INDEX_END in readme:
            new = re.sub(
                re.escape(_INDEX_START) + r".*?" + re.escape(_INDEX_END),
                block, readme, count=1, flags=re.S,
            )
        else:
            new = (readme.rstrip() + "\n\n" + block + "\n") if readme else block + "\n"
        if new != readme:
            self._hub.upload_dataset_file(
                self._repo, "README.md", new.encode("utf-8"),
                "merge-bot: regenerate final-set index",
            )

    def _trace_missing_reason(self, agent: str, description: str) -> str | None:
        """None if the trace requirement is satisfied (or disabled), else a
        human-readable reason the merge is held."""
        s = self._settings
        if not s.merge_require_trace:
            return None
        session = parse_session_header(description)
        if not session:
            return ("the PR description must declare `session: <id>` naming your working "
                    "session, and that session's trace must be shared.")
        rec = self._rm.record(TRACES_FOLDER, f"{agent}/{session}/manifest.md")
        if rec is None:
            return (f"no shared trace found for session `{session}`. Share it first with "
                    f"`python share_trace.py --full --yes`, then reference that session id.")
        if s.merge_require_full_trace and rec.frontmatter.get("share") != "full":
            return (f"session `{session}` has only a stats trace; a **full** trace is required "
                    f"(`python share_trace.py --full --yes`).")
        return None

    def _note_missing_trace(self, pr, thread, reason: str) -> None:
        if any(_TRACE_MARKER in c.text for c in thread.comments):
            return
        self._hub.comment_pr(
            self._repo, pr.num,
            f"{_TRACE_MARKER}\nThis PR is approved but I can't merge it yet: {reason}",
        )
        log.info("PR #%s held: trace requirement (%s)", pr.num, reason)

    def _note_invalid(self, pr, thread, path: str, errs: list[str]) -> None:
        if any(_INVALID_MARKER in c.text for c in thread.comments):
            return
        bullets = "\n".join(f"- {e}" for e in errs)
        self._hub.comment_pr(
            self._repo, pr.num,
            f"{_INVALID_MARKER}\nThis PR is approved but `{path}` is not a valid entry, "
            f"so I can't merge it:\n{bullets}\n\nFix the file and re-push; I'll merge on the next pass.",
        )
        log.info("PR #%s held: invalid entry %s (%s)", pr.num, path, errs)

    def _close_on_veto(self, pr, thread, tally) -> None:
        """A veto is a decision, not silence — leaving the PR open just lets it
        rot in the queue. Close it, but leave `VETO_MARKER` on the closing
        comment so the read API can still report it as vetoed rather than an
        indistinguishable closed PR."""
        if any(VETO_MARKER in c.text for c in thread.comments):
            return
        # Close before commenting: if the close fails, no marker is left
        # behind, so the next poll pass retries instead of thinking it's done.
        if not self._hub.close_pr(self._repo, pr.num):
            log.warning("PR #%s: veto-close failed, will retry next pass", pr.num)
            return
        vetoers = ", ".join(self._as_agents(tally.request_changes_by)) or "a reviewer"
        self._hub.comment_pr(
            self._repo, pr.num,
            f"{VETO_MARKER}\nClosing: {vetoers} requested changes and none have been "
            f"resolved with a newer /approve or /comment. Address the feedback and open a "
            f"fresh PR if this still belongs in the final set.",
        )
        log.info("PR #%s closed: vetoed by %s", pr.num, vetoers)

    def _note_closed(self, pr, thread) -> None:
        if any(_CLOSED_MARKER in c.text for c in thread.comments):
            return
        ended = self._settings.challenge_ended_at or "now"
        self._hub.comment_pr(
            self._repo, pr.num,
            f"{_CLOSED_MARKER}\nThe challenge closed on {ended}. This PR will not be "
            f"merged, even if approved.",
        )
        log.info("PR #%s ignored: challenge closed (ended %s)", pr.num, ended)

    def _note_conflict(self, pr, thread, conflicts: list[str]) -> None:
        if any(_CONFLICT_MARKER in c.text for c in thread.comments):
            return
        files = ", ".join(f"`{f}`" for f in conflicts) or "one or more files"
        self._hub.comment_pr(
            self._repo, pr.num,
            f"{_CONFLICT_MARKER}\nThis PR is approved but conflicts with `main` on {files}. "
            f"Rebase your branch onto current `main` and re-push, and I'll merge it.",
        )
        log.info("PR #%s: posted conflict nudge (%s)", pr.num, conflicts)

    def _dataset_url(self) -> str:
        return f"https://huggingface.co/datasets/{self._repo}"
