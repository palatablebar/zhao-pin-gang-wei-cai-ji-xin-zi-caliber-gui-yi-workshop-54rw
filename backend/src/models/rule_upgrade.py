"""规则升级批次：一次可追踪、可重放（幂等）的口径版本切换记录。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.config.database import Base


class RuleUpgrade(Base):
    __tablename__ = "rule_upgrades"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 同一目标版本只允许一个升级批次：重复执行直接返回既有批次
    target_version: Mapped[str] = mapped_column(String(8), unique=True, nullable=False, index=True)
    previous_version: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="applied", nullable=False)
    before_rate: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_rate: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 切换前的受影响岗位、已发布报告快照（审计可追溯，不随后续重跑漂移）
    affected_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_raws: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_postings: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_corrected: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    benchmarks_marked: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reports_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reports_skipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    actor_email: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
