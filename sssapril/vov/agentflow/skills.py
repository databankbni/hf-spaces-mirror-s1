from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

import yaml


_FRONTMATTER_RE = re.compile(r"\A---\s*\r?\n(.*?)\r?\n---\s*(?:\r?\n|$)", re.DOTALL)
_ASCII_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_./-]{1,}")
_PHRASE_SPLIT_RE = re.compile(r"[\s,.;:!?()\[\]{}，。；：！？（）【】]+")
_COMMON_MATCH_TERMS = {
    "skill",
    "skills",
    "agent",
    "agents",
    "codex",
    "local",
    "using",
    "use",
    "when",
    "that",
    "this",
    "with",
    "from",
    "into",
    "they",
    "them",
    "your",
    "help",
    "supports",
    "support",
    "asks",
    "user",
    "users",
}


@dataclass
class SkillSpec:
    name: str
    description: str
    path: str
    body: str
    raw_text: str
    frontmatter: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    hooks: Dict[str, Any] = field(default_factory=dict)
    allowed_tools: List[str] = field(default_factory=list)
    user_invocable: Optional[bool] = None
    source_root: Optional[str] = None

    def to_dict(self, include_body: bool = False) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "path": self.path,
            "allowed_tools": list(self.allowed_tools),
            "user_invocable": self.user_invocable,
            "metadata": dict(self.metadata),
            "hooks": dict(self.hooks),
            "frontmatter": dict(self.frontmatter),
            "source_root": self.source_root,
        }
        if include_body:
            payload["body"] = self.body
        return payload

    def to_summary_dict(self) -> Dict[str, Any]:
        return self.to_dict(include_body=False)


@dataclass
class SkillResourceSpec:
    skill: SkillSpec
    path: str
    relative_path: str
    available_files: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill": self.skill.to_summary_dict(),
            "path": self.path,
            "relative_path": self.relative_path,
            "available_files": list(self.available_files),
        }


def default_skill_roots() -> List[Path]:
    home = Path.home()
    roots = [
        home / ".agents" / "skills",
        home / ".codex" / "skills",
        home / ".codex" / "plugins" / "cache",
    ]
    return [root for root in roots if root.exists()]


def normalize_skill_roots(skill_roots: Optional[Sequence[Union[str, Path]]]) -> List[Path]:
    roots = skill_roots or default_skill_roots()
    return [Path(root).expanduser().resolve() for root in roots]


def iter_skill_files(skill_roots: Sequence[Union[str, Path]]) -> List[Path]:
    files: List[Path] = []
    for root in normalize_skill_roots(skill_roots):
        if not root.exists():
            continue
        files.extend(root.rglob("SKILL.md"))
    files.sort()
    return files


def _normalize_allowed_tools(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[,|\n]+", value) if item.strip()]
    return []


def _parse_frontmatter(text: str) -> tuple[Dict[str, Any], str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text.strip()

    frontmatter_text = match.group(1)
    body = text[match.end() :].lstrip()
    try:
        parsed = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError:
        return {}, text.strip()
    if not isinstance(parsed, dict):
        parsed = {}
    return parsed, body.strip()


def parse_skill_text(
    text: str,
    *,
    path: Union[str, Path],
    source_root: Optional[Union[str, Path]] = None,
) -> SkillSpec:
    resolved_path = Path(path).expanduser().resolve()
    frontmatter, body = _parse_frontmatter(text)

    fallback_name = resolved_path.parent.name
    name = str(frontmatter.get("name") or fallback_name).strip() or fallback_name
    description = str(frontmatter.get("description") or "").strip()
    if not description:
        for line in body.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                description = stripped
                break

    metadata = frontmatter.get("metadata")
    hooks = frontmatter.get("hooks")

    return SkillSpec(
        name=name,
        description=description,
        path=str(resolved_path),
        body=body,
        raw_text=text.strip(),
        frontmatter=dict(frontmatter),
        metadata=dict(metadata) if isinstance(metadata, dict) else {},
        hooks=dict(hooks) if isinstance(hooks, dict) else {},
        allowed_tools=_normalize_allowed_tools(frontmatter.get("allowed-tools") or frontmatter.get("allowed_tools")),
        user_invocable=frontmatter.get("user-invocable")
        if isinstance(frontmatter.get("user-invocable"), bool)
        else frontmatter.get("user_invocable")
        if isinstance(frontmatter.get("user_invocable"), bool)
        else None,
        source_root=str(Path(source_root).expanduser().resolve()) if source_root else None,
    )


def parse_skill_file(skill_file: Union[str, Path], source_root: Optional[Union[str, Path]] = None) -> SkillSpec:
    resolved = Path(skill_file).expanduser().resolve()
    return parse_skill_text(
        resolved.read_text(encoding="utf-8"),
        path=resolved,
        source_root=source_root,
    )


def resolve_skill_file(requested: str, skill_roots: Optional[Sequence[Union[str, Path]]] = None) -> Path:
    candidate = Path(requested).expanduser()
    if candidate.exists():
        if candidate.is_dir():
            candidate = candidate / "SKILL.md"
        return candidate.resolve()

    normalized_request = requested.strip().lower()
    for skill_file in iter_skill_files(skill_roots or default_skill_roots()):
        parsed = parse_skill_file(skill_file)
        if parsed.name.lower() == normalized_request or skill_file.parent.name.lower() == normalized_request:
            return skill_file.resolve()

    raise FileNotFoundError(f"Skill '{requested}' was not found.")


def load_skill(requested: str, skill_roots: Optional[Sequence[Union[str, Path]]] = None) -> SkillSpec:
    roots = normalize_skill_roots(skill_roots)
    skill_file = resolve_skill_file(requested, roots)
    source_root = next((root for root in roots if root == skill_file.parent or root in skill_file.parents), None)
    return parse_skill_file(skill_file, source_root=source_root)


def load_skills_from_roots(skill_roots: Optional[Sequence[Union[str, Path]]] = None) -> List[SkillSpec]:
    roots = normalize_skill_roots(skill_roots)
    items: List[SkillSpec] = []
    for skill_file in iter_skill_files(roots):
        source_root = next((root for root in roots if root == skill_file.parent or root in skill_file.parents), None)
        items.append(parse_skill_file(skill_file, source_root=source_root))
    return items


def _skill_aliases(skill: SkillSpec) -> List[str]:
    aliases: List[str] = []
    seen: set[str] = set()
    candidates = [skill.name, Path(skill.path).parent.name]
    if skill.source_root:
        try:
            candidates.append(Path(skill.path).parent.relative_to(Path(skill.source_root)).as_posix())
        except ValueError:
            pass
    for item in candidates:
        normalized = str(item or "").strip().replace("\\", "/").strip("/")
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        aliases.append(normalized)
        seen.add(lowered)
    return aliases


def list_skill_files(skill: SkillSpec) -> List[str]:
    skill_dir = Path(skill.path).resolve().parent
    files = [path.name for path in skill_dir.iterdir() if path.is_file()]
    files.sort(key=lambda item: (item != "SKILL.md", item.lower()))
    return files


def _resolve_skill_from_existing_path(
    candidate: Path,
    roots: List[Path],
) -> SkillResourceSpec:
    resolved_candidate = candidate.resolve()
    if resolved_candidate.is_dir():
        resolved_candidate = resolved_candidate / "SKILL.md"
    if not resolved_candidate.exists() or not resolved_candidate.is_file():
        raise FileNotFoundError(f"Skill resource '{resolved_candidate}' was not found.")

    skill_file: Optional[Path] = None
    current = resolved_candidate if resolved_candidate.is_dir() else resolved_candidate.parent
    while True:
        possible = current / "SKILL.md"
        if possible.exists():
            skill_file = possible.resolve()
            break
        if current.parent == current:
            break
        current = current.parent

    if skill_file is None:
        raise FileNotFoundError(f"Skill root for '{resolved_candidate}' was not found.")

    source_root = next((root for root in roots if root == skill_file.parent or root in skill_file.parents), None)
    skill = parse_skill_file(skill_file, source_root=source_root)
    relative_path = resolved_candidate.relative_to(skill_file.parent).as_posix()
    if "/" in relative_path:
        raise ValueError("Only top-level skill files are supported right now.")
    return SkillResourceSpec(
        skill=skill,
        path=str(resolved_candidate),
        relative_path=relative_path,
        available_files=list_skill_files(skill),
    )


def resolve_skill_resource(
    requested: str,
    skill_roots: Optional[Sequence[Union[str, Path]]] = None,
) -> SkillResourceSpec:
    roots = normalize_skill_roots(skill_roots)
    candidate = Path(requested).expanduser()
    if candidate.exists():
        return _resolve_skill_from_existing_path(candidate, roots)

    normalized_request = str(requested or "").strip().replace("\\", "/").strip("/")
    if not normalized_request:
        raise ValueError("Skill request cannot be empty.")

    skills = load_skills_from_roots(roots)
    best_match: tuple[int, SkillSpec, str] | None = None
    lowered_request = normalized_request.lower()
    for skill in skills:
        for alias in _skill_aliases(skill):
            lowered_alias = alias.lower()
            if lowered_request == lowered_alias:
                suffix = ""
            elif lowered_request.startswith(f"{lowered_alias}/"):
                suffix = normalized_request[len(alias) + 1 :]
            else:
                continue
            if best_match is None or len(alias) > best_match[0]:
                best_match = (len(alias), skill, suffix)

    if best_match is None:
        raise FileNotFoundError(f"Skill resource '{requested}' was not found.")

    _, skill, suffix = best_match
    relative_path = suffix or "SKILL.md"
    if "/" in relative_path:
        raise ValueError("Only top-level skill files are supported right now.")

    resource_path = (Path(skill.path).resolve().parent / relative_path).resolve()
    skill_dir = Path(skill.path).resolve().parent
    if resource_path.parent != skill_dir:
        raise ValueError("Skill resource must stay within the top level of the skill directory.")
    if not resource_path.exists() or not resource_path.is_file():
        raise FileNotFoundError(f"Skill file '{relative_path}' was not found in '{skill.name}'.")

    return SkillResourceSpec(
        skill=skill,
        path=str(resource_path),
        relative_path=relative_path,
        available_files=list_skill_files(skill),
    )


def _normalize_match_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _extract_match_fragments(text: str) -> List[str]:
    normalized = _normalize_match_text(text)
    if not normalized:
        return []

    fragments: List[str] = []
    seen: set[str] = set()

    for token in _ASCII_TOKEN_RE.findall(normalized):
        if len(token) < 3 or token in _COMMON_MATCH_TERMS:
            continue
        if token not in seen:
            fragments.append(token)
            seen.add(token)

    for raw_fragment in _PHRASE_SPLIT_RE.split(normalized):
        fragment = raw_fragment.strip(" -_.")
        if len(fragment) < 2 or fragment in seen:
            continue
        if all(char.isascii() for char in fragment) and fragment in _COMMON_MATCH_TERMS:
            continue
        fragments.append(fragment)
        seen.add(fragment)

    return fragments


def score_skill_match(skill: SkillSpec, text: str) -> int:
    haystack = _normalize_match_text(text)
    if not haystack:
        return 0

    score = 0
    normalized_name = skill.name.strip().lower()
    folder_name = Path(skill.path).parent.name.strip().lower()

    if normalized_name and f"${normalized_name}" in haystack:
        return 1000
    if folder_name and folder_name != normalized_name and f"${folder_name}" in haystack:
        return 1000

    if normalized_name and normalized_name in haystack:
        score += 240
    if folder_name and folder_name != normalized_name and folder_name in haystack:
        score += 180

    fragments = _extract_match_fragments(skill.name) + _extract_match_fragments(skill.description)
    unique_fragments: List[str] = []
    seen: set[str] = set()
    for fragment in fragments:
        if fragment not in seen:
            unique_fragments.append(fragment)
            seen.add(fragment)

    fragment_hits = 0
    for fragment in unique_fragments:
        if fragment and fragment in haystack:
            fragment_hits += 1
            score += 50 if len(fragment) >= 4 else 25

    if score < 100 and fragment_hits < 2:
        return 0
    return score


def select_relevant_skills(
    text: str,
    skills: Iterable[SkillSpec],
    *,
    limit: int = 3,
) -> List[SkillSpec]:
    scored: List[tuple[int, SkillSpec]] = []
    for skill in skills:
        score = score_skill_match(skill, text)
        if score > 0:
            scored.append((score, skill))

    scored.sort(key=lambda item: (-item[0], item[1].name.lower()))
    return [skill for _, skill in scored[: max(limit, 0)]]


__all__ = [
    "SkillResourceSpec",
    "SkillSpec",
    "default_skill_roots",
    "iter_skill_files",
    "list_skill_files",
    "load_skill",
    "load_skills_from_roots",
    "normalize_skill_roots",
    "parse_skill_file",
    "parse_skill_text",
    "resolve_skill_resource",
    "resolve_skill_file",
    "score_skill_match",
    "select_relevant_skills",
]
