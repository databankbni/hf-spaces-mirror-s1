from __future__ import annotations

import os
import re
from pathlib import Path


class MOKInternetBoundaryViolation(ValueError):
    pass


class MOKInternetDeploymentBoundary:
    """
    Public deployment safety boundary for MOK.

    This boundary validates external names, request size, filesystem
    placement and public error containment. It has no production,
    creative, recovery, policy or learning authority.
    """

    SCHEMA = "MOK_INTERNET_DEPLOYMENT_BOUNDARY_V1"
    VERSION = "MOK-H9.5"

    DEFAULT_MAX_REQUEST_BYTES = 256 * 1024 * 1024

    SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,199}$")

    def __init__(self, project_root):
        self.project_root = Path(project_root).resolve()

        state_value = os.getenv(
            "MOK_PERSISTENT_STATE_ROOT",
            str(self.project_root / "runtime_data"),
        )

        work_value = os.getenv(
            "MOK_TRANSIENT_WORK_ROOT",
            str(self.project_root / "output" / "internet_work"),
        )

        self.persistent_state_root = Path(state_value).resolve()
        self.transient_work_root = Path(work_value).resolve()

        self.max_request_bytes = int(
            os.getenv(
                "MOK_MAX_REQUEST_BYTES",
                str(self.DEFAULT_MAX_REQUEST_BYTES),
            )
        )

        if self.max_request_bytes <= 0:
            raise MOKInternetBoundaryViolation(
                "MOK_MAX_REQUEST_BYTES must be positive."
            )

    @staticmethod
    def _under(path, root):
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    def validate_external_name(self, value):
        if not isinstance(value, str):
            raise MOKInternetBoundaryViolation("Filename must be text.")

        if not value or value in {".", ".."}:
            raise MOKInternetBoundaryViolation("Unsafe external filename.")

        if "/" in value or "\\\\" in value:
            raise MOKInternetBoundaryViolation("Path separators are forbidden.")

        if "\x00" in value:
            raise MOKInternetBoundaryViolation("NUL byte is forbidden.")

        if ".." in value:
            raise MOKInternetBoundaryViolation("Traversal syntax is forbidden.")

        if not self.SAFE_NAME.fullmatch(value):
            raise MOKInternetBoundaryViolation("Filename is outside allowed syntax.")

        return value

    def validate_request_size(self, declared_bytes):
        if isinstance(declared_bytes, bool):
            raise MOKInternetBoundaryViolation("Invalid request size.")

        try:
            value = int(declared_bytes)
        except (TypeError, ValueError) as exc:
            raise MOKInternetBoundaryViolation("Invalid request size.") from exc

        if value < 0:
            raise MOKInternetBoundaryViolation("Negative request size.")

        if value > self.max_request_bytes:
            raise MOKInternetBoundaryViolation("Request exceeds MOK size boundary.")

        return value

    def transient_path(self, filename):
        safe = self.validate_external_name(filename)
        resolved = (self.transient_work_root / safe).resolve()

        if not self._under(resolved, self.transient_work_root):
            raise MOKInternetBoundaryViolation("Transient path escaped root.")

        return resolved

    def persistent_path(self, filename):
        safe = self.validate_external_name(filename)
        resolved = (self.persistent_state_root / safe).resolve()

        if not self._under(resolved, self.persistent_state_root):
            raise MOKInternetBoundaryViolation("Persistent path escaped root.")

        return resolved

    @staticmethod
    def public_error(code="MOK_REQUEST_FAILED"):
        return {
            "ok": False,
            "error": str(code),
        }

    def contract(self):
        return {
            "schema": self.SCHEMA,
            "version": self.VERSION,
            "target": "HUGGING_FACE_DOCKER_SPACE",
            "app_port": 7860,
            "persistent_state_root": str(self.persistent_state_root),
            "transient_work_root": str(self.transient_work_root),
            "max_request_bytes": self.max_request_bytes,
            "persistent_state_externalizable": True,
            "production_authority": False,
            "decision_authority": False,
            "recovery_authority": False,
            "learning_mutation_authority": False,
            "policy_mutation_authority": False,
        }


# ================================================================
# MOK_H10_8C_H_H_B_R7_NATIVE_WEB_KNOWLEDGE
# ================================================================
class _MOKWebResultParser:
    """Minimal bounded parser for no-JavaScript search results."""

    def __init__(self):
        from html.parser import HTMLParser

        class _Parser(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=True)
                self.results = []
                self._capture_title = False
                self._capture_snippet = False
                self._title_parts = []
                self._snippet_parts = []
                self._href = ""

            @staticmethod
            def _classes(attrs):
                values = dict(attrs)
                return str(values.get("class", "")).split()

            def handle_starttag(self, tag, attrs):
                values = dict(attrs)
                classes = self._classes(attrs)

                if tag == "a" and "result__a" in classes:
                    self._capture_title = True
                    self._title_parts = []
                    self._href = str(values.get("href", "") or "")
                    return

                if "result__snippet" in classes:
                    self._capture_snippet = True
                    self._snippet_parts = []

            def handle_data(self, data):
                if self._capture_title:
                    self._title_parts.append(str(data))

                if self._capture_snippet:
                    self._snippet_parts.append(str(data))

            def handle_endtag(self, tag):
                if tag == "a" and self._capture_title:
                    title = " ".join(
                        " ".join(self._title_parts).split()
                    )

                    if title and self._href:
                        self.results.append({
                            "title": title,
                            "url": self._href,
                            "snippet": "",
                        })

                    self._capture_title = False
                    self._title_parts = []
                    self._href = ""

                if self._capture_snippet and tag in {
                    "a",
                    "div",
                    "span",
                    "td",
                    "p",
                }:
                    snippet = " ".join(
                        " ".join(self._snippet_parts).split()
                    )

                    if snippet and self.results:
                        if not self.results[-1]["snippet"]:
                            self.results[-1]["snippet"] = snippet

                    self._capture_snippet = False
                    self._snippet_parts = []

        self._parser = _Parser()

    def feed(self, text):
        self._parser.feed(str(text or ""))
        return list(self._parser.results)


class MOKNativeWebKnowledgeAuthority:
    """
    MOK-owned scoped web knowledge authority.

    Web evidence is supplementary knowledge only.
    It never authorizes production, execution, readiness,
    verification, or artifact success.
    """

    SCHEMA = "MOK_NATIVE_WEB_KNOWLEDGE_V1"
    SEARCH_ENDPOINT = "https://html.duckduckgo.com/html/"

    def __init__(
        self,
        timeout_seconds=1.5,
        max_results=4,
        cache_seconds=300.0,
    ):
        self.timeout_seconds = max(
            0.5,
            min(float(timeout_seconds), 4.0),
        )

        self.max_results = max(
            1,
            min(int(max_results), 6),
        )

        self.cache_seconds = max(
            30.0,
            min(float(cache_seconds), 3600.0),
        )

        self._cache = {}

    @staticmethod
    def _normalize(value):
        import re

        text = str(value or "").strip().lower()
        text = re.sub(r"[^a-z0-9\s\-]", " ", text)
        return " ".join(text.split())

    def should_supplement(self, question):
        normalized = self._normalize(question)

        if not normalized:
            return False

        creative_signals = (
            "animation",
            "animate",
            "movement",
            "motion",
            "transition",
            "video",
            "videos",
            "photo",
            "photos",
            "picture",
            "pictures",
            "logo",
            "cinematic",
            "film",
            "brand",
            "advertising",
            "commercial",
            "trailer",
            "editing",
            "edit",
            "effect",
            "effects",
            "typography",
            "presentation",
            "storyboard",
            "color grade",
            "visual style",
            "creative style",
            "youtube",
            "instagram",
            "tiktok",
            "social media",
            "aspect ratio",
            "frame rate",
            "resolution",
            "production technique",
        )

        research_signals = (
            "latest",
            "current",
            "new",
            "trend",
            "trending",
            "popular",
            "modern",
            "examples",
            "example",
            "ideas",
            "inspiration",
            "recommend",
            "recommendation",
            "best",
            "search",
            "web",
            "internet",
            "online",
            "find",
            "technique",
            "techniques",
            "style",
            "styles",
            "animation",
            "movement",
            "transition",
            "effect",
            "effects",
            "spec",
            "specification",
            "format",
            "guideline",
            "guidelines",
        )

        has_creative_scope = any(
            signal in normalized
            for signal in creative_signals
        )

        needs_external_knowledge = any(
            signal in normalized
            for signal in research_signals
        )

        return bool(
            has_creative_scope
            and needs_external_knowledge
        )

    @staticmethod
    def _search_query(question):
        normalized = " ".join(
            str(question or "").strip().split()
        )

        return (
            normalized
            + " creative production animation video technique examples"
        )[:500]

    @staticmethod
    def _unwrap_url(value):
        from urllib.parse import parse_qs
        from urllib.parse import unquote
        from urllib.parse import urlparse

        url = str(value or "").strip()

        if not url:
            return ""

        if url.startswith("//"):
            url = "https:" + url

        parsed = urlparse(url)

        if "duckduckgo.com" in parsed.netloc:
            query = parse_qs(parsed.query)
            target = query.get("uddg")

            if target:
                url = unquote(str(target[0]))

        return url

    @staticmethod
    def _safe_external_url(value):
        from urllib.parse import urlparse

        url = str(value or "").strip()

        if not url:
            return ""

        parsed = urlparse(url)

        if parsed.scheme not in {"http", "https"}:
            return ""

        host = str(parsed.hostname or "").strip().lower()

        if not host:
            return ""

        blocked_hosts = {
            "localhost",
            "127.0.0.1",
            "0.0.0.0",
            "::1",
        }

        if host in blocked_hosts:
            return ""

        if host.endswith(".local"):
            return ""

        return url

    def _cache_get(self, key):
        import time

        entry = self._cache.get(key)

        if not isinstance(entry, dict):
            return None

        created = float(entry.get("created", 0.0))

        if (time.monotonic() - created) > self.cache_seconds:
            self._cache.pop(key, None)
            return None

        results = entry.get("results")

        if not isinstance(results, list):
            return None

        return [dict(item) for item in results]

    def _cache_put(self, key, results):
        import time

        self._cache[key] = {
            "created": time.monotonic(),
            "results": [dict(item) for item in results],
        }

        if len(self._cache) > 32:
            oldest_key = min(
                self._cache,
                key=lambda item: self._cache[item]["created"],
            )
            self._cache.pop(oldest_key, None)

    def search(self, question):
        from urllib.parse import urlencode
        from urllib.request import Request
        from urllib.request import urlopen

        query = self._search_query(question)
        cache_key = self._normalize(query)

        cached = self._cache_get(cache_key)

        if cached is not None:
            return cached

        payload = urlencode({
            "q": query,
            "kl": "us-en",
        }).encode("utf-8")

        request = Request(
            self.SEARCH_ENDPOINT,
            data=payload,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(compatible; MOKAutonomousAIStudio/1.0)"
                ),
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.8",
            },
            method="POST",
        )

        try:
            with urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                body = response.read(750000)
        except Exception:
            return []

        try:
            html_text = body.decode("utf-8", errors="replace")
        except Exception:
            return []

        lowered = html_text.lower()

        if (
            "anomaly-modal" in lowered
            or "unusual traffic" in lowered
        ):
            return []

        parser = _MOKWebResultParser()
        parsed = parser.feed(html_text)

        results = []
        seen = set()

        for raw in parsed:
            title = " ".join(
                str(raw.get("title", "") or "").split()
            )

            snippet = " ".join(
                str(raw.get("snippet", "") or "").split()
            )

            url = self._unwrap_url(
                raw.get("url", "")
            )

            url = self._safe_external_url(url)

            if not title or not url:
                continue

            identity = (title.lower(), url)

            if identity in seen:
                continue

            seen.add(identity)

            results.append({
                "title": title[:220],
                "snippet": snippet[:500],
                "url": url[:1000],
            })

            if len(results) >= self.max_results:
                break

        self._cache_put(cache_key, results)
        return results

    @staticmethod
    def _domain(value):
        from urllib.parse import urlparse

        try:
            return str(
                urlparse(str(value)).hostname or ""
            ).lower()
        except Exception:
            return ""

    def supplement(self, question):
        if not self.should_supplement(question):
            return None

        results = self.search(question)

        if not results:
            return None

        lines = [
            "I found some current web references that may help with your creative decision:",
        ]

        for index, result in enumerate(results[:4], start=1):
            title = result.get("title", "")
            snippet = result.get("snippet", "")
            url = result.get("url", "")
            domain = self._domain(url)

            detail = title

            if snippet:
                detail += ": " + snippet

            if domain:
                detail += " [" + domain + "]"

            lines.append(
                str(index) + ". " + detail
            )

        lines.append(
            "MOK can use these references as creative evidence, combine them with your materials and preferences, and decide which approach best fits your project."
        )

        return "\n".join(lines)

    def contract(self):
        return {
            "schema": self.SCHEMA,
            "authority": "MOK_NATIVE_WEB_KNOWLEDGE",
            "scope": "CREATIVE_PRODUCTION_SUPPLEMENTATION_ONLY",
            "autonomous_search_decision": True,
            "production_authority": False,
            "execution_authority": False,
            "verification_authority": False,
            "search_endpoint": self.SEARCH_ENDPOINT,
            "max_results": self.max_results,
            "timeout_seconds": self.timeout_seconds,
            "cache_seconds": self.cache_seconds,
        }
