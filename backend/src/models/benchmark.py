"""薪资基准：城市 × 职能 的 P25/P50/P75（按规则版本快照，版本切换不覆盖历史）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.config.database import Base


class Benchmark(Base):
    __tablename__ = "benchmarks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    city: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    function_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    sample_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    p25: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    p50: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    p75: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rule_version: Mapped[str] = mapped_column(String(16), default="v1", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # ok / pending_review：口径升级后旧报告保留可查，但标记待复核
    review_status: Mapped[str] = mapped_column(String(16), default="ok", nullable=False)
    superseded_by_version: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    # 标记它的升级批次（可追踪到 rule_upgrades.id）
    upgrade_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # 生成时的分布/职级拆分快照，保证历史报告在规则切换后仍可复现
    detail_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("city", "function_type", "rule_version", name="uq_benchmark_city_function_rule"),
    )
