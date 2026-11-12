"""口径规则 schema（含版本升级预览/批次）。"""
from __future__ import annotations

from pydantic import BaseModel


class RuleOut(BaseModel):
    id: int
    code: str
    rule_set: str
    version: str
    rule_type: str
    name: str
    pattern: str
    action: str
    description: str
    hit_count: int
    enabled: bool
    is_active_set: bool


class TrialOut(BaseModel):
    version: str
    attempts: int
    hits: int
    misses: int
    hit_rate: float
    hit_rate_pct: int
    reason_breakdown: dict
    rule_hits: dict
    samples: list[dict] = []


class ReparseOut(BaseModel):
    previous_version: str
    active_version: str
    before: dict
    after: dict
    updated_raws: int
    updated_postings: int
    skipped_corrected: int
    duration_ms: int


class ActivateOut(BaseModel):
    version: str
    active: bool
    rules: int


class UpgradeOut(BaseModel):
    id: int
    target_version: str
    previous_version: str
    status: str
    before_rate: dict | None = None
    after_rate: dict | None = None
    affected_snapshot: dict | None = None
    updated_raws: int = 0
    updated_postings: int = 0
    skipped_corrected: int = 0
    benchmarks_marked: int = 0
    reports_created: int = 0
    reports_skipped: int = 0
    actor_email: str = ""
    duration_ms: int = 0
    summary: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    idempotent: bool = False


class UpgradePreviewOut(BaseModel):
    target_version: str
    active_version: str
    already_applied: bool
    existing_batch: UpgradeOut | None = None
    affected_totals: dict
    affected_postings: list[dict] = []
    reports_to_mark: list[dict] = []
    published_reports: list[dict] = []
    reports_to_generate: list[dict] = []
    target_existing_reports: list[dict] = []
