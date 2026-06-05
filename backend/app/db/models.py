from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # User-scoped LLM overrides (BYOK + per-user provider switching).
    # When set, these take precedence over the server-side .env values, so a
    # user can swap DeepSeek <-> Qwen <-> OpenAI without a redeploy.
    llm_api_key: Mapped[Optional[str]] = mapped_column(String(255), default=None)
    llm_base_url: Mapped[Optional[str]] = mapped_column(String(512), default=None)
    llm_model: Mapped[Optional[str]] = mapped_column(String(120), default=None)


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    filename: Mapped[str] = mapped_column(String(512))
    storage_path: Mapped[str] = mapped_column(String(1024))
    file_format: Mapped[str] = mapped_column(String(32))  # csv, parquet, xlsx, json
    rows: Mapped[int] = mapped_column(Integer, default=0)
    columns: Mapped[int] = mapped_column(Integer, default=0)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    schema_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Derived-dataset lineage: a dataset produced by an algorithm step carries
    # kind="derived", its parent id, and the op that made it. Lets users inspect
    # every pipeline stage, branch from it, and compare (e.g. 原始 vs 去噪后).
    kind: Mapped[str] = mapped_column(String(16), default="source")  # source | derived
    derived_from: Mapped[Optional[int]] = mapped_column(
        ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True
    )
    lineage: Mapped[dict] = mapped_column(JSON, default=dict)  # {from, from_name, op:{slug,label,params}}
    # Auto-GC pin: a derived dataset is reclaimable by the garbage collector
    # unless the user has KEPT it (in place, without promoting to source — which
    # would lose its tree position). Source datasets and kept derived ones are
    # never swept. See services.datasets.gc_derived_datasets.
    kept: Mapped[bool] = mapped_column(Boolean, default=False)


class Algorithm(Base):
    """A callable tool — built-in, user-uploaded, or LLM-generated."""

    __tablename__ = "algorithms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    slug: Mapped[str] = mapped_column(String(120), index=True)  # e.g. "savgol_filter"
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(64), index=True)  # e.g. "filter", "regression"
    description: Mapped[str] = mapped_column(Text, default="")

    source: Mapped[str] = mapped_column(String(32))  # "builtin" | "user" | "ai"
    language: Mapped[str] = mapped_column(String(32), default="python")
    code: Mapped[str] = mapped_column(Text, default="")  # for user / ai algorithms
    builtin_ref: Mapped[Optional[str]] = mapped_column(String(255), default=None)  # for builtin

    params_schema: Mapped[dict] = mapped_column(JSON, default=dict)  # JSON-Schema-ish
    returns: Mapped[str] = mapped_column(String(32), default="dataframe")

    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)  # passed test
    test_report: Mapped[dict] = mapped_column(JSON, default=dict)

    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class Run(Base):
    """A single execution of an algorithm against a dataset."""

    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    algorithm_id: Mapped[int] = mapped_column(ForeignKey("algorithms.id", ondelete="CASCADE"))
    dataset_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True
    )

    params: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|ok|error
    error: Mapped[str] = mapped_column(Text, default="")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)

    result_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    result_dataset_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True
    )
    result_artifacts: Mapped[list] = mapped_column(JSON, default=list)
    logs: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class FormatAdapter(Base):
    """An LLM-generated (or user-uploaded) parser for a file format the
    built-in pandas readers don't understand. Looked up by file extension
    on subsequent uploads so the user only has to teach Numetrix a format
    once."""

    __tablename__ = "format_adapters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    extension: Mapped[str] = mapped_column(String(32), index=True)  # ".ndax" (with dot, lowercase)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    code: Mapped[str] = mapped_column(Text)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    test_report: Mapped[dict] = mapped_column(JSON, default=dict)
    sample_size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class FlowTemplate(Base):
    """A reusable multi-step pipeline — the ordered tool chain captured from a
    conversation's flow graph, replayable on new data. Bridges the chat
    orchestration and the manual run side."""

    __tablename__ = "flow_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    # steps: [{ "action": "run_tool", "slug": "...", "params": {...}, "label": "..." }, ...]
    # — the LINEAR execution order used by replay (derived from `graph` topo-sort
    # when edited on the free-form canvas).
    steps: Mapped[list] = mapped_column(JSON, default=list)
    # Free-form React-Flow layout: { nodes: [{id, slug, params, label, position}],
    # edges: [{source, target}] }. Purely for the visual canvas; replay still
    # uses `steps`. Empty for templates created before the canvas (the canvas
    # synthesizes a linear layout from `steps` in that case).
    graph: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255), default="New session")
    dataset_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True
    )
    # Cross-turn pipeline state: maps str(source_dataset_id) -> {head_id,
    # head_name, steps}. The "head" is the latest derived dataset a prior turn
    # produced for that source; the next turn SEEDS its working copy from it so
    # a pipeline (去噪 → 检测 → 插值 …) keeps composing across messages instead of
    # resetting every turn. Cleared by /reset-pipeline.
    pipeline_state: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.id"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # user|assistant|tool|system
    content: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
