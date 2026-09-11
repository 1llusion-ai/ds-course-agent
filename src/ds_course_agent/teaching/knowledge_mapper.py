"""
知识点映射模块
将自然语言问题映射到标准知识点（canonical_id）
采用三层匹配策略：精确匹配 -> 规则匹配 -> Embedding兜底
"""

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, replace
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

import ds_course_agent.shared.config as config
from ds_course_agent.shared.cache import CacheInfo
from ds_course_agent.shared.embeddings import EmbeddingCircuitMode, create_embedding_model, embed_query_cached
from ds_course_agent.shared.paths import PROJECT_ROOT

logger = logging.getLogger(__name__)


class _StrongIdentity:
    """Keep an unknown cache owner alive so identity keys cannot be recycled."""

    __slots__ = ("value",)

    def __init__(self, value: object) -> None:
        self.value = value

    def __hash__(self) -> int:
        return object.__hash__(self.value)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _StrongIdentity) and self.value is other.value


class _MapperCacheIdentity:
    """Hashable cache key that also owns the mapper used to produce its value."""

    __slots__ = ("mapper", "_key")

    def __init__(self, mapper: Any, key: tuple[object, ...]) -> None:
        self.mapper = mapper
        self._key = key

    def __hash__(self) -> int:
        return hash(self._key)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _MapperCacheIdentity) and self._key == other._key


def _cache_scalar(value: Any) -> tuple[str, Any]:
    """Encode primitive config values without exposing arbitrary object text."""

    if value is None:
        return ("none", None)
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, int):
        return ("int", value)
    if isinstance(value, float):
        return ("float", value)
    if isinstance(value, str):
        return ("str", value)
    return ("identity", _StrongIdentity(value))


def _configured_embedding_identity() -> tuple[object, ...]:
    """Return the model settings that determine query-embedding semantics."""

    try:
        model_name = getattr(config, "MODEL_EMBEDDING", "")
        base_url = getattr(config, "BASE_URL", "")
    except Exception:
        return ("configured_embedding", _StrongIdentity(config))
    return (
        "configured_embedding",
        _cache_scalar(model_name),
        _cache_scalar(base_url),
        _cache_scalar(None),
    )


def _embedding_identity(model: Any) -> tuple[object, ...]:
    """Bind a known embedding client's stable settings or keep unknown clients private."""

    configured_identity = _configured_embedding_identity()
    if model is None:
        return configured_identity

    try:
        model_name = model.model
        base_url = model.openai_api_base
        dimensions = model.dimensions
    except Exception:
        return ("embedding_instance", configured_identity, _StrongIdentity(model))

    actual_identity = (
        "configured_embedding",
        _cache_scalar(model_name),
        _cache_scalar(base_url),
        _cache_scalar(dimensions),
    )
    if actual_identity == configured_identity:
        return configured_identity
    return ("embedding_client", configured_identity, actual_identity)


def _concept_map_config_identity() -> tuple[object, ...]:
    """Return normalized settings that can change concept-map results."""

    raw_mode: Any = "offline_first"
    try:
        raw_mode = getattr(config, "CONCEPT_MAP_EMBEDDING_MODE", "offline_first")
        mode = raw_mode.lower() or "offline_first" if isinstance(raw_mode, str) else raw_mode
    except Exception:
        mode = _StrongIdentity(config)

    raw_timeout: Any = 0.5
    try:
        raw_timeout = getattr(config, "CONCEPT_MAP_QUERY_EMBEDDING_TIMEOUT_SECONDS", 0.5)
        timeout = float(raw_timeout or 0.5) if isinstance(raw_timeout, (bool, int, float, str)) else raw_timeout
    except Exception:
        timeout = raw_timeout

    try:
        raw_skip = getattr(config, "CONCEPT_MAP_SKIP_EMBEDDING_IF_RULE_MATCH", True)
        skip_embedding = bool(raw_skip)
    except Exception:
        skip_embedding = _StrongIdentity(config)

    raw_min_matches: Any = 1
    try:
        raw_min_matches = getattr(config, "CONCEPT_MAP_MIN_RULE_MATCHES_TO_SKIP", 1)
        min_rule_matches = max(1, int(raw_min_matches or 1))
    except Exception:
        min_rule_matches = raw_min_matches

    return (
        "concept_map_config",
        ("embedding_mode", _cache_scalar(mode)),
        ("query_embedding_timeout", _cache_scalar(timeout)),
        ("skip_embedding_if_rule_match", _cache_scalar(skip_embedding)),
        ("min_rule_matches_to_skip", _cache_scalar(min_rule_matches)),
    )


class AliasMatchMode(str, Enum):
    """别名文本的匹配方式。"""

    TOKEN = "token"
    SUBSTRING = "substring"
    CONTEXTUAL = "contextual"


class ConceptMatchStrength(str, Enum):
    """知识点匹配对后续控制流的证据强度。"""

    STRONG = "strong"
    SUPPORTING = "supporting"


@dataclass(frozen=True)
class AliasPolicy:
    """知识图谱中单个别名的声明式匹配策略。"""

    match_mode: AliasMatchMode
    match_strength: ConceptMatchStrength

    @property
    def independently_emits_match(self) -> bool:
        """是否允许该别名单独生成知识点匹配。"""
        return self.match_mode is not AliasMatchMode.CONTEXTUAL and self.match_strength is ConceptMatchStrength.STRONG


@dataclass(frozen=True)
class AliasSpec:
    """归一化后的别名及其所属知识点和匹配策略。"""

    text: str
    normalized_text: str
    concept_id: str
    policy: AliasPolicy
    token_pattern: re.Pattern[str] | None = None


def _trace_concept_map(stage: str, **data) -> None:
    try:
        from ds_course_agent.shared.query_trace import trace_step

        trace_step(stage, **data)
    except Exception:
        logger.debug("Failed to emit concept map trace", exc_info=True)


@dataclass
class MatchedConcept:
    """匹配结果"""

    concept_id: str
    display_name: str
    chapter: str
    method: str  # exact_alias / regex_rule / embedding
    score: float
    match_strength: ConceptMatchStrength = ConceptMatchStrength.STRONG
    routing_eligible: bool = True
    event_eligible: bool = True


class KnowledgeGraph:
    """知识图谱加载与查询"""

    def __init__(self, graph_path: str | None = None):
        if graph_path is None:
            graph_path = PROJECT_ROOT / "data" / "knowledge_graph.json"

        with open(graph_path, encoding="utf-8") as f:
            data = json.load(f)

        self.concepts: dict[str, dict] = {}
        self.alias_to_concept: dict[str, str] = {}  # alias -> canonical_id
        self.alias_specs: dict[str, AliasSpec] = {}
        self.alias_policies = self._parse_alias_policies(data.get("alias_policies", {}))
        self.embeddings: dict[str, np.ndarray] = {}  # canonical_id -> embedding vector

        for concept in data["concepts"]:
            cid = concept["canonical_id"]
            self.concepts[cid] = concept

            # 构建别名映射
            for alias in concept["aliases"]:
                normalized_alias = self._normalize_text(alias)
                self.alias_to_concept[normalized_alias] = cid
                policy = self.alias_policies.get(
                    normalized_alias,
                    self._default_alias_policy(normalized_alias),
                )
                token_pattern = None
                if policy.match_mode is AliasMatchMode.TOKEN:
                    token_pattern = re.compile(
                        rf"(?<![A-Za-z0-9_]){re.escape(normalized_alias)}(?![A-Za-z0-9_])",
                        re.I,
                    )
                self.alias_specs[normalized_alias] = AliasSpec(
                    text=alias,
                    normalized_text=normalized_alias,
                    concept_id=cid,
                    policy=policy,
                    token_pattern=token_pattern,
                )

        # 预编译正则规则（在精确匹配之后应用）
        self.regex_rules = self._build_regex_rules()

        # 加载离线 embedding cache（请求链路默认不在线预计算）
        self._precompute_embeddings()

    def _normalize_text(self, text: str) -> str:
        """文本归一化：去标点、小写、统一空格"""
        text = re.sub(r"[^\w\s]", "", text.lower())
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _parse_alias_policies(self, raw_policies: object) -> dict[str, AliasPolicy]:
        """解析并校验知识图谱顶层别名策略。"""
        if not isinstance(raw_policies, dict):
            raise ValueError("alias_policies must be an object")

        policies: dict[str, AliasPolicy] = {}
        for alias, raw_policy in raw_policies.items():
            if not isinstance(alias, str) or not alias.strip():
                raise ValueError("alias_policies keys must be non-empty strings")
            if not isinstance(raw_policy, dict):
                raise ValueError(f"alias policy for {alias!r} must be an object")

            try:
                policy = AliasPolicy(
                    match_mode=AliasMatchMode(raw_policy["match_mode"]),
                    match_strength=ConceptMatchStrength(raw_policy["match_strength"]),
                )
            except KeyError as exc:
                raise ValueError(f"alias policy for {alias!r} is missing {exc.args[0]!r}") from exc
            except ValueError as exc:
                raise ValueError(f"alias policy for {alias!r} has an invalid enum value") from exc

            normalized_alias = self._normalize_text(alias)
            if not normalized_alias:
                raise ValueError(f"alias policy key {alias!r} is empty after normalization")
            policies[normalized_alias] = policy

        return policies

    @staticmethod
    def _default_alias_policy(normalized_alias: str) -> AliasPolicy:
        """ASCII 别名默认按 token 匹配，中文等别名默认按子串匹配。"""
        match_mode = AliasMatchMode.TOKEN if normalized_alias.isascii() else AliasMatchMode.SUBSTRING
        return AliasPolicy(
            match_mode=match_mode,
            match_strength=ConceptMatchStrength.STRONG,
        )

    def _build_regex_rules(self) -> list[tuple[re.Pattern, str]]:
        """
        构建正则规则
        """
        rules = []

        # SVM 相关
        rules.append((re.compile(r"svm.*核|支持向量机.*核|svm.*kernel", re.I), "svm_kernel"))
        rules.append((re.compile(r"核函数.*svm|核技巧.*svm", re.I), "svm_kernel"))

        # 过拟合相关
        rules.append((re.compile(r"过拟合.*怎么|overfitting.*|泛化.*差", re.I), "overfitting"))

        # 交叉验证相关
        rules.append((re.compile(r"交叉验证.*怎么|k折|k-fold.*怎么", re.I), "cross_validation"))

        # 梯度下降相关
        rules.append((re.compile(r"梯度下降.*怎么|学习率.*怎么|sgd.*怎么", re.I), "gradient_descent"))

        # 决策树相关
        rules.append((re.compile(r"决策树.*剪枝|信息熵.*怎么|信息增益.*", re.I), "decision_tree"))

        # 正则化相关
        rules.append((re.compile(r"正则化.*怎么|l1正则|l2正则|岭回归.*lasso", re.I), "regularization"))

        return rules

    def _precompute_embeddings(self):
        """预计算/加载知识图谱中所有概念的 embedding"""
        # 优先尝试加载离线缓存
        cache_path = PROJECT_ROOT / "data" / "knowledge_graph_embeddings.json"
        env_cache = os.environ.get("KNOWLEDGE_MAPPER_EMBEDDING_CACHE")
        if env_cache:
            cache_path = Path(env_cache)

        if cache_path.exists():
            try:
                with open(cache_path, encoding="utf-8") as f:
                    cache_data = json.load(f)
                for cid, vec in cache_data.items():
                    self.embeddings[cid] = np.array(vec)
                logger.info("Loaded %d embeddings from cache (%s)", len(self.embeddings), cache_path)
                return
            except Exception as e:
                logger.warning("Cache load failed: %s, falling back to online embedding", e)

        online_disabled_by_env = os.environ.get("KNOWLEDGE_MAPPER_DISABLE_ONLINE_EMBEDDINGS") == "1"
        online_enabled_by_config = bool(getattr(config, "CONCEPT_MAP_ONLINE_PRECOMPUTE_ENABLED", False))
        if online_disabled_by_env or not online_enabled_by_config:
            logger.info(
                "Online knowledge mapper concept embedding precompute disabled; "
                "using rule matching and offline cache only"
            )
            return

        try:
            embedding_model = create_embedding_model()

            for cid, concept in self.concepts.items():
                text = concept["display_name"] + " " + " ".join(concept["aliases"][:3])
                try:
                    embedding = embed_query_cached(embedding_model, text)
                    self.embeddings[cid] = np.array(embedding)
                except Exception as e:
                    logger.warning("Embedding failed for %s: %s", cid, e)

            logger.info("Precomputed %d embeddings", len(self.embeddings))

        except Exception as e:
            logger.warning("Embedding model not available: %s", e)

    def get_concept(self, concept_id: str) -> dict | None:
        """获取概念详情"""
        return self.concepts.get(concept_id)

    def get_embedding(self, concept_id: str) -> np.ndarray | None:
        """获取概念预计算embedding"""
        return self.embeddings.get(concept_id)


def _embedding_content_identity(value: Any) -> dict[str, Any]:
    """Return a deterministic digest for one numeric concept embedding."""

    array = np.asarray(value)
    if array.dtype.hasobject:
        raise TypeError("object embeddings do not have a stable content identity")
    contiguous = np.ascontiguousarray(array)
    return {
        "dtype": contiguous.dtype.str,
        "shape": list(contiguous.shape),
        "sha256": hashlib.sha256(contiguous.tobytes(order="C")).hexdigest(),
    }


def _knowledge_graph_content_identity(graph: Any) -> str | None:
    """Hash all graph data consumed by the concept matching algorithm."""

    if type(graph) is not KnowledgeGraph:
        return None

    try:
        alias_specs = []
        for normalized_alias, spec in graph.alias_specs.items():
            token_pattern = None
            if spec.token_pattern is not None:
                token_pattern = [spec.token_pattern.pattern, spec.token_pattern.flags]
            alias_specs.append(
                [
                    normalized_alias,
                    spec.text,
                    spec.concept_id,
                    spec.policy.match_mode.value,
                    spec.policy.match_strength.value,
                    token_pattern,
                ]
            )

        regex_rules = [[pattern.pattern, pattern.flags, concept_id] for pattern, concept_id in graph.regex_rules]
        embeddings = {
            concept_id: _embedding_content_identity(vector) for concept_id, vector in graph.embeddings.items()
        }
        canonical = json.dumps(
            {
                "concepts": graph.concepts,
                "alias_to_concept": graph.alias_to_concept,
                "alias_specs": alias_specs,
                "regex_rules": regex_rules,
                "embeddings": embeddings,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    except Exception:
        return None


def precompute_knowledge_graph_embeddings(
    graph_path: str,
    embedding_cache_path: str,
    force: bool = False,
) -> int:
    """离线预计算知识图谱 embedding 并写入缓存文件。

    Args:
        graph_path: 知识图谱 JSON 路径
        embedding_cache_path: 输出缓存路径
        force: 是否强制重建（即使已有缓存）

    Returns:
        成功缓存的 embedding 数量
    """
    import os

    out_path = Path(embedding_cache_path)
    if not force and out_path.exists():
        try:
            with open(out_path, encoding="utf-8") as f:
                existing = json.load(f)
            logger.info("Cache already exists with %d entries. Use --force to rebuild.", len(existing))
            return len(existing)
        except Exception:
            pass

    with open(graph_path, encoding="utf-8") as f:
        data = json.load(f)

    concepts = {c["canonical_id"]: c for c in data["concepts"]}

    embedding_model = create_embedding_model()

    embeddings: dict[str, list[float]] = {}
    for cid, concept in concepts.items():
        text = concept["display_name"] + " " + " ".join(concept["aliases"][:3])
        try:
            vec = embed_query_cached(embedding_model, text)
            embeddings[cid] = [float(v) for v in vec]
        except Exception as e:
            logger.warning("Precompute failed for %s: %s", cid, e)

    if not embeddings:
        if out_path.exists():
            logger.warning(
                "Precompute produced 0 embeddings; keeping existing cache at %s",
                out_path,
            )
            try:
                with open(out_path, encoding="utf-8") as f:
                    existing = json.load(f)
                return len(existing) if isinstance(existing, dict) else 0
            except Exception:
                return 0
        logger.warning("Precompute produced 0 embeddings; no cache written")
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(embeddings, f, ensure_ascii=False, indent=2)

    # 同时设置环境变量，使同进程后续加载能命中缓存
    os.environ["KNOWLEDGE_MAPPER_EMBEDDING_CACHE"] = str(out_path)
    logger.info("Cached %d embeddings -> %s", len(embeddings), out_path)
    return len(embeddings)


class KnowledgeMapper:
    """知识点映射器"""

    def __init__(self, graph: KnowledgeGraph | None = None):
        self.graph = graph or KnowledgeGraph()
        self._embedding_model = None

    def _get_embedding_model(self):
        """延迟加载 embedding 模型"""
        if self._embedding_model is None:
            self._embedding_model = create_embedding_model(
                timeout_seconds=float(getattr(config, "CONCEPT_MAP_QUERY_EMBEDDING_TIMEOUT_SECONDS", 0.5) or 0.5)
            )
        return self._embedding_model

    def _embed_text(self, text: str) -> np.ndarray:
        """获取文本 embedding"""
        model = self._get_embedding_model()
        embedding = embed_query_cached(
            model,
            text,
            circuit_mode=EmbeddingCircuitMode.OBSERVE_ONLY,
        )
        return np.array(embedding)

    def _cosine_similarity(self, v1: np.ndarray, v2: np.ndarray) -> float:
        """计算余弦相似度"""
        norm1 = np.linalg.norm(v1)
        norm2 = np.linalg.norm(v2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(v1, v2) / (norm1 * norm2))

    def _score_alias_match(self, alias_spec: AliasSpec, normalized: str) -> float:
        """按别名策略评分，contextual/supporting 别名不独立产生命中。"""
        alias = alias_spec.normalized_text
        if not alias or not normalized or not alias_spec.policy.independently_emits_match:
            return 0.0

        if alias == normalized:
            return 1.0

        if alias_spec.policy.match_mode is AliasMatchMode.TOKEN:
            if alias_spec.token_pattern is None or alias_spec.token_pattern.search(normalized) is None:
                return 0.0
            coverage = len(alias) / max(len(normalized), 1)
            return round(min(0.99, 0.72 + 0.25 * coverage), 3)

        # 问句包含完整概念别名时，应视为较强命中。
        if alias in normalized and len(alias) >= 2:
            coverage = len(alias) / max(len(normalized), 1)
            return round(min(0.99, 0.72 + 0.25 * coverage), 3)

        return 0.0

    def map_question(self, question: str, top_k: int = 3, embedding_threshold: float = 0.82) -> list[MatchedConcept]:
        """
        三层匹配策略：
        1. 别名精确匹配（含归一化）
        2. 正则规则匹配
        3. Embedding语义匹配（兜底）

        Args:
            question: 用户问题
            top_k: 返回最大匹配数
            embedding_threshold: embedding匹配阈值

        Returns:
            MatchedConcept列表，按score降序
        """
        matches = []
        matched_ids = set()

        # ===== Layer 1: 别名精确匹配 =====
        normalized = self.graph._normalize_text(question)
        alias_candidates: dict[str, tuple[float, AliasSpec]] = {}
        for alias_spec in self.graph.alias_specs.values():
            score = self._score_alias_match(alias_spec, normalized)
            if score < 0.55:
                continue
            previous = alias_candidates.get(alias_spec.concept_id)
            if previous is None or score > previous[0]:
                alias_candidates[alias_spec.concept_id] = (score, alias_spec)

        for cid, (score, alias_spec) in alias_candidates.items():
            concept = self.graph.get_concept(cid)
            matches.append(
                MatchedConcept(
                    concept_id=cid,
                    display_name=concept["display_name"],
                    chapter=concept["chapter"],
                    method="exact_alias",
                    score=score,
                    match_strength=alias_spec.policy.match_strength,
                    routing_eligible=True,
                    event_eligible=True,
                )
            )
            matched_ids.add(cid)

        # ===== Layer 2: 正则规则匹配 =====
        for pattern, cid in self.graph.regex_rules:
            if cid in matched_ids:
                continue
            if pattern.search(question):
                concept = self.graph.get_concept(cid)
                matches.append(
                    MatchedConcept(
                        concept_id=cid,
                        display_name=concept["display_name"],
                        chapter=concept["chapter"],
                        method="regex_rule",
                        score=0.95,
                        match_strength=ConceptMatchStrength.STRONG,
                        routing_eligible=True,
                        event_eligible=True,
                    )
                )
                matched_ids.add(cid)

        # ===== Layer 3: Embedding语义匹配（兜底）=====
        # 主请求链路采用 offline-first 策略：
        # - concept embeddings 只从离线 cache 加载，默认不在线预计算；
        # - exact/regex 已命中足够高置信概念时，不再为了补满 top_k 调 query embedding；
        # - 只有规则未命中/不足且 embedding 服务健康时，才短超时尝试 query embedding。
        embedding_mode = str(getattr(config, "CONCEPT_MAP_EMBEDDING_MODE", "offline_first") or "offline_first").lower()
        min_rule_matches = max(1, int(getattr(config, "CONCEPT_MAP_MIN_RULE_MATCHES_TO_SKIP", 1) or 1))
        skip_if_rule_match = bool(getattr(config, "CONCEPT_MAP_SKIP_EMBEDDING_IF_RULE_MATCH", True))
        should_skip_embedding = (
            embedding_mode in {"disabled", "off", "none"}
            or not self.graph.embeddings
            or (skip_if_rule_match and len(matches) >= min_rule_matches)
            or len(matches) >= top_k
        )

        if should_skip_embedding:
            reason = "unknown"
            if embedding_mode in {"disabled", "off", "none"}:
                reason = "mode_disabled"
            elif not self.graph.embeddings:
                reason = "no_offline_cache"
            elif skip_if_rule_match and len(matches) >= min_rule_matches:
                reason = "rule_match"
            elif len(matches) >= top_k:
                reason = "top_k_satisfied"
            _trace_concept_map(
                "concept_map.embedding_skipped",
                reason=reason,
                rule_match_count=len(matches),
                top_k=top_k,
                mode=embedding_mode,
                offline_embedding_count=len(self.graph.embeddings),
            )

        if not should_skip_embedding:
            try:
                _trace_concept_map(
                    "concept_map.embedding_used",
                    status="started",
                    rule_match_count=len(matches),
                    top_k=top_k,
                    mode=embedding_mode,
                    timeout_seconds=float(getattr(config, "CONCEPT_MAP_QUERY_EMBEDDING_TIMEOUT_SECONDS", 0.5) or 0.5),
                    offline_embedding_count=len(self.graph.embeddings),
                )
                query_vec = self._embed_text(question)

                embedding_matches = []
                for cid, concept_vec in self.graph.embeddings.items():
                    if cid in matched_ids:
                        continue
                    sim = self._cosine_similarity(query_vec, concept_vec)
                    if sim > embedding_threshold:
                        concept = self.graph.get_concept(cid)
                        embedding_matches.append(
                            MatchedConcept(
                                concept_id=cid,
                                display_name=concept["display_name"],
                                chapter=concept["chapter"],
                                method="embedding",
                                score=round(sim, 3),
                                match_strength=ConceptMatchStrength.SUPPORTING,
                                routing_eligible=False,
                                event_eligible=True,
                            )
                        )

                # 按相似度排序，补充到 matches
                embedding_matches.sort(key=lambda x: x.score, reverse=True)
                added_matches = embedding_matches[: top_k - len(matches)]
                matches.extend(added_matches)
                _trace_concept_map(
                    "concept_map.embedding_used",
                    status="ok",
                    added_count=len(added_matches),
                    candidate_count=len(embedding_matches),
                    final_match_count=len(matches),
                    top_k=top_k,
                    mode=embedding_mode,
                )

            except Exception as e:
                _trace_concept_map(
                    "concept_map.embedding_failed",
                    status="warning",
                    error_type=type(e).__name__,
                    error=str(e)[:200],
                    mode=embedding_mode,
                )
                logger.warning("Embedding match failed: %s", e)

        # 最终排序，取 top_k
        matches.sort(key=lambda x: x.score, reverse=True)
        return matches[:top_k]

    def get_related_concepts(self, concept_id: str) -> list[str]:
        """获取相关概念列表"""
        concept = self.graph.get_concept(concept_id)
        if concept:
            return concept.get("related_concepts", [])
        return []


# 全局单例
_knowledge_mapper: KnowledgeMapper | None = None


def get_knowledge_mapper() -> KnowledgeMapper:
    """获取知识点映射器单例"""
    global _knowledge_mapper
    if _knowledge_mapper is None:
        _knowledge_mapper = KnowledgeMapper()
    return _knowledge_mapper


def _clone_matched_concepts(matches: tuple[MatchedConcept, ...]) -> list[MatchedConcept]:
    """Return fresh dataclass instances so cache contents cannot be mutated."""
    return [replace(match) for match in matches]


def _mapper_cache_identity(mapper: Any) -> _MapperCacheIdentity:
    """Build a stable content key, isolating objects without stable config."""

    config_identity = _concept_map_config_identity()
    if type(mapper) is not KnowledgeMapper:
        return _MapperCacheIdentity(
            mapper,
            ("mapper_instance", _StrongIdentity(mapper), config_identity),
        )

    graph_identity = _knowledge_graph_content_identity(getattr(mapper, "graph", None))
    if graph_identity is None:
        return _MapperCacheIdentity(
            mapper,
            ("mapper_instance", _StrongIdentity(mapper), config_identity),
        )

    model_identity = _embedding_identity(getattr(mapper, "_embedding_model", None))
    return _MapperCacheIdentity(
        mapper,
        ("mapper_config", graph_identity, config_identity, model_identity),
    )


@lru_cache(maxsize=max(0, int(config.QUERY_CACHE_SIZE)))
def _map_question_to_concepts_cached(
    mapper_identity: _MapperCacheIdentity,
    question: str,
    top_k: int,
) -> tuple[MatchedConcept, ...]:
    return tuple(mapper_identity.mapper.map_question(question, top_k))


def clear_map_question_cache() -> None:
    """Clear concept mapping cache; useful for tests and latency harness setup."""
    _map_question_to_concepts_cached.cache_clear()


def map_question_cache_info() -> CacheInfo:
    """Return functools cache_info for concept mapping cache observability."""
    return _map_question_to_concepts_cached.cache_info()


def map_question_to_concepts(question: str, top_k: int = 3) -> list[MatchedConcept]:
    """
    便捷函数：将问题映射到知识点

    Returns:
        MatchedConcept列表，按匹配分数降序
    """
    mapper = get_knowledge_mapper()
    if not config.QUERY_CACHE_ENABLED:
        return mapper.map_question(question, top_k)

    cached = _map_question_to_concepts_cached(
        _mapper_cache_identity(mapper),
        str(question or ""),
        int(top_k),
    )
    return _clone_matched_concepts(cached)


if __name__ == "__main__":
    # 测试
    mapper = get_knowledge_mapper()

    test_questions = [
        "什么是支持向量机？",
        "SVM的核函数怎么选？",
        "核技巧是什么？",
        "kernel trick的原理",
        "过拟合怎么处理？",
        "梯度下降的学习率怎么调？",
    ]

    for q in test_questions:
        print(f"\n问题: {q}")
        matches = mapper.map_question(q)
        for m in matches:
            print(f"  -> {m.display_name} ({m.concept_id}) | {m.method} | score={m.score}")
