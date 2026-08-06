from __future__ import annotations

from pathlib import Path
import json
from typing import Any, Dict, List, Optional, Sequence, Union

from ..packet import InfoPacket
from ..plugin import Plugin
from ..skills import SkillSpec, load_skills_from_roots, normalize_skill_roots, select_relevant_skills

ACTIVE_SKILL_NAMES_METADATA_KEY = "agentflow_active_skill_names"


class SkillPlugin(Plugin):
    def __init__(
        self,
        skill_roots: Optional[Sequence[Union[str, Path]]] = None,
        skill_names: Optional[Sequence[str]] = None,
        auto_select: bool = True,
        max_skills: int = 3,
        max_skill_chars: int = 12000,
        name: Optional[str] = None,
    ):
        super().__init__(name)
        self.skill_roots = [str(path) for path in normalize_skill_roots(skill_roots)]
        self.skill_names = [str(item).strip() for item in (skill_names or []) if str(item).strip()]
        self.auto_select = auto_select
        self.max_skills = max_skills
        self.max_skill_chars = max_skill_chars
        self._catalog_cache: Optional[Dict[str, SkillSpec]] = None
        self._alias_cache: Optional[Dict[str, str]] = None

    def clone(self) -> "SkillPlugin":
        cloned = SkillPlugin(
            skill_roots=self.skill_roots,
            skill_names=self.skill_names,
            auto_select=self.auto_select,
            max_skills=self.max_skills,
            max_skill_chars=self.max_skill_chars,
            name=self.name,
        )
        return cloned

    def refresh_catalog(self) -> None:
        self._catalog_cache = None
        self._alias_cache = None

    def pre_process(self, packet: InfoPacket) -> InfoPacket:
        if packet.has_metadata(ACTIVE_SKILL_NAMES_METADATA_KEY):
            return packet

        active_names = self._resolve_active_skill_names(packet)
        if active_names:
            packet.add_metadata(ACTIVE_SKILL_NAMES_METADATA_KEY, active_names)
        return packet

    def build_system_message(self, packet: InfoPacket) -> str:
        active_names = packet.get_metadata(ACTIVE_SKILL_NAMES_METADATA_KEY)
        if not isinstance(active_names, list) or not active_names:
            active_names = self._resolve_active_skill_names(packet)

        if not active_names:
            return ""

        sections: List[str] = []
        total_chars = 0
        for skill_name in active_names:
            skill = self._lookup_skill(str(skill_name))
            if skill is None:
                continue

            section = skill.raw_text.strip()
            if not section:
                continue

            projected_length = total_chars + len(section)
            if self.max_skill_chars > 0 and projected_length > self.max_skill_chars:
                remaining = self.max_skill_chars - total_chars
                if remaining <= 0:
                    break
                section = section[:remaining].rstrip()
                sections.append(section)
                break

            sections.append(section)
            total_chars += len(section)

        if not sections:
            return ""

        return (
            "[Prompt Context]\n"
            "The following local prompt files are active for this turn. "
            "Treat them as task-specific operating instructions in addition to the base role.\n\n"
            + "\n\n".join(sections)
        ).strip()

    def _get_catalog(self) -> Dict[str, SkillSpec]:
        if self._catalog_cache is None:
            loaded = load_skills_from_roots(self.skill_roots)
            self._catalog_cache = {skill.name.lower(): skill for skill in loaded}
            aliases: Dict[str, str] = {}
            for skill in loaded:
                aliases[skill.name.lower()] = skill.name.lower()
                aliases[Path(skill.path).parent.name.lower()] = skill.name.lower()
            self._alias_cache = aliases
        return self._catalog_cache

    def _lookup_skill(self, requested_name: str) -> Optional[SkillSpec]:
        catalog = self._get_catalog()
        alias_cache = self._alias_cache or {}
        canonical_name = alias_cache.get(requested_name.lower())
        if canonical_name is None:
            return None
        return catalog.get(canonical_name)

    def _resolve_active_skill_names(self, packet: InfoPacket) -> List[str]:
        names: List[str] = []
        seen: set[str] = set()
        catalog = self._get_catalog()

        for configured_name in self.skill_names:
            skill = self._lookup_skill(configured_name)
            if skill is None:
                continue
            lowered = skill.name.lower()
            if lowered not in seen:
                names.append(skill.name)
                seen.add(lowered)

        if self.auto_select:
            query_text = self._build_relevance_text(packet)
            for skill in select_relevant_skills(query_text, catalog.values(), limit=self.max_skills):
                lowered = skill.name.lower()
                if lowered in seen:
                    continue
                names.append(skill.name)
                seen.add(lowered)
                if self.max_skills > 0 and len(names) >= self.max_skills:
                    break

        if self.max_skills > 0:
            return names[: self.max_skills]
        return names

    def _build_relevance_text(self, packet: InfoPacket) -> str:
        parts = [self._stringify(packet.content)]
        processor = self._processor
        if processor is not None and hasattr(processor, "_get_chain_packets_for_messages"):
            try:
                chain_packets = processor._get_chain_packets_for_messages(packet)
            except Exception:
                chain_packets = []
            sender_id = getattr(processor, "sender_id", None)
            for current in reversed(chain_packets):
                if current.id == packet.id:
                    continue
                if sender_id and current.sender_id == sender_id:
                    continue
                if current.type.value in {"stream", "response", "error"}:
                    continue
                rendered = self._stringify(current.content)
                if rendered:
                    parts.append(rendered)
                if len(parts) >= 3:
                    break
        return "\n".join(part for part in parts if part).strip()

    def _stringify(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        if isinstance(value, str):
            return value
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        return str(value)


class PromptPlugin(SkillPlugin):
    pass
