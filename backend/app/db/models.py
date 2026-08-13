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
    # Empty for OIDC-managed users (identity lives at the auth center, no local
    # password). Local email/password users always have a bcrypt hash here.
    password_hash: Mapped[str] = mapped_column(String(255), default="")
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    # Stable cross-product subject from the auth center's id_token (OIDC `sub`).
    # NULL for local accounts; set when a user is provisioned/linked via OIDC.
    oidc_sub: Mapped[Optional[str]] = mapped_column(String(255), unique=True, index=True, default=None)
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
    on subsequent uploads so the user only has to teach RLab Cortex a format
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


class Feedback(Base):
    """An in-the-moment note dropped by a user while using the product — the
    seed of the knowledge flywheel. The whole point is to capture the THOUGHT
    together with the CONTEXT it happened in (which view / conversation /
    dataset / run the user was looking at), so a vague "this was wrong somewhere"
    becomes an actionable, replayable record.

    `kind` splits feedback into the three buckets that route to different fixes
    (don't pour them into one box — they go to different places):
      - "cannot"   能力缺口:想做但做不到      → 需要新工件
      - "wrong"    正确性:它做错了我得手动改  → 真值 / 纠正
      - "distrust" 信任:结果对但我不敢信      → 解释 / 验证 UX
      - "idea"     想法 / 其它

    `status` lets you triage later (new → triaged → done). When this fills up
    with real usage it grows into the 渊-style candidate→review→promote loop.
    """

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="idea", index=True)
    text: Mapped[str] = mapped_column(Text, default="")

    # Context the note was dropped in. The ids are stored WITHOUT FK constraints
    # on purpose: a referenced conversation/dataset/run may later be deleted, but
    # the feedback (and the fact it pointed at id N) must survive regardless.
    view: Mapped[str] = mapped_column(String(32), default="")  # chat|datasets|algorithms|...
    conversation_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    dataset_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    run_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    context: Mapped[dict] = mapped_column(JSON, default=dict)  # url, ua, anything extra

    # An optional screenshot of exactly what the user was looking at — for "this
    # part, what does it mean?" the picture pins the referent far better than
    # words. Stored as a file under <upload>/feedback/; this holds its path.
    screenshot: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    status: Mapped[str] = mapped_column(String(16), default="new", index=True)  # new|triaged|done
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class MappingRule(Base):
    """Sedimented EXPERT JUDGMENT about what a column MEANS — the first carrier
    of the "judgment layer" of domain knowledge.

    A correction the expert makes ("this `U(V)` column is voltage") is promoted
    into one of these rules. Thereafter the system CONSULTS these rules at
    decision time (dataset profiling / column picking) and applies the expert's
    meaning automatically — so the next (non-expert) user gets it for free. That
    consult-before-decide step is the whole point: a rule that's stored but never
    read back changes nothing.

    `is_public` defaults True because inheritance across users IS the value:
    one expert correction → everyone benefits.
    """

    __tablename__ = "mapping_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    # What to match a column name against, and how.
    pattern: Mapped[str] = mapped_column(String(255), index=True)  # e.g. "U(V)"
    match_type: Mapped[str] = mapped_column(String(16), default="normalized")  # normalized|exact|contains|regex

    # The meaning to assign when it matches.
    role: Mapped[str] = mapped_column(String(64))                  # e.g. "voltage" (machine key)
    label: Mapped[str] = mapped_column(String(120), default="")    # e.g. "电压 Voltage" (display)
    note: Mapped[str] = mapped_column(Text, default="")

    # Provenance + sharing.
    source: Mapped[str] = mapped_column(String(16), default="manual")  # feedback|manual
    feedback_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    hit_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# ══════════════════════════════════════════════════════════════════════════
#  Wind-tunnel quality-check domain
# ══════════════════════════════════════════════════════════════════════════
class WtBatch(Base):
    """One import + check session — a set of 车次 uploaded together.

    Runs are batched rather than stored individually because two of the most
    valuable checks are inherently cross-run: 天平零飘 compares against the
    previous run, and the trend view needs the whole sequence. A per-file model
    would have made both of those bolt-ons.
    """

    __tablename__ = "wt_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    #: Directory under <upload>/windtunnel/ holding the raw ca/pa/da files.
    storage_dir: Mapped[str] = mapped_column(String(1024), default="")
    #: [{run_no, files:{ca,pa,da}, meta:{…}}, …]
    runs: Mapped[list] = mapped_column(JSON, default=list)
    #: The 车次表 (test plan) if one was uploaded with the batch. Holds what was
    #: SUPPOSED to be flown — the only way to see a condition that is missing.
    plan: Mapped[dict] = mapped_column(JSON, default=dict)
    #: CheckConfig as saved by the user.
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    #: BatchResult.to_dict() from the last successful check.
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="new")  # new|checked|error
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class WtRule(Base):
    """A quality rule as DATA — the whole point of the design.

    Shipped rules are seeded here on first use so a user can edit a threshold
    the same way they edit one of their own. ``source`` records where it came
    from (builtin / user / ai) and ``builtin_id`` lets a modified shipped rule
    still be traced back to the original.
    """

    __tablename__ = "wt_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    rule_id: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(255))
    feature: Mapped[str] = mapped_column(String(120), index=True)
    object_name: Mapped[str] = mapped_column(String(255), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    applies_when_mach: Mapped[str] = mapped_column(String(32), default="")
    bands: Mapped[list] = mapped_column(JSON, default=list)
    refs: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String(16), default="user")  # builtin|user|ai
    builtin_id: Mapped[str] = mapped_column(String(120), default="")
    #: Free-text audit trail of who changed what and why.
    changelog: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class WtBalance(Base):
    """A balance's rated ranges — required by the overload check and available
    nowhere in a run's own files."""

    __tablename__ = "wt_balances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    ranges: Mapped[dict] = mapped_column(JSON, default=dict)  # {My,Z,Mz,Y,Mx,Q}
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class WtReport(Base):
    """A generated report — kept editable, because the spec requires the
    preview to be edited before export and the edit must survive."""

    __tablename__ = "wt_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    batch_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("wt_batches.id", ondelete="CASCADE"), nullable=True, index=True
    )
    run_no: Mapped[str] = mapped_column(String(64), default="")
    kind: Mapped[str] = mapped_column(String(16), default="report")  # report|shift|summary
    title: Mapped[str] = mapped_column(String(255), default="")
    sections: Mapped[list] = mapped_column(JSON, default=list)
    #: Markdown as generated — kept so a user can revert their edits.
    content: Mapped[str] = mapped_column(Text, default="")
    #: Markdown after the user edited the preview. Empty until they touch it.
    edited: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
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
