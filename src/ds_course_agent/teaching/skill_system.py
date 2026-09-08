"""Single-file skill system for SKILL.md-based project skills.

This module keeps the current project simple:

- one `Skill` data model
- one `SkillRegistry`
- project/user discovery
- lightweight catalog for the system prompt
- executor-first execution with prompt fallback
"""

from __future__ import annotations

import hashlib
import importlib.util
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

from ds_course_agent.shared.paths import PROJECT_ROOT

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_PathSignature = tuple[bool, int, int, int, int, int, int]


@dataclass(frozen=True)
class _DiscoverySignature:
    """Bounded filesystem state used to validate the discovered catalog."""

    path_states: tuple[tuple[Path, _PathSignature], ...]
    manifest_digests: tuple[tuple[Path, str], ...]


def _normalize_skill_key(value: str) -> str:
    return re.sub(r"[-_\s]+", "-", (value or "").strip().lower())


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _coerce_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(value).strip()]


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1", "on"}:
            return True
        if lowered in {"false", "no", "0", "off"}:
            return False
    return bool(value)


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text

    raw = match.group(1)
    body = text[match.end() :]
    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        return {}, body
    return data, body


def _path_signature(path: Path) -> _PathSignature:
    """Return cheap filesystem metadata used to validate discovery state."""
    try:
        stat_result = path.stat()
    except OSError:
        return (False, 0, 0, 0, 0, 0, 0)
    return (
        True,
        stat_result.st_mode,
        stat_result.st_size,
        stat_result.st_mtime_ns,
        stat_result.st_ctime_ns,
        getattr(stat_result, "st_ino", 0),
        getattr(stat_result, "st_nlink", 0),
    )


def _file_digest(path: Path) -> str:
    """Return a compact digest for a known skill manifest."""
    try:
        return hashlib.blake2b(path.read_bytes(), digest_size=16).hexdigest()
    except OSError:
        return ""


@dataclass
class Skill:
    """A single discovered skill manifest plus optional prompt body."""

    name: str
    key: str = ""
    description: str = ""
    when_to_use: str = ""
    user_invocable: bool = True
    disable_model_invocation: bool = False
    allowed_tools: list[str] = field(default_factory=list)
    model: str | None = None
    context: str = "inline"
    argument_hint: str = ""
    paths: list[str] = field(default_factory=list)
    source: str = "project"
    skill_root: str | None = None
    skill_doc: str | None = None
    executor_path: str = "scripts/executor.py"
    trigger_keywords: list[str] = field(default_factory=list)
    avoid_keywords: list[str] = field(default_factory=list)
    priority: int = 0
    _prompt_text: str = ""
    _prompt_fn: Callable[[str], str] | None = None

    def __post_init__(self) -> None:
        self.key = _normalize_skill_key(self.key or self.name)

    def get_prompt(self, args: str = "") -> str:
        """Return the prompt body with simple variable substitution."""
        if self._prompt_fn is not None:
            return self._prompt_fn(args)

        text = self._prompt_text
        text = text.replace("$ARGUMENTS", args)
        if self.skill_root:
            text = text.replace("${CLAUDE_SKILL_DIR}", self.skill_root)
        if args and self.argument_hint:
            text = text.replace(f"${{{self.argument_hint}}}", args)
        return text

    @property
    def has_executor(self) -> bool:
        """Whether this skill has backend code support."""

        if not self.skill_root or not self.executor_path:
            return False
        return (Path(self.skill_root) / self.executor_path).exists()

    @property
    def skill_kind(self) -> str:
        """Human-readable skill category for prompt/context rendering."""

        return "backend" if self.has_executor else "cognitive"


@dataclass(frozen=True)
class SkillMatch:
    skill: Skill
    score: int
    matched_keywords: list[str]
    blocked_keywords: list[str]


def _skill_from_frontmatter(
    meta: dict[str, Any],
    body: str,
    name: str,
    source: str,
    skill_root: str | None = None,
    skill_doc: str | None = None,
) -> Skill:
    raw_priority = meta.get("priority", 0)
    try:
        priority = int(raw_priority)
    except Exception:
        priority = 0

    return Skill(
        name=str(meta.get("name") or name),
        description=str(meta.get("description") or ""),
        when_to_use=str(meta.get("when_to_use") or ""),
        user_invocable=_coerce_bool(meta.get("user_invocable"), default=True),
        disable_model_invocation=_coerce_bool(meta.get("disable_model_invocation"), default=False),
        allowed_tools=_coerce_list(meta.get("allowed_tools")),
        model=str(meta.get("model")) if meta.get("model") else None,
        context=str(meta.get("context") or "inline"),
        argument_hint=str(meta.get("arguments") or meta.get("argument_hint") or ""),
        paths=_coerce_list(meta.get("paths")),
        source=source,
        skill_root=skill_root,
        skill_doc=skill_doc,
        executor_path=str(meta.get("executor_path") or "scripts/executor.py"),
        trigger_keywords=_coerce_list(meta.get("trigger_keywords")),
        avoid_keywords=_coerce_list(meta.get("avoid_keywords")),
        priority=priority,
        _prompt_text=body.strip(),
    )


class SkillRegistry:
    """Discover, register, list, select, and execute skills."""

    def __init__(
        self,
        base_dir: Path | None = None,
        user_dir: Path | None = None,
    ) -> None:
        root = PROJECT_ROOT
        self.base_dir = Path(base_dir or (root / "src" / "ds_course_agent" / "teaching" / "skills"))
        self.project_cc_dir = root / ".cc-mini" / "skills"
        self.user_dir = Path(user_dir or (Path.home() / ".cc-mini" / "skills"))
        self._skills: dict[str, Skill] = {}
        self._module_cache: dict[tuple[str, str], ModuleType] = {}
        self._discovered_keys: set[str] = set()
        self._discovery_roots: tuple[Path, ...] = ()
        self._tracked_paths: tuple[Path, ...] = ()
        self._manifest_paths: tuple[Path, ...] = ()
        self._discovery_signature: _DiscoverySignature | None = None

    def register_skill(self, skill: Skill) -> None:
        """Register a skill, rejecting collisions after key normalization."""
        self._register_skill(self._skills, skill)

    def get_skill(self, name: str) -> Skill:
        self._ensure_discovered()
        key = _normalize_skill_key(name)
        if key not in self._skills:
            raise KeyError(f"Unknown skill: {name}")
        return self._skills[key]

    def list_skills(self, user_invocable_only: bool = False) -> list[Skill]:
        self._ensure_discovered()
        skills = list(self._skills.values())
        if user_invocable_only:
            skills = [skill for skill in skills if skill.user_invocable]
        return sorted(skills, key=lambda skill: (skill.source != "bundled", skill.name))

    def clear_skills(self, source: str | None = None) -> None:
        if source is None:
            self._skills.clear()
            self._module_cache.clear()
            self._discovered_keys.clear()
            self._discovery_roots = ()
            self._tracked_paths = ()
            self._manifest_paths = ()
            self._discovery_signature = None
            return

        keys = [key for key, skill in self._skills.items() if skill.source == source]
        for key in keys:
            self._skills.pop(key, None)

        stale_cache = [cache_key for cache_key in self._module_cache if cache_key[0] not in self._skills]
        for cache_key in stale_cache:
            self._module_cache.pop(cache_key, None)

        self._discovered_keys.difference_update(keys)
        self._discovery_roots = ()
        self._tracked_paths = ()
        self._manifest_paths = ()
        self._discovery_signature = None

    @staticmethod
    def _register_skill(registry: dict[str, Skill], skill: Skill) -> None:
        key = _normalize_skill_key(skill.key or skill.name)
        if not key or not key.strip("-"):
            raise ValueError(f"Skill '{skill.name}' has an empty normalized registration key")

        existing = registry.get(key)
        if existing is not None:
            existing_location = existing.skill_doc or existing.skill_root or f"source={existing.source}"
            new_location = skill.skill_doc or skill.skill_root or f"source={skill.source}"
            raise ValueError(
                f"Skill registration conflict for normalized key {key!r}: "
                f"{existing.name!r} ({existing_location}) conflicts with "
                f"{skill.name!r} ({new_location})"
            )
        skill.key = key
        registry[key] = skill

    @staticmethod
    def _resolve_discovery_roots(
        base_dir: Path,
        project_cc_dir: Path,
        user_dir: Path,
        cwd: str | None,
    ) -> tuple[Path, ...]:
        if cwd:
            cwd_path = Path(cwd)
            roots = (
                cwd_path / "src" / "ds_course_agent" / "teaching" / "skills",
                cwd_path / ".cc-mini" / "skills",
                user_dir,
            )
        else:
            roots = (base_dir, project_cc_dir, user_dir)
        return tuple(path.resolve() for path in roots)

    @staticmethod
    def _tracked_paths_for_skills(skills: list[Skill]) -> tuple[Path, ...]:
        paths: set[Path] = set()
        for skill in skills:
            if skill.skill_doc:
                paths.add(Path(skill.skill_doc).resolve())
            if skill.skill_root:
                skill_root = Path(skill.skill_root).resolve()
                paths.add(skill_root)
                if skill.executor_path:
                    paths.add((skill_root / skill.executor_path).resolve())
        return tuple(sorted(paths, key=str))

    @staticmethod
    def _manifest_paths_for_skills(skills: list[Skill]) -> tuple[Path, ...]:
        paths = {Path(skill.skill_doc).resolve() for skill in skills if skill.skill_doc}
        return tuple(sorted(paths, key=str))

    @staticmethod
    def _capture_discovery_signature(
        roots: tuple[Path, ...],
        tracked_paths: tuple[Path, ...],
        manifest_paths: tuple[Path, ...],
    ) -> _DiscoverySignature:
        paths = tuple(dict.fromkeys((*roots, *tracked_paths)))
        return _DiscoverySignature(
            path_states=tuple((path, _path_signature(path)) for path in paths),
            manifest_digests=tuple((path, _file_digest(path)) for path in manifest_paths),
        )

    def _discovery_cache_is_current(self, roots: tuple[Path, ...]) -> bool:
        if self._discovery_signature is None or roots != self._discovery_roots:
            return False
        return (
            self._capture_discovery_signature(roots, self._tracked_paths, self._manifest_paths)
            == self._discovery_signature
        )

    def _load_skills_from_dir(
        self,
        skills_dir: Path,
        source: str,
        registry: dict[str, Skill],
    ) -> tuple[list[Skill], set[Path], set[Path]]:
        loaded: list[Skill] = []
        scanned_paths: set[Path] = set()
        manifest_paths: set[Path] = set()
        if not skills_dir.is_dir():
            return loaded, scanned_paths, manifest_paths

        for entry in sorted(skills_dir.iterdir()):
            resolved_entry = entry.resolve()
            scanned_paths.add(resolved_entry)
            skill: Skill | None = None

            if entry.is_dir():
                skill_md = entry / "SKILL.md"
                manifest_paths.add(skill_md.resolve())
                if not skill_md.exists():
                    continue
                try:
                    text = skill_md.read_text(encoding="utf-8")
                except Exception:
                    continue
                meta, body = _parse_frontmatter(text)
                skill = _skill_from_frontmatter(
                    meta,
                    body,
                    name=entry.name,
                    source=source,
                    skill_root=str(entry),
                    skill_doc=str(skill_md),
                )
            elif entry.suffix == ".md" and entry.is_file():
                try:
                    text = entry.read_text(encoding="utf-8")
                except Exception:
                    continue
                meta, body = _parse_frontmatter(text)
                skill = _skill_from_frontmatter(
                    meta,
                    body,
                    name=entry.stem,
                    source=source,
                    skill_root=str(entry.parent),
                    skill_doc=str(entry),
                )

            if skill is None:
                continue

            self._register_skill(registry, skill)
            loaded.append(skill)

        return loaded, scanned_paths, manifest_paths

    def load_skills_from_dir(self, skills_dir: Path, source: str = "project") -> list[Skill]:
        staged_skills = dict(self._skills)
        loaded, _, _ = self._load_skills_from_dir(skills_dir, source, staged_skills)
        self._skills = staged_skills
        return loaded

    def discover_skills(self, cwd: str | None = None) -> list[Skill]:
        roots = self._resolve_discovery_roots(self.base_dir, self.project_cc_dir, self.user_dir, cwd)
        if self._discovery_cache_is_current(roots):
            return []

        staged_skills = {key: skill for key, skill in self._skills.items() if key not in self._discovered_keys}
        loaded: list[Skill] = []
        tracked_paths: set[Path] = set()
        manifest_paths: set[Path] = set()
        for skills_dir, source in zip(roots, ("project", "project", "user"), strict=True):
            discovered, scanned_paths, candidate_manifest_paths = self._load_skills_from_dir(
                skills_dir,
                source,
                staged_skills,
            )
            loaded.extend(discovered)
            tracked_paths.update(scanned_paths)
            tracked_paths.update(candidate_manifest_paths)
            manifest_paths.update(candidate_manifest_paths)

        self._skills = staged_skills
        self._discovered_keys = {skill.key for skill in loaded}
        self._discovery_roots = roots
        tracked_paths.update(self._tracked_paths_for_skills(loaded))
        manifest_paths.update(self._manifest_paths_for_skills(loaded))
        self._tracked_paths = tuple(sorted(tracked_paths, key=str))
        self._manifest_paths = tuple(sorted(manifest_paths, key=str))
        self._discovery_signature = self._capture_discovery_signature(
            roots,
            self._tracked_paths,
            self._manifest_paths,
        )
        self._module_cache.clear()
        return loaded

    def build_skills_summary(self) -> str:
        skills = self.list_skills(user_invocable_only=False)
        if not skills:
            return ""

        lines = ["## Skill catalog", ""]
        for skill in skills:
            line = f"- /{skill.name}: {skill.description or '(no description)'}"
            if skill.when_to_use:
                line += f" - {skill.when_to_use}"
            line += f" [kind={skill.skill_kind}]"
            lines.append(line)
        return "\n".join(lines)

    def build_inline_skill_instructions(self) -> str:
        """Render full inline SKILL.md bodies for LLM cognition.

        There are only four project skills today, so Phase 2 injects all inline
        skill instructions. The separate method keeps a clean path for future
        summary-only / lazy-loading behavior if the skill catalog grows.
        """

        skills = [skill for skill in self.list_skills(user_invocable_only=False) if skill.context == "inline"]
        if not skills:
            return ""

        lines = [
            "## Inline Skill Instructions",
            "",
            "Use these SKILL.md instructions as teaching-strategy guidance. "
            "Backend skills may also be executed by the router; cognitive guidance still applies when generating responses.",
            "",
        ]
        for skill in skills:
            allowed_tools = ", ".join(skill.allowed_tools) if skill.allowed_tools else "none"
            lines.extend(
                [
                    f'<skill name="{skill.name}" kind="{skill.skill_kind}">',
                    f"Description: {skill.description or '(no description)'}",
                    f"When to use: {skill.when_to_use or '(unspecified)'}",
                    f"Allowed tools: {allowed_tools}",
                    f"Executor: {skill.executor_path if skill.has_executor else 'none'}",
                    "",
                    skill.get_prompt().strip(),
                    "</skill>",
                    "",
                ]
            )
        return "\n".join(lines).strip()

    def build_skills_prompt_section(self) -> str:
        summary = self.build_skills_summary().strip()
        inline = self.build_inline_skill_instructions().strip()
        if not summary and not inline:
            return ""

        lines = ["# Available Teaching Skills", ""]
        if summary:
            lines.append(summary)
        if inline:
            lines.extend(["", inline])
        return "\n".join(lines)

    def select_candidates(self, question: str, limit: int | None = None) -> list[SkillMatch]:
        self._ensure_discovered()
        normalized_question = _normalize_text(question)
        matches: list[SkillMatch] = []

        for skill in self._skills.values():
            matched_keywords = [
                keyword
                for keyword in skill.trigger_keywords
                if _normalize_text(keyword) and _normalize_text(keyword) in normalized_question
            ]
            blocked_keywords = [
                keyword
                for keyword in skill.avoid_keywords
                if _normalize_text(keyword) and _normalize_text(keyword) in normalized_question
            ]

            score = skill.priority
            score += len(matched_keywords) * 10
            score -= len(blocked_keywords) * 12

            if skill.description:
                desc_terms = [
                    term for term in re.split(r"[,，、/\s]+", _normalize_text(skill.description)) if len(term) >= 2
                ]
                score += min(sum(1 for term in desc_terms[:8] if term in normalized_question), 2)

            if skill.when_to_use:
                usage_terms = [
                    term for term in re.split(r"[,，、/\s]+", _normalize_text(skill.when_to_use)) if len(term) >= 2
                ]
                score += min(sum(1 for term in usage_terms[:8] if term in normalized_question), 2)

            if matched_keywords and score > 0:
                matches.append(
                    SkillMatch(
                        skill=skill,
                        score=score,
                        matched_keywords=matched_keywords,
                        blocked_keywords=blocked_keywords,
                    )
                )

        matches.sort(key=lambda item: (item.score, item.skill.priority), reverse=True)
        return matches[:limit] if limit is not None else matches

    def load_full_text(self, name: str, args: str = "") -> str:
        skill = self.get_skill(name)
        return f'<skill name="{skill.name}">\n{skill.get_prompt(args)}\n</skill>'

    def load_module(self, name: str, script_relative_path: str | None = None) -> ModuleType:
        skill = self.get_skill(name)
        relative_path = script_relative_path or skill.executor_path
        cache_key = (skill.key, relative_path)
        if cache_key in self._module_cache:
            return self._module_cache[cache_key]

        if not skill.skill_root:
            raise FileNotFoundError(f"Skill '{name}' does not have a valid root directory")

        script_path = Path(skill.skill_root) / relative_path
        if not script_path.exists():
            raise FileNotFoundError(f"Skill script not found: {script_path}")

        module_name = f"rag_skill_{skill.key.replace('-', '_')}_{script_path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, script_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Unable to load skill script: {script_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        self._module_cache[cache_key] = module
        return module

    def load_executor(self, name: str, attr: str = "execute") -> Callable:
        module = self.load_module(name)
        executor = getattr(module, attr, None)
        if not callable(executor):
            raise AttributeError(f"Skill '{name}' does not expose callable '{attr}'")
        return executor

    def execute_skill(self, name: str, *args: Any, **kwargs: Any) -> Any:
        try:
            executor = self.load_executor(name)
        except FileNotFoundError:
            if args and isinstance(args[0], str):
                prompt_args = args[0]
            else:
                prompt_args = str(kwargs.get("arguments", ""))
            return self.load_full_text(name, prompt_args)
        return executor(*args, **kwargs)

    def _ensure_discovered(self) -> None:
        self.discover_skills()


_skill_registry: SkillRegistry | None = None


def get_skill_registry() -> SkillRegistry:
    global _skill_registry
    if _skill_registry is None:
        _skill_registry = SkillRegistry()
    return _skill_registry


def get_skill_loader() -> SkillRegistry:
    """Return the shared skill registry used by agent and pipeline code."""
    return get_skill_registry()
