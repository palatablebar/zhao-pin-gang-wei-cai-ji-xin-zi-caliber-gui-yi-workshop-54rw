"""rule upgrade batches + versioned benchmark snapshots

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-12

背景：历史基准已对外发布。口径 v1→v2 切换必须以「批次」为单位可追踪、可幂等重放，
且旧报告保留可查（标待复核）、新报告按新规则版本独立快照，不能原地覆盖。

变更：
1. 新表 rule_upgrades（target_version 唯一 → 同一版本只允许一个批次）。
2. benchmarks 增加 review_status / superseded_by_version / upgrade_id / detail_snapshot。
3. 历史基准按 rule_version 拆分快照：同一 city×function×rule_version 唯一；
   既有行全部保留（不会因加唯一约束而被覆盖），仅补默认值。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "rule_upgrades" not in inspector.get_table_names():
        op.create_table(
            "rule_upgrades",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("target_version", sa.String(8), nullable=False),
            sa.Column("previous_version", sa.String(8), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="applied"),
            sa.Column("before_rate", sa.JSON(), nullable=True),
            sa.Column("after_rate", sa.JSON(), nullable=True),
            sa.Column("affected_snapshot", sa.JSON(), nullable=True),
            sa.Column("updated_raws", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_postings", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("skipped_corrected", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("benchmarks_marked", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("reports_created", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("reports_skipped", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("actor_email", sa.String(160), nullable=False, server_default=""),
            sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("target_version", name="uq_rule_upgrades_target_version"),
        )
        op.create_index("ix_rule_upgrades_target_version", "rule_upgrades", ["target_version"])

    benchmark_cols = {col["name"] for col in inspector.get_columns("benchmarks")}
    if "review_status" not in benchmark_cols:
        op.add_column(
            "benchmarks",
            sa.Column("review_status", sa.String(16), nullable=False, server_default="ok"),
        )
    if "superseded_by_version" not in benchmark_cols:
        op.add_column(
            "benchmarks",
            sa.Column("superseded_by_version", sa.String(16), nullable=False, server_default=""),
        )
    if "upgrade_id" not in benchmark_cols:
        op.add_column("benchmarks", sa.Column("upgrade_id", sa.Integer(), nullable=True))
        op.create_index("ix_benchmarks_upgrade_id", "benchmarks", ["upgrade_id"])
    if "detail_snapshot" not in benchmark_cols:
        op.add_column("benchmarks", sa.Column("detail_snapshot", sa.JSON(), nullable=True))

    existing_constraints = {
        c["name"] for c in inspector.get_unique_constraints("benchmarks")
    }
    if "uq_benchmark_city_function_rule" not in existing_constraints:
        op.create_unique_constraint(
            "uq_benchmark_city_function_rule",
            "benchmarks",
            ["city", "function_type", "rule_version"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    constraints = {c["name"] for c in inspector.get_unique_constraints("benchmarks")}
    if "uq_benchmark_city_function_rule" in constraints:
        op.drop_constraint("uq_benchmark_city_function_rule", "benchmarks", type_="unique")

    benchmark_cols = {col["name"] for col in inspector.get_columns("benchmarks")}
    if "detail_snapshot" in benchmark_cols:
        op.drop_column("benchmarks", "detail_snapshot")
    if "upgrade_id" in benchmark_cols:
        indexes = {i["name"] for i in inspector.get_indexes("benchmarks")}
        if "ix_benchmarks_upgrade_id" in indexes:
            op.drop_index("ix_benchmarks_upgrade_id", table_name="benchmarks")
        op.drop_column("benchmarks", "upgrade_id")
    if "superseded_by_version" in benchmark_cols:
        op.drop_column("benchmarks", "superseded_by_version")
    if "review_status" in benchmark_cols:
        op.drop_column("benchmarks", "review_status")

    if "rule_upgrades" in inspector.get_table_names():
        op.drop_table("rule_upgrades")
