"""Stable knowledge retrieval contracts and deterministic orchestration.

SQLite-backed adapters remain authoritative. Optional vector adapters are
projections that may improve ranking but must never be required for retrieval.
This module intentionally owns no database schema or mutation.
"""

from __future__ import annotations

import hashlib
import html
import json
import math
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol


KNOWLEDGE_SCHEMA_VERSION = 1
DEFAULT_TOP_K = 5
DEFAULT_MAX_CHARS = 6_000
MAX_TOP_K = 50
MAX_MAX_CHARS = 65_536
DEFAULT_KEYWORD_WEIGHT = 0.4
DEFAULT_VECTOR_WEIGHT = 0.6

_OUTBOX_OPERATIONS = frozenset({"upsert", "delete"})
_PROMPT_SECRET_RE = re.compile(
    r"\b(?:"
    r"sk-(?:proj-|svcacct-|live-)?[A-Za-z0-9_-]{20,}|"
    r"ghp_[A-Za-z0-9]{36}|"
    r"github_pat_[A-Za-z0-9_]{50,}|"
    r"AKIA[0-9A-Z]{16}|"
    r"ASIA[0-9A-Z]{16}"
    r")\b"
)
_PROMPT_ASSIGNMENT_RE = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD))"
    r"\s*[:=]\s*[^\s,;]+"
)


class _FrozenStringMap(Mapping[str, str]):
    """Small hashable immutable mapping used by frozen public contracts."""

    __slots__ = ("_items", "_values")

    def __init__(self, value: Mapping[str, str] | None = None) -> None:
        items: list[tuple[str, str]] = []
        for key, item in (value or {}).items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("metadata keys must be non-empty strings")
            if not isinstance(item, str):
                raise TypeError("metadata values must be strings")
            items.append((key.strip(), item))
        self._items = tuple(sorted(items))
        self._values = dict(self._items)

    def __getitem__(self, key: str) -> str:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __hash__(self) -> int:
        return hash(self._items)

    def __repr__(self) -> str:
        return repr(self._values)


def _required_text(
    value: object,
    field_name: str,
    *,
    preserve: bool = False,
    max_length: int = 65_536,
) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value if preserve else value.strip()
    if not normalized.strip():
        raise ValueError(f"{field_name} must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field_name} exceeds {max_length} characters")
    return normalized


def _optional_text(value: object, field_name: str, *, max_length: int = 4_096) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if len(normalized) > max_length:
        raise ValueError(f"{field_name} exceeds {max_length} characters")
    return normalized


def _positive_int(value: object, field_name: str, *, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    if value <= 0:
        raise ValueError(f"{field_name} must be positive")
    if maximum is not None and value > maximum:
        raise ValueError(f"{field_name} must not exceed {maximum}")
    return value


def _non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return value


def _finite_score(value: object, field_name: str = "score") -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (tuple, list)):
        raise TypeError(f"{field_name} must be a tuple or list of strings")
    normalized = tuple(
        _required_text(item, field_name, max_length=256) for item in value
    )
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} must not contain duplicates")
    return normalized


def _score_text(score: float) -> str:
    return format(score, ".17g")


def stable_record_id(
    namespace: str,
    source_type: str,
    source_id: str,
    *,
    source_revision: str = "1",
    chunk_index: int = 0,
) -> str:
    """Return a deterministic ID that remains stable across source revisions."""
    _required_text(source_revision, "source_revision", max_length=1_024)
    components = (
        _required_text(namespace, "namespace", max_length=256),
        _required_text(source_type, "source_type", max_length=256),
        _required_text(source_id, "source_id", max_length=4_096),
        _non_negative_int(chunk_index, "chunk_index"),
    )
    payload = json.dumps(
        components,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"kr_{hashlib.sha256(payload).hexdigest()[:32]}"


@dataclass(frozen=True)
class KnowledgeRecord:
    """Normalized durable knowledge or knowledge-chunk record."""

    record_id: str
    namespace: str
    source_type: str
    source_id: str
    content: str
    source_revision: str = "1"
    chunk_index: int = 0
    metadata: Mapping[str, str] = field(default_factory=dict)
    schema_version: int = KNOWLEDGE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "record_id",
            _required_text(self.record_id, "record_id", max_length=256),
        )
        object.__setattr__(
            self,
            "namespace",
            _required_text(self.namespace, "namespace", max_length=256),
        )
        object.__setattr__(
            self,
            "source_type",
            _required_text(self.source_type, "source_type", max_length=256),
        )
        object.__setattr__(
            self,
            "source_id",
            _required_text(self.source_id, "source_id", max_length=4_096),
        )
        object.__setattr__(
            self,
            "content",
            _required_text(self.content, "content", preserve=True),
        )
        object.__setattr__(
            self,
            "source_revision",
            _required_text(
                self.source_revision,
                "source_revision",
                max_length=1_024,
            ),
        )
        object.__setattr__(
            self,
            "chunk_index",
            _non_negative_int(self.chunk_index, "chunk_index"),
        )
        object.__setattr__(self, "metadata", _FrozenStringMap(self.metadata))
        version = _positive_int(self.schema_version, "schema_version")
        if version != KNOWLEDGE_SCHEMA_VERSION:
            raise ValueError(f"unsupported knowledge schema version: {version}")
        object.__setattr__(self, "schema_version", version)

    @classmethod
    def from_source(
        cls,
        *,
        namespace: str,
        source_type: str,
        source_id: str,
        content: str,
        source_revision: str = "1",
        chunk_index: int = 0,
        metadata: Mapping[str, str] | None = None,
    ) -> KnowledgeRecord:
        return cls(
            record_id=stable_record_id(
                namespace,
                source_type,
                source_id,
                source_revision=source_revision,
                chunk_index=chunk_index,
            ),
            namespace=namespace,
            source_type=source_type,
            source_id=source_id,
            content=content,
            source_revision=source_revision,
            chunk_index=chunk_index,
            metadata=metadata or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "namespace": self.namespace,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "source_revision": self.source_revision,
            "chunk_index": self.chunk_index,
            "content": self.content,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class KnowledgeQuery:
    text: str
    namespaces: tuple[str, ...] = ()
    top_k: int = DEFAULT_TOP_K
    max_chars: int = DEFAULT_MAX_CHARS

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "text",
            _required_text(self.text, "text", max_length=32_768),
        )
        object.__setattr__(
            self,
            "namespaces",
            _string_tuple(self.namespaces, "namespaces"),
        )
        object.__setattr__(
            self,
            "top_k",
            _positive_int(self.top_k, "top_k", maximum=MAX_TOP_K),
        )
        object.__setattr__(
            self,
            "max_chars",
            _positive_int(
                self.max_chars,
                "max_chars",
                maximum=MAX_MAX_CHARS,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "namespaces": list(self.namespaces),
            "top_k": self.top_k,
            "max_chars": self.max_chars,
        }


@dataclass(frozen=True)
class RetrievalHit:
    record_id: str
    source_type: str
    source_id: str
    content: str
    score: float
    score_kind: str
    provenance: Mapping[str, str]
    namespace: str = "global"
    source_revision: str = "1"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "record_id",
            _required_text(self.record_id, "record_id", max_length=256),
        )
        object.__setattr__(
            self,
            "source_type",
            _required_text(self.source_type, "source_type", max_length=256),
        )
        object.__setattr__(
            self,
            "source_id",
            _required_text(self.source_id, "source_id", max_length=4_096),
        )
        object.__setattr__(
            self,
            "content",
            _required_text(self.content, "content", preserve=True),
        )
        score = _finite_score(self.score)
        object.__setattr__(self, "score", score)
        score_kind = _required_text(
            self.score_kind,
            "score_kind",
            max_length=256,
        )
        object.__setattr__(self, "score_kind", score_kind)
        namespace = _required_text(
            self.namespace,
            "namespace",
            max_length=256,
        )
        object.__setattr__(self, "namespace", namespace)
        source_revision = _required_text(
            self.source_revision,
            "source_revision",
            max_length=1_024,
        )
        object.__setattr__(self, "source_revision", source_revision)
        provenance = dict(_FrozenStringMap(self.provenance))
        provenance.setdefault("namespace", namespace)
        provenance.setdefault("source_type", self.source_type)
        provenance.setdefault("source_id", self.source_id)
        provenance.setdefault("source_revision", source_revision)
        provenance.setdefault("retrieval_algorithm", score_kind)
        provenance.setdefault("score", _score_text(score))
        object.__setattr__(self, "provenance", _FrozenStringMap(provenance))

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "namespace": self.namespace,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "source_revision": self.source_revision,
            "content": self.content,
            "score": self.score,
            "score_kind": self.score_kind,
            "provenance": dict(self.provenance),
        }


@dataclass(frozen=True)
class RetrievalBatch:
    """Adapter response with enough metadata to reject stale projections."""

    hits: tuple[RetrievalHit, ...] = ()
    adapter: str = "unknown"
    algorithm: str = "unknown"
    available: bool = True
    stale: bool = False
    index_version: str = ""
    embedding_model: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.hits, list):
            object.__setattr__(self, "hits", tuple(self.hits))
        if not isinstance(self.hits, tuple) or not all(
            isinstance(hit, RetrievalHit) for hit in self.hits
        ):
            raise TypeError("hits must be a tuple or list of RetrievalHit values")
        object.__setattr__(
            self,
            "adapter",
            _required_text(self.adapter, "adapter", max_length=256),
        )
        object.__setattr__(
            self,
            "algorithm",
            _required_text(self.algorithm, "algorithm", max_length=256),
        )
        if not isinstance(self.available, bool):
            raise TypeError("available must be a boolean")
        if not isinstance(self.stale, bool):
            raise TypeError("stale must be a boolean")
        object.__setattr__(
            self,
            "index_version",
            _optional_text(self.index_version, "index_version"),
        )
        object.__setattr__(
            self,
            "embedding_model",
            _optional_text(self.embedding_model, "embedding_model"),
        )
        object.__setattr__(self, "reason", _optional_text(self.reason, "reason"))


class KnowledgeAdapter(Protocol):
    def query(
        self,
        request: KnowledgeQuery,
    ) -> RetrievalBatch | tuple[RetrievalHit, ...]:
        """Retrieve candidates without changing authoritative storage."""


class AuthoritativeKnowledgeAdapter(KnowledgeAdapter, Protocol):
    def hydrate(self, record_ids: Sequence[str]) -> tuple[RetrievalHit, ...]:
        """Load canonical content and revision for bounded record IDs."""


class OptionalRedisAdapter:
    """Lazy, dependency-free boundary around an injected Redis implementation."""

    def __init__(self, factory: Callable[[], KnowledgeAdapter | None] | None) -> None:
        self._factory = factory
        self._adapter: KnowledgeAdapter | None = None

    @property
    def initialized(self) -> bool:
        return self._adapter is not None

    def query(self, request: KnowledgeQuery) -> RetrievalBatch:
        if self._factory is None:
            return RetrievalBatch(
                adapter="redis",
                algorithm="vector",
                available=False,
                reason="redis_not_configured",
            )
        if self._adapter is None:
            try:
                self._adapter = self._factory()
            except Exception:
                return RetrievalBatch(
                    adapter="redis",
                    algorithm="vector",
                    available=False,
                    reason="redis_load_failed",
                )
        if self._adapter is None:
            return RetrievalBatch(
                adapter="redis",
                algorithm="vector",
                available=False,
                reason="redis_unavailable",
            )
        try:
            result = self._adapter.query(request)
        except Exception:
            return RetrievalBatch(
                adapter="redis",
                algorithm="vector",
                available=False,
                reason="redis_query_failed",
            )
        return _coerce_batch(
            result,
            default_adapter="redis",
            default_algorithm="vector",
        )


LazyRedisAdapter = OptionalRedisAdapter


def _coerce_batch(
    result: RetrievalBatch | tuple[RetrievalHit, ...] | list[RetrievalHit],
    *,
    default_adapter: str,
    default_algorithm: str,
) -> RetrievalBatch:
    if isinstance(result, RetrievalBatch):
        return result
    if isinstance(result, (tuple, list)) and all(
        isinstance(hit, RetrievalHit) for hit in result
    ):
        return RetrievalBatch(
            hits=tuple(result),
            adapter=default_adapter,
            algorithm=default_algorithm,
        )
    raise TypeError("adapter query must return RetrievalBatch or RetrievalHit values")


def _copy_hit(
    hit: RetrievalHit,
    *,
    content: str | None = None,
    score: float | None = None,
    score_kind: str | None = None,
    provenance: Mapping[str, str] | None = None,
) -> RetrievalHit:
    return RetrievalHit(
        record_id=hit.record_id,
        namespace=hit.namespace,
        source_type=hit.source_type,
        source_id=hit.source_id,
        source_revision=hit.source_revision,
        content=hit.content if content is None else content,
        score=hit.score if score is None else score,
        score_kind=hit.score_kind if score_kind is None else score_kind,
        provenance=hit.provenance if provenance is None else provenance,
    )


def normalize_scores(
    hits: Sequence[RetrievalHit],
    *,
    adapter: str = "unknown",
    algorithm: str = "unknown",
    index_version: str = "",
    embedding_model: str = "",
) -> tuple[RetrievalHit, ...]:
    """Min-max normalize higher-is-better scores with deterministic ties."""
    if not all(isinstance(hit, RetrievalHit) for hit in hits):
        raise TypeError("hits must contain RetrievalHit values")
    ordered = sorted(
        hits,
        key=lambda hit: (
            -hit.score,
            hit.record_id,
            hit.source_type,
            hit.source_id,
            hit.source_revision,
        ),
    )
    unique: list[RetrievalHit] = []
    seen: set[str] = set()
    for hit in ordered:
        if hit.record_id not in seen:
            seen.add(hit.record_id)
            unique.append(hit)
    if not unique:
        return ()

    minimum = min(hit.score for hit in unique)
    maximum = max(hit.score for hit in unique)
    normalized: list[RetrievalHit] = []
    for hit in unique:
        score = 1.0 if maximum == minimum else (hit.score - minimum) / (maximum - minimum)
        score = round(score, 12)
        provenance = dict(hit.provenance)
        provenance.update(
            {
                "adapter": adapter,
                "retrieval_algorithm": algorithm,
                "raw_score": _score_text(hit.score),
                "raw_score_kind": hit.score_kind,
                "score": _score_text(score),
            }
        )
        if index_version:
            provenance["index_version"] = index_version
        if embedding_model:
            provenance["embedding_model"] = embedding_model
        normalized.append(
            _copy_hit(
                hit,
                score=score,
                score_kind="normalized",
                provenance=provenance,
            )
        )
    return tuple(
        sorted(
            normalized,
            key=lambda hit: (-hit.score, hit.record_id, hit.source_id),
        )
    )


def _weight(value: object, field_name: str) -> float:
    result = _finite_score(value, field_name)
    if result <= 0:
        raise ValueError(f"{field_name} must be positive")
    return result


def fuse_hits(
    keyword_hits: Sequence[RetrievalHit],
    vector_hits: Sequence[RetrievalHit],
    *,
    keyword_weight: float = DEFAULT_KEYWORD_WEIGHT,
    vector_weight: float = DEFAULT_VECTOR_WEIGHT,
) -> tuple[RetrievalHit, ...]:
    """Fuse normalized keyword/vector scores while preferring SQLite content."""
    keyword_weight = _weight(keyword_weight, "keyword_weight")
    vector_weight = _weight(vector_weight, "vector_weight")
    weight_total = keyword_weight + vector_weight
    keyword_weight /= weight_total
    vector_weight /= weight_total

    keyword_by_id = {hit.record_id: hit for hit in keyword_hits}
    vector_by_id = {hit.record_id: hit for hit in vector_hits}
    fused: list[RetrievalHit] = []
    for record_id in sorted(keyword_by_id.keys() | vector_by_id.keys()):
        keyword = keyword_by_id.get(record_id)
        vector = vector_by_id.get(record_id)
        canonical = keyword or vector
        if canonical is None:
            continue

        vector_revision_matches = (
            keyword is None
            or vector is None
            or keyword.source_revision == vector.source_revision
        )
        keyword_component = keyword.score * keyword_weight if keyword else 0.0
        vector_component = (
            vector.score * vector_weight
            if vector is not None and vector_revision_matches
            else 0.0
        )
        score = round(keyword_component + vector_component, 12)
        provenance = dict(canonical.provenance)
        algorithms = sorted(
            {
                hit.provenance["retrieval_algorithm"]
                for hit in (keyword, vector)
                if hit is not None
            }
        )
        provenance.update(
            {
                "content_source": "sqlite",
                "retrieval_algorithm": "weighted_fusion",
                "retrieval_algorithms": ",".join(algorithms),
                "keyword_weight": _score_text(keyword_weight),
                "vector_weight": _score_text(vector_weight),
                "keyword_score": _score_text(keyword.score if keyword else 0.0),
                "vector_score": _score_text(vector.score if vector else 0.0),
                "score": _score_text(score),
            }
        )
        if not vector_revision_matches:
            provenance["vector_revision_mismatch"] = "true"
        if vector is not None:
            for key in ("embedding_model", "index_version"):
                if key in vector.provenance:
                    provenance[key] = vector.provenance[key]
        fused.append(
            _copy_hit(
                canonical,
                score=score,
                score_kind="weighted_fusion",
                provenance=provenance,
            )
        )
    return tuple(
        sorted(
            fused,
            key=lambda hit: (-hit.score, hit.record_id, hit.source_id),
        )
    )


def bound_hits(
    hits: Sequence[RetrievalHit],
    *,
    top_k: int,
    max_chars: int,
) -> tuple[RetrievalHit, ...]:
    """Apply final rank and content bounds, truncating only the last hit."""
    top_k = _positive_int(top_k, "top_k", maximum=MAX_TOP_K)
    max_chars = _positive_int(max_chars, "max_chars", maximum=MAX_MAX_CHARS)
    bounded: list[RetrievalHit] = []
    remaining = max_chars
    for hit in hits:
        if len(bounded) >= top_k or remaining <= 0:
            break
        if len(hit.content) <= remaining:
            bounded.append(hit)
            remaining -= len(hit.content)
            continue
        provenance = dict(hit.provenance)
        provenance.update(
            {
                "truncated": "true",
                "original_chars": str(len(hit.content)),
                "returned_chars": str(remaining),
            }
        )
        bounded.append(
            _copy_hit(
                hit,
                content=hit.content[:remaining],
                provenance=provenance,
            )
        )
        remaining = 0
    return tuple(bounded)


class KnowledgeRetriever:
    """Orchestrate authoritative keyword retrieval and optional vector fusion."""

    def __init__(
        self,
        keyword_adapter: KnowledgeAdapter,
        vector_adapter: KnowledgeAdapter | None = None,
        *,
        expected_index_version: str = "",
        expected_embedding_model: str = "",
        keyword_weight: float = DEFAULT_KEYWORD_WEIGHT,
        vector_weight: float = DEFAULT_VECTOR_WEIGHT,
    ) -> None:
        if not hasattr(keyword_adapter, "query"):
            raise TypeError("keyword_adapter must provide query()")
        if vector_adapter is not None and not hasattr(vector_adapter, "query"):
            raise TypeError("vector_adapter must provide query()")
        self._keyword_adapter = keyword_adapter
        self._vector_adapter = vector_adapter
        self._expected_index_version = _optional_text(
            expected_index_version,
            "expected_index_version",
        )
        self._expected_embedding_model = _optional_text(
            expected_embedding_model,
            "expected_embedding_model",
        )
        self._keyword_weight = _weight(keyword_weight, "keyword_weight")
        self._vector_weight = _weight(vector_weight, "vector_weight")

    def query(self, request: KnowledgeQuery) -> tuple[RetrievalHit, ...]:
        if not isinstance(request, KnowledgeQuery):
            raise TypeError("request must be a KnowledgeQuery")
        keyword_batch = _coerce_batch(
            self._keyword_adapter.query(request),
            default_adapter="sqlite",
            default_algorithm="keyword",
        )
        keyword_hits = normalize_scores(
            keyword_batch.hits,
            adapter=keyword_batch.adapter,
            algorithm=keyword_batch.algorithm,
            index_version=keyword_batch.index_version,
            embedding_model=keyword_batch.embedding_model,
        )

        fallback_reason = ""
        vector_batch: RetrievalBatch | None = None
        if self._vector_adapter is None:
            fallback_reason = "vector_not_configured"
        else:
            try:
                vector_batch = _coerce_batch(
                    self._vector_adapter.query(request),
                    default_adapter="redis",
                    default_algorithm="vector",
                )
            except Exception:
                fallback_reason = "vector_query_failed"

        if vector_batch is not None and not fallback_reason:
            if not vector_batch.available:
                fallback_reason = vector_batch.reason or "vector_unavailable"
            elif vector_batch.stale:
                fallback_reason = vector_batch.reason or "vector_stale"
            elif (
                self._expected_index_version
                and vector_batch.index_version != self._expected_index_version
            ):
                fallback_reason = "index_version_mismatch"
            elif (
                self._expected_embedding_model
                and vector_batch.embedding_model != self._expected_embedding_model
            ):
                fallback_reason = "embedding_model_mismatch"
            elif not vector_batch.hits:
                fallback_reason = "vector_no_hits"

        if fallback_reason:
            annotated = []
            for hit in keyword_hits:
                provenance = dict(hit.provenance)
                provenance.update(
                    {
                        "fallback": "sqlite_keyword",
                        "fallback_reason": fallback_reason,
                    }
                )
                annotated.append(_copy_hit(hit, provenance=provenance))
            ranked = tuple(annotated)
        else:
            assert vector_batch is not None
            vector_hits = self._hydrate_vector_hits(vector_batch.hits, keyword_hits)
            if not vector_hits:
                return bound_hits(
                    self._annotate_fallback(keyword_hits, "vector_not_hydrated"),
                    top_k=request.top_k,
                    max_chars=request.max_chars,
                )
            vector_hits = normalize_scores(
                vector_hits,
                adapter=vector_batch.adapter,
                algorithm=vector_batch.algorithm,
                index_version=vector_batch.index_version,
                embedding_model=vector_batch.embedding_model,
            )
            ranked = fuse_hits(
                keyword_hits,
                vector_hits,
                keyword_weight=self._keyword_weight,
                vector_weight=self._vector_weight,
            )
        return bound_hits(
            ranked,
            top_k=request.top_k,
            max_chars=request.max_chars,
        )

    @staticmethod
    def _annotate_fallback(
        hits: Sequence[RetrievalHit],
        reason: str,
    ) -> tuple[RetrievalHit, ...]:
        annotated = []
        for hit in hits:
            provenance = dict(hit.provenance)
            provenance.update(
                {
                    "fallback": "sqlite_keyword",
                    "fallback_reason": reason,
                }
            )
            annotated.append(_copy_hit(hit, provenance=provenance))
        return tuple(annotated)

    def _hydrate_vector_hits(
        self,
        vector_hits: Sequence[RetrievalHit],
        keyword_hits: Sequence[RetrievalHit],
    ) -> tuple[RetrievalHit, ...]:
        """Replace projection content with authoritative SQLite content."""
        record_ids = tuple(dict.fromkeys(hit.record_id for hit in vector_hits))
        canonical = {hit.record_id: hit for hit in keyword_hits}
        hydrate = getattr(self._keyword_adapter, "hydrate", None)
        if callable(hydrate):
            canonical.update(
                {
                    hit.record_id: hit
                    for hit in hydrate(record_ids)
                    if isinstance(hit, RetrievalHit)
                }
            )

        hydrated: list[RetrievalHit] = []
        for projected in vector_hits:
            source = canonical.get(projected.record_id)
            if source is None or source.source_revision != projected.source_revision:
                continue
            provenance = dict(projected.provenance)
            provenance["content_source"] = "sqlite"
            hydrated.append(
                _copy_hit(
                    source,
                    score=projected.score,
                    score_kind=projected.score_kind,
                    provenance=provenance,
                )
            )
        return tuple(hydrated)


def _redact_prompt_text(value: str) -> str:
    value = _PROMPT_SECRET_RE.sub("[REDACTED_SECRET]", value)
    return _PROMPT_ASSIGNMENT_RE.sub(r"\1=[REDACTED_SECRET]", value)


def format_retrieval_hits_for_prompt(
    hits: Sequence[RetrievalHit],
    *,
    max_chars: int = 4_000,
) -> str:
    """Render bounded retrieval evidence as escaped, untrusted references."""
    max_chars = _positive_int(max_chars, "max_chars", maximum=MAX_MAX_CHARS)
    if not hits:
        return ""
    opening = '<knowledge_references trust="untrusted" authority="sqlite">\n'
    closing = "</knowledge_references>"
    rendered = opening
    for hit in hits:
        provenance = {
            key: _redact_prompt_text(value)
            for key, value in hit.provenance.items()
            if key
            in {
                "adapter",
                "fallback",
                "fallback_reason",
                "index_version",
                "retrieval_algorithm",
            }
        }
        attrs = {
            "id": hit.record_id,
            "namespace": hit.namespace,
            "source_type": hit.source_type,
            "source_id": hit.source_id,
            "source_revision": hit.source_revision,
            "score": _score_text(hit.score),
            **provenance,
        }
        attr_text = " ".join(
            f'{key}="{html.escape(value, quote=True)}"'
            for key, value in sorted(attrs.items())
        )
        content = html.escape(_redact_prompt_text(hit.content))
        prefix = f"  <reference {attr_text}>"
        suffix = "</reference>\n"
        available = max_chars - len(rendered) - len(closing) - len(prefix) - len(suffix)
        if available <= 0:
            break
        rendered += prefix + content[:available] + suffix
        if available < len(content):
            break
    if rendered == opening:
        return ""
    return rendered + closing


@dataclass(frozen=True)
class IndexOutboxEntry:
    """Read-only description of one pending projection operation."""

    event_id: str
    operation: str
    record_id: str
    source_revision: str
    created_at: str
    attempts: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "event_id",
            _required_text(self.event_id, "event_id", max_length=256),
        )
        operation = _required_text(
            self.operation,
            "operation",
            max_length=32,
        )
        if operation not in _OUTBOX_OPERATIONS:
            raise ValueError(f"unsupported outbox operation: {operation}")
        object.__setattr__(self, "operation", operation)
        object.__setattr__(
            self,
            "record_id",
            _required_text(self.record_id, "record_id", max_length=256),
        )
        object.__setattr__(
            self,
            "source_revision",
            _required_text(
                self.source_revision,
                "source_revision",
                max_length=1_024,
            ),
        )
        object.__setattr__(
            self,
            "created_at",
            _required_text(self.created_at, "created_at", max_length=128),
        )
        object.__setattr__(
            self,
            "attempts",
            _non_negative_int(self.attempts, "attempts"),
        )


IndexOutboxEvent = IndexOutboxEntry


class IndexOutboxReader(Protocol):
    def pending(self, *, limit: int) -> tuple[IndexOutboxEntry, ...]:
        """Read pending projection work without acknowledging or mutating it."""


@dataclass(frozen=True)
class IndexRebuildRequest:
    index_version: str
    embedding_model: str
    namespaces: tuple[str, ...] = ()
    batch_size: int = 100
    cursor: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "index_version",
            _required_text(
                self.index_version,
                "index_version",
                max_length=256,
            ),
        )
        object.__setattr__(
            self,
            "embedding_model",
            _required_text(
                self.embedding_model,
                "embedding_model",
                max_length=256,
            ),
        )
        object.__setattr__(
            self,
            "namespaces",
            _string_tuple(self.namespaces, "namespaces"),
        )
        object.__setattr__(
            self,
            "batch_size",
            _positive_int(self.batch_size, "batch_size", maximum=1_000),
        )
        object.__setattr__(self, "cursor", _optional_text(self.cursor, "cursor"))


@dataclass(frozen=True)
class IndexRebuildResult:
    index_version: str
    processed: int
    failed: int
    complete: bool
    next_cursor: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "index_version",
            _required_text(
                self.index_version,
                "index_version",
                max_length=256,
            ),
        )
        object.__setattr__(
            self,
            "processed",
            _non_negative_int(self.processed, "processed"),
        )
        object.__setattr__(
            self,
            "failed",
            _non_negative_int(self.failed, "failed"),
        )
        if not isinstance(self.complete, bool):
            raise TypeError("complete must be a boolean")
        object.__setattr__(
            self,
            "next_cursor",
            _optional_text(self.next_cursor, "next_cursor"),
        )
        object.__setattr__(self, "reason", _optional_text(self.reason, "reason"))


class IndexRebuilder(Protocol):
    def rebuild(self, request: IndexRebuildRequest) -> IndexRebuildResult:
        """Rebuild an optional projection from authoritative records."""


__all__ = [
    "DEFAULT_KEYWORD_WEIGHT",
    "DEFAULT_MAX_CHARS",
    "DEFAULT_TOP_K",
    "DEFAULT_VECTOR_WEIGHT",
    "MAX_MAX_CHARS",
    "MAX_TOP_K",
    "AuthoritativeKnowledgeAdapter",
    "IndexOutboxEntry",
    "IndexOutboxEvent",
    "IndexOutboxReader",
    "IndexRebuildRequest",
    "IndexRebuildResult",
    "IndexRebuilder",
    "KnowledgeAdapter",
    "KnowledgeQuery",
    "KnowledgeRecord",
    "KnowledgeRetriever",
    "LazyRedisAdapter",
    "OptionalRedisAdapter",
    "RetrievalBatch",
    "RetrievalHit",
    "bound_hits",
    "format_retrieval_hits_for_prompt",
    "fuse_hits",
    "normalize_scores",
    "stable_record_id",
]
