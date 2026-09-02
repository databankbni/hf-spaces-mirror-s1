"""Wrapper over huggingface_hub's bucket API."""
from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from huggingface_hub import (
    HfApi,
    batch_bucket_files,
    bucket_info,
    download_bucket_files,
    hf_hub_download,
    list_bucket_tree,
    whoami,
)
from huggingface_hub.constants import ENDPOINT
from huggingface_hub.errors import (
    EntryNotFoundError,
    HfHubHTTPError,
    RepositoryNotFoundError,
)
from huggingface_hub.utils import build_hf_headers, get_session

from app.config import Settings
from app.naming import SourceURI, parse_source_uri


log = logging.getLogger(__name__)


@dataclass
class ListedFile:
    rel_path: str
    size: int
    xet_hash: str | None = None


@dataclass(frozen=True)
class HubIdentity:
    username: str
    orgs: set[str]
    email: str | None = None


@dataclass(frozen=True)
class OrgMemberRole:
    user: str
    role: str


@dataclass
class PRComment:
    author: str        # HF username
    text: str
    created_at: str = ""


@dataclass
class PullRequest:
    num: int
    title: str
    author: str        # HF username of the PR author
    status: str        # "open" | "closed" | "merged" | "draft"
    created_at: str = ""


@dataclass
class PRThread:
    description: str           # the first comment (carries the `agent:` header)
    comments: list["PRComment"]  # all comments, in chronological order
    # Git-level merge state: non-empty means the PR conflicts with main and
    # CANNOT be merged until rebased, regardless of approvals.
    conflicting_files: list[str] = field(default_factory=list)


class HubClient:
    def __init__(self, settings: Settings):
        self._settings = settings

    @property
    def _token(self) -> str:
        return self._settings.resolved_token()

    # ───────────────────────── Bucket existence & identity ─────────────────────────

    def bucket_exists(self, bucket: str) -> bool:
        try:
            bucket_info(bucket, token=self._token)
            return True
        except (RepositoryNotFoundError, HfHubHTTPError) as e:
            log.debug("bucket_exists(%s) -> False (%s)", bucket, e)
            return False

    def bucket_author(self, bucket: str) -> str | None:
        """Return the `author` field from BucketInfo (the org name for org buckets).

        Not a true creator-of-record; for identity binding we rely on the
        whoami-at-registration flow plus a handshake file in the agent's bucket.
        """
        try:
            info = bucket_info(bucket, token=self._token)
        except (RepositoryNotFoundError, HfHubHTTPError) as e:
            log.debug("bucket_author(%s) failed: %s", bucket, e)
            return None
        return getattr(info, "author", None)

    def whoami_for_token(self, token: str) -> str:
        info = whoami(token=token)
        if isinstance(info, dict) and info.get("name"):
            return info["name"]
        raise ValueError("whoami did not return a `name` field")

    def whoami_identity(self, token: str) -> HubIdentity:
        """Resolve a caller token to HF identity facts used by human posts.

        OAuth tokens expose org membership but not roleInOrg. When the Space's
        OAuth app requests the email scope, the email lets the organizer gate
        perform a targeted org-member lookup instead of scanning the full org.
        """
        info = whoami(token=token)
        if not isinstance(info, dict) or not info.get("name"):
            raise ValueError("whoami did not return a `name` field")
        orgs = {
            o["name"]
            for o in (info.get("orgs") or [])
            if isinstance(o, dict) and o.get("name")
        }
        email = info.get("email")
        if not isinstance(email, str) or not email.strip():
            email = None
        return HubIdentity(info["name"], orgs, email.strip() if email else None)

    def whoami_user_and_orgs(self, token: str) -> tuple[str, set[str]]:
        """Resolve a caller token to (hf_user, org names). Used by existing
        identity gates that do not need optional email."""
        identity = self.whoami_identity(token)
        return identity.username, identity.orgs

    def org_member_role_by_email(self, org: str, email: str) -> OrgMemberRole | None:
        """Resolve one org member by email and return its role, if available.

        The members endpoint supports an email filter for orgs with a matching
        Organization email domain or SSO allowed domain. This is the scalable
        organizer check path: one request for the caller instead of listing
        every org member. Transport errors propagate so callers can fall back
        or fail closed.
        """
        session = get_session()
        headers = build_hf_headers(token=self._token)
        url = f"{ENDPOINT}/api/organizations/{org}/members"
        resp = session.get(
            url,
            headers=headers,
            params={"email": email, "limit": 1},
            timeout=10,
        )
        resp.raise_for_status()
        page = resp.json()
        if not isinstance(page, list) or not page:
            return None
        member = page[0]
        if not isinstance(member, dict):
            return None
        user, role = member.get("user"), member.get("role")
        if not isinstance(user, str) or not isinstance(role, str):
            return None
        return OrgMemberRole(user=user, role=role)

    def org_member_roles(self, org: str) -> dict[str, str]:
        """Map {lowercased username: org role} for every member of ``org``.

        whoami omits a caller's org role for OAuth tokens, so the organizer
        gate can't read it from the caller's own token; instead the Space
        looks the role up here with its admin token. Lists the members
        endpoint, following Link pagination and falling back to offset-style
        pagination if needed. Raises on transport error so the caller
        can fail closed rather than treat an outage as "not an organizer".
        """
        session = get_session()
        headers = build_hf_headers(token=self._token)
        url = f"{ENDPOINT}/api/organizations/{org}/members"
        page_size = 100
        roles: dict[str, str] = {}
        offset = 0
        params: dict[str, int] | None = {"limit": page_size, "offset": offset}
        while True:
            resp = session.get(
                url,
                headers=headers,
                params=params,
                timeout=10,
            )
            resp.raise_for_status()
            page = resp.json()
            if not isinstance(page, list) or not page:
                break
            before = len(roles)
            for m in page:
                if not isinstance(m, dict):
                    continue
                user, role = m.get("user"), m.get("role")
                if user and role:
                    roles[user.lower()] = role
            next_url = resp.links.get("next", {}).get("url")
            if next_url:
                url = next_url
                params = None
                continue
            if len(page) < page_size or len(roles) == before:
                break
            offset += page_size
            params = {"limit": page_size, "offset": offset}
        return roles

    # ───────────────────────── Reads ─────────────────────────

    def read_bytes(self, uri: SourceURI | str) -> bytes:
        parsed = uri if isinstance(uri, SourceURI) else parse_source_uri(uri)
        if parsed is None:
            raise ValueError(f"invalid source URI: {uri}")
        bucket = f"{parsed.org}/{parsed.bucket}"
        return self._download_one(bucket, parsed.path)

    def read_text(self, uri: SourceURI | str) -> str:
        return self.read_bytes(uri).decode("utf-8")

    def read_central_bytes(self, target_path: str) -> bytes:
        return self._download_one(self._settings.central_bucket, target_path)

    def read_central_text(self, target_path: str) -> str:
        return self.read_central_bytes(target_path).decode("utf-8")

    def read_central_bytes_optional(self, target_path: str) -> bytes | None:
        """Read a central-bucket file, distinguishing a genuinely missing file
        (returns None) from a transport/HTTP error (propagates).

        Unlike ``read_central_bytes`` — which flattens both cases to
        ``FileNotFoundError`` — this lets read-modify-write callers fail SAFE on
        a storage blip: skip the update rather than overwrite a live file with a
        fresh, near-empty one. Mirrors ``read_audit_bytes`` for the central bucket.
        """
        with tempfile.TemporaryDirectory() as td:
            local = Path(td) / "f"
            try:
                download_bucket_files(
                    bucket_id=self._settings.central_bucket,
                    files=[(target_path, str(local))],
                    raise_on_missing_files=True,
                    token=self._token,
                )
            except EntryNotFoundError:
                return None
            return local.read_bytes()

    def _download_one(self, bucket: str, remote_path: str) -> bytes:
        with tempfile.TemporaryDirectory() as td:
            local = Path(td) / "f"
            try:
                download_bucket_files(
                    bucket_id=bucket,
                    files=[(remote_path, str(local))],
                    raise_on_missing_files=True,
                    token=self._token,
                )
            except (EntryNotFoundError, HfHubHTTPError) as e:
                raise FileNotFoundError(f"{bucket}/{remote_path}: {e}")
            return local.read_bytes()

    def download_many(self, bucket: str, remote_paths: list[str]) -> dict[str, bytes]:
        """Batch-download files, returning {remote_path: bytes}.

        Missing or failed entries are simply absent from the result — callers
        (the read model, the backfill script) treat absence as transient and
        retry on a later pass. Chunked so a multi-thousand-file cold fill
        doesn't ride on a single oversized call.
        """
        out: dict[str, bytes] = {}
        chunk_size = 500
        for start in range(0, len(remote_paths), chunk_size):
            chunk = remote_paths[start : start + chunk_size]
            with tempfile.TemporaryDirectory() as td:
                pairs = [(remote, str(Path(td) / str(i))) for i, remote in enumerate(chunk)]
                try:
                    download_bucket_files(
                        bucket_id=bucket,
                        files=pairs,
                        raise_on_missing_files=False,
                        token=self._token,
                    )
                except (EntryNotFoundError, HfHubHTTPError) as e:
                    log.warning(
                        "download_many(%s, %d files) failed: %s", bucket, len(chunk), e
                    )
                    continue
                for remote, local in pairs:
                    p = Path(local)
                    if p.exists():
                        out[remote] = p.read_bytes()
        return out

    def list_central_dir(self, prefix: str) -> list[ListedFile]:
        return self._list(self._settings.central_bucket, prefix)

    def list_bucket_dir(self, bucket: str, prefix: str) -> list[ListedFile]:
        return self._list(bucket, prefix)

    def _list(self, bucket: str, prefix: str) -> list[ListedFile]:
        out: list[ListedFile] = []
        try:
            for entry in list_bucket_tree(
                bucket_id=bucket,
                prefix=prefix or None,
                recursive=True,
                token=self._token,
            ):
                if getattr(entry, "type", None) == "file":
                    out.append(
                        ListedFile(
                            rel_path=entry.path,
                            size=entry.size or 0,
                            xet_hash=getattr(entry, "xet_hash", None),
                        )
                    )
        except (RepositoryNotFoundError, HfHubHTTPError) as e:
            log.debug("list(%s, %s) failed: %s", bucket, prefix, e)
        return out

    # ───────────────────────── Writes (central bucket) ─────────────────────────

    def write_bytes_central(self, target_path: str, data: bytes) -> None:
        batch_bucket_files(
            bucket_id=self._settings.central_bucket,
            add=[(data, target_path)],
            token=self._token,
        )

    def write_text_central(self, target_path: str, text: str) -> None:
        self.write_bytes_central(target_path, text.encode("utf-8"))

    def write_many_central(self, items: list[tuple[bytes, str]]) -> None:
        """Write several central-bucket files in one batch call.

        Used to land a message and its inbox fan-out copies together (§16.4):
        one storage round trip, no window where board and inbox diverge.
        """
        if not items:
            return
        batch_bucket_files(
            bucket_id=self._settings.central_bucket,
            add=list(items),
            token=self._token,
        )

    def delete_central(self, target_path: str) -> None:
        """Delete one central-bucket file. The only deleting write in the
        system: channel unsubscribe removes the member marker
        (CHANNELS_DESIGN.md §3.3). Everything else stays append-only."""
        batch_bucket_files(
            bucket_id=self._settings.central_bucket,
            delete=[target_path],
            token=self._token,
        )

    def write_bytes_to_bucket(self, bucket: str, target_path: str, data: bytes) -> None:
        batch_bucket_files(bucket_id=bucket, add=[(data, target_path)], token=self._token)

    def write_text_to_bucket(self, bucket: str, target_path: str, text: str) -> None:
        self.write_bytes_to_bucket(bucket, target_path, text.encode("utf-8"))

    def append_jsonl_audit(self, target_path: str, line: str) -> None:
        """Append to the audit log in the private (out-of-org) audit bucket."""
        self._append_jsonl(self._settings.audit_bucket, target_path, line)

    def read_audit_bytes(self, target_path: str) -> bytes | None:
        """Read a file from the private audit bucket.

        Returns the bytes, or None if the file genuinely does not exist. Unlike
        read_central_bytes, transport/HTTP errors PROPAGATE rather than being
        flattened to "missing" — so callers (e.g. the job quota) can fail closed
        on a storage outage instead of treating it as an empty ledger.
        """
        with tempfile.TemporaryDirectory() as td:
            local = Path(td) / "f"
            try:
                download_bucket_files(
                    bucket_id=self._settings.audit_bucket,
                    files=[(target_path, str(local))],
                    raise_on_missing_files=True,
                    token=self._token,
                )
            except EntryNotFoundError:
                return None
            return local.read_bytes()

    def write_bytes_audit(self, target_path: str, data: bytes) -> None:
        batch_bucket_files(
            bucket_id=self._settings.audit_bucket,
            add=[(data, target_path)],
            token=self._token,
        )

    def _append_jsonl(self, bucket: str, target_path: str, line: str) -> None:
        try:
            existing = self._download_one(bucket, target_path)
        except FileNotFoundError:
            existing = b""
        if existing and not existing.endswith(b"\n"):
            existing += b"\n"
        batch_bucket_files(
            bucket_id=bucket,
            add=[(existing + line.encode("utf-8") + b"\n", target_path)],
            token=self._token,
        )

    # ───────────────────────── Cross-bucket copy ─────────────────────────

    def copy_file_to_central(self, src_bucket: str, src_xet_hash: str, dest_path: str) -> None:
        """Hash-copy a single source file into the central bucket (bytes never
        transit the Space). The caller passes the source's xet hash — taken from a
        listing it already holds — so there is no extra lookup here."""
        if not src_xet_hash:
            raise RuntimeError(f"missing xet_hash for copy to {dest_path}")
        batch_bucket_files(
            bucket_id=self._settings.central_bucket,
            copy=[("bucket", src_bucket, src_xet_hash, dest_path)],
            token=self._token,
        )

    def copy_tree_to_central(
        self, src_bucket: str, src_prefix: str, dest_prefix: str
    ) -> Iterable[tuple[str, str, int]]:
        files = self._list(src_bucket, src_prefix)
        if not files:
            return
        prefix = src_prefix.rstrip("/")
        copy_ops: list[tuple[str, str, str, str]] = []
        results: list[tuple[str, str, int]] = []
        for f in files:
            if not f.xet_hash:
                raise RuntimeError(f"missing xet_hash for source file: {f.rel_path}")
            rel = f.rel_path[len(prefix) + 1 :] if prefix and f.rel_path.startswith(prefix + "/") else f.rel_path
            dest_path = f"{dest_prefix.rstrip('/')}/{rel}"
            copy_ops.append(("bucket", src_bucket, f.xet_hash, dest_path))
            results.append((f.rel_path, dest_path, f.size))

        batch_bucket_files(
            bucket_id=self._settings.central_bucket,
            copy=copy_ops,
            token=self._token,
        )
        for r in results:
            yield r

    # ───────────────────────── Dataset Pull Requests (curation) ─────────────────────────
    #
    # The curated final set is a HF *dataset* repo; agents propose add/remove of
    # entry files through native Hub PRs and the merge-bot merges those that
    # clear the review bar with this admin token. All best-effort: a Hub hiccup
    # returns an empty/false result and the next poll retries.

    @property
    def _api(self) -> HfApi:
        return HfApi(token=self._token)

    @staticmethod
    def _username(author: object) -> str:
        """HF discussion/event author -> username string. The Hub returns either
        a bare username or an object/dict carrying it under name/user."""
        if isinstance(author, str):
            return author
        if isinstance(author, dict):
            return str(author.get("name") or author.get("user") or "")
        return str(getattr(author, "name", "") or getattr(author, "user", "") or "")

    def list_dataset_prs(self, repo_id: str, status: str = "open") -> list[PullRequest]:
        out: list[PullRequest] = []
        try:
            for d in self._api.get_repo_discussions(repo_id=repo_id, repo_type="dataset"):
                if not getattr(d, "is_pull_request", False):
                    continue
                if status and getattr(d, "status", None) != status:
                    continue
                out.append(
                    PullRequest(
                        num=int(d.num),
                        title=str(getattr(d, "title", "") or ""),
                        author=self._username(getattr(d, "author", "")),
                        status=str(getattr(d, "status", "") or ""),
                        created_at=str(getattr(d, "created_at", "") or ""),
                    )
                )
        except (RepositoryNotFoundError, HfHubHTTPError, ValueError) as e:
            log.warning("list_dataset_prs(%s) failed: %s", repo_id, e)
        return out

    def get_pr_thread(self, repo_id: str, num: int) -> PRThread:
        comments: list[PRComment] = []
        conflicting: list[str] = []
        try:
            details = self._api.get_discussion_details(
                repo_id=repo_id, discussion_num=num, repo_type="dataset"
            )
            for ev in getattr(details, "events", []) or []:
                if getattr(ev, "type", None) != "comment":
                    continue
                comments.append(
                    PRComment(
                        author=self._username(getattr(ev, "author", "")),
                        text=str(getattr(ev, "content", "") or getattr(ev, "raw", "") or ""),
                        created_at=str(getattr(ev, "created_at", "") or ""),
                    )
                )
            conflicting = list(getattr(details, "conflicting_files", None) or [])
        except (RepositoryNotFoundError, HfHubHTTPError, EntryNotFoundError, ValueError) as e:
            log.warning("get_pr_thread(%s, %s) failed: %s", repo_id, num, e)
        description = comments[0].text if comments else ""
        return PRThread(description=description, comments=comments, conflicting_files=conflicting)

    def list_dataset_tree(self, repo_id: str, revision: str = "main") -> dict[str, str]:
        """{path: blob id} for a dataset revision. Diffing two revisions' blob
        ids reveals adds, deletes, and modifications without downloading."""
        out: dict[str, str] = {}
        try:
            for entry in self._api.list_repo_tree(
                repo_id, repo_type="dataset", revision=revision, recursive=True,
            ):
                blob = getattr(entry, "blob_id", None)
                if blob:
                    out[entry.path] = str(blob)
        except (RepositoryNotFoundError, HfHubHTTPError, EntryNotFoundError, ValueError) as e:
            log.debug("list_dataset_tree(%s@%s) failed: %s", repo_id, revision, e)
        return out

    def read_dataset_bytes(self, repo_id: str, path: str, revision: str = "main") -> bytes | None:
        """Read one file from a dataset revision; None if missing/unreadable."""
        try:
            local = hf_hub_download(
                repo_id, path, repo_type="dataset", revision=revision, token=self._token,
            )
            return Path(local).read_bytes()
        except (RepositoryNotFoundError, HfHubHTTPError, EntryNotFoundError, ValueError) as e:
            log.debug("read_dataset_bytes(%s@%s:%s) failed: %s", repo_id, revision, path, e)
            return None

    def merge_pr(self, repo_id: str, num: int, comment: str | None = None) -> bool:
        try:
            self._api.merge_pull_request(
                repo_id=repo_id, discussion_num=num, comment=comment, repo_type="dataset",
            )
            return True
        except (RepositoryNotFoundError, HfHubHTTPError, ValueError) as e:
            log.warning("merge_pr(%s, %s) failed: %s", repo_id, num, e)
            return False

    def comment_pr(self, repo_id: str, num: int, comment: str) -> bool:
        try:
            self._api.comment_discussion(
                repo_id=repo_id, discussion_num=num, comment=comment, repo_type="dataset",
            )
            return True
        except (RepositoryNotFoundError, HfHubHTTPError, ValueError) as e:
            log.warning("comment_pr(%s, %s) failed: %s", repo_id, num, e)
            return False

    def close_pr(self, repo_id: str, num: int) -> bool:
        try:
            self._api.change_discussion_status(
                repo_id=repo_id, discussion_num=num, new_status="closed", repo_type="dataset",
            )
            return True
        except (RepositoryNotFoundError, HfHubHTTPError, ValueError) as e:
            log.warning("close_pr(%s, %s) failed: %s", repo_id, num, e)
            return False

    def upload_dataset_file(self, repo_id: str, path_in_repo: str, data: bytes, message: str) -> bool:
        """Commit one file to a dataset's main branch (the merge-bot's README
        index regen). Best-effort — a failure just leaves the index stale."""
        try:
            self._api.upload_file(
                path_or_fileobj=data, path_in_repo=path_in_repo, repo_id=repo_id,
                repo_type="dataset", commit_message=message,
            )
            return True
        except (RepositoryNotFoundError, HfHubHTTPError, ValueError) as e:
            log.warning("upload_dataset_file(%s:%s) failed: %s", repo_id, path_in_repo, e)
            return False
