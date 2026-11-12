"""本地端到端验证：SQLite + MySQL JSON 函数兼容层，覆盖升级预览/幂等/回滚/旧报告可查。

仅用于开发机验证（线上是 MySQL 8.0）。运行：
  PYTHONPATH=backend python3 -m pytest backend/tests/test_upgrade_flow.py -q
"""
from __future__ import annotations

import json
import os

os.environ.setdefault("SEED_DEMO", "false")

import pytest
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///{path}".format(path=":memory:"), future=True)

    @event.listens_for(engine, "connect")
    def _register_functions(dbapi_connection, _):
        dbapi_connection.create_function(
            "json_length", 1, lambda value: len(json.loads(value)) if value else 0
        )

        def json_contains(value, needle):
            data = json.loads(value) if value else []
            return 1 if json.loads(needle) in data else 0

        dbapi_connection.create_function("json_contains", 2, json_contains)

    import src.config.database as database

    database.engine = engine
    database.SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    import src.models  # noqa: F401  # 注册全部表到 metadata
    from src.config.database import Base

    Base.metadata.create_all(bind=engine)

    from scripts.seed_demo import seed_all

    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    # seed 用 session_scope → SessionLocal（已替换）
    seed_all()
    yield session
    session.close()


def _admin(db):
    from src.models.user import User

    return db.query(User).filter(User.email == "admin@jobnorm.io").first()


def test_preview_is_read_only_and_lists_impact(db):
    from src.services import upgrade_service
    from src.models.posting import Posting
    from src.models.benchmark import Benchmark
    from src.services.rule_service import active_version

    before_active = active_version(db)
    before_postings = {p.id: p.salary_median for p in db.query(Posting).all()}
    before_benchmarks = {b.id: (b.rule_version, b.review_status, b.version)
                         for b in db.query(Benchmark).all()}

    preview = upgrade_service.build_preview(db, "v2")

    assert preview["active_version"] == before_active == "v1"
    assert preview["already_applied"] is False
    assert preview["affected_totals"]["changed"] > 0
    assert preview["affected_totals"]["kept_corrected"] >= 0
    assert {row["city"] for row in preview["published_reports"]} >= {"上海", "北京"}
    assert preview["reports_to_mark"], "应列出会被标记待复核的旧报告"
    assert preview["reports_to_generate"], "应列出将生成的杭州/backend 等快照"
    # 只读：库内不变
    assert {p.id: p.salary_median for p in db.query(Posting).all()} == before_postings
    assert {b.id: (b.rule_version, b.review_status, b.version) for b in db.query(Benchmark).all()} \
        == before_benchmarks


def test_upgrade_marks_old_reports_keeps_readable_and_creates_new_snapshots(db):
    from src.services import upgrade_service, benchmark_service
    from src.models.benchmark import Benchmark
    from src.models.rule_upgrade import RuleUpgrade
    from src.services.rule_service import active_version

    admin = _admin(db)
    old_rows = db.query(Benchmark).filter(Benchmark.rule_version == "v1").all()
    assert old_rows

    result = upgrade_service.upgrade(db, "v2", admin, "127.0.0.1")
    db.commit()

    assert result["status"] == "applied"
    assert result["idempotent"] is False
    assert active_version(db) == "v2"
    batch = db.query(RuleUpgrade).one()
    assert batch.target_version == "v2"
    assert batch.reports_created >= 1
    assert batch.benchmarks_marked == len(old_rows)

    # 旧报告：仍可查看，标待复核，数值不变
    for row in db.query(Benchmark).filter(Benchmark.rule_version == "v1").all():
        assert row.review_status == "pending_review"
        assert row.superseded_by_version == "v2"
        assert row.upgrade_id == batch.id
        assert row.detail_snapshot is not None
        data = benchmark_service.report(db, row.id)
        assert data["review_status"] == "pending_review"
        assert data["p50"] == row.p50
        assert data["distribution"], "历史报告要能继续展示分布"

    # 新报告：目标版本独立快照，不与旧行同 id/覆盖
    new_rows = db.query(Benchmark).filter(Benchmark.rule_version == "v2").all()
    assert new_rows
    assert {r.id for r in new_rows}.isdisjoint({r.id for r in old_rows})


def test_new_report_only_counts_target_version_valid_postings(db):
    """新报告只用目标规则版本下的有效岗位；人工修正保留且计入新版本。"""
    from sqlalchemy import func
    from src.services import upgrade_service, benchmark_service, posting_service
    from src.models.benchmark import Benchmark
    from src.models.posting import Posting

    # 1) 先人工修正一条干净岗位（模拟分析师在切版本前修过数）
    clean = (
        db.query(Posting)
        .filter(Posting.city == "杭州", Posting.function_type == "backend")
        .filter(func.json_length(Posting.quality_flags) == 0)
        .filter(Posting.is_corrected.is_(False))
        .first()
    )
    assert clean is not None
    admin = _admin(db)
    posting_service.correct_posting(
        db, clean.id, {"salary_min": 21000, "salary_max": 21000, "note": "人工校准"}, admin, ""
    )
    db.commit()

    # 2) 预览应提示这条岗位会被保留、不覆盖
    preview = upgrade_service.build_preview(db, "v2")
    kept = [row for row in preview["affected_postings"] if row["kept_corrected"]]
    assert any(row["posting_id"] == clean.id for row in kept)

    # 3) 执行升级
    upgrade_service.upgrade(db, "v2", admin, "127.0.0.1")
    db.commit()

    # 4) 修正值原样保留、口径版本随批次推进
    db.refresh(clean)
    assert clean.is_corrected is True
    assert clean.salary_median == 21000, "人工修正值不能被重跑覆盖"
    assert clean.rule_version == "v2", "修正条目应保留在新规则版本下，而非被静默丢弃"

    # 5) 新报告样本 = 该版本全部有效岗位（含保留的修正条目），不含旧版本岗位
    city, function = "杭州", "backend"
    new_row = (
        db.query(Benchmark)
        .filter_by(city=city, function_type=function, rule_version="v2")
        .one()
    )
    values_v2 = benchmark_service._sample_values(db, city, function, "v2")
    assert new_row.sample_count == len(values_v2)
    assert 21000 in values_v2
    # 旧版本行仍存在且独立
    assert (
        db.query(Benchmark)
        .filter_by(city=city, function_type=function, rule_version="v1")
        .one()
        .id
        != new_row.id
    )

def test_upgrade_is_idempotent(db):
    from src.services import upgrade_service
    from src.models.benchmark import Benchmark
    from src.models.rule_upgrade import RuleUpgrade
    from src.models.audit_log import AuditLog

    admin = _admin(db)
    first = upgrade_service.upgrade(db, "v2", admin, "127.0.0.1")
    db.commit()
    versions_after_first = {
        (b.city, b.function_type, b.rule_version): b.version for b in db.query(Benchmark).all()
    }
    batches_after_first = db.query(RuleUpgrade).count()
    audits_after_first = db.query(AuditLog).count()

    second = upgrade_service.upgrade(db, "v2", admin, "127.0.0.1")
    db.commit()

    assert second["idempotent"] is True
    assert second["id"] == first["id"]
    assert db.query(RuleUpgrade).count() == batches_after_first, "重复执行不新增批次"
    assert {
        (b.city, b.function_type, b.rule_version): b.version for b in db.query(Benchmark).all()
    } == versions_after_first, "重复执行不抬高报告版本"
    # 只多一条 replay 审计，不重新写业务变更审计
    assert db.query(AuditLog).count() == audits_after_first + 1


def test_upgrade_rolls_back_on_failure(db, monkeypatch):
    from src.services import upgrade_service, benchmark_service
    from src.services.rule_service import active_version
    from src.models.benchmark import Benchmark
    from src.models.rule_upgrade import RuleUpgrade
    from src.models.posting import Posting
    from src.models.raw_posting import RawPosting
    from src.models.parse_rule import ParseRule

    admin = _admin(db)
    snapshot = {
        "active": active_version(db),
        "postings": {(p.id, p.rule_version, p.salary_median) for p in db.query(Posting).all()},
        "raws": {(r.id, r.rule_version, r.status) for r in db.query(RawPosting).all()},
        "benchmarks": {(b.id, b.rule_version, b.review_status, b.version, b.p50)
                       for b in db.query(Benchmark).all()},
        "rules": {(r.id, r.is_active_set) for r in db.query(ParseRule).all()},
        "upgrades": db.query(RuleUpgrade).count(),
    }

    original = benchmark_service.build_snapshot

    def boom(*args, **kwargs):
        raise RuntimeError("simulated failure mid-upgrade")

    monkeypatch.setattr(upgrade_service.benchmark_service, "build_snapshot", boom)
    with pytest.raises(RuntimeError):
        upgrade_service.upgrade(db, "v2", admin, "127.0.0.1")
    db.rollback()
    monkeypatch.setattr(upgrade_service.benchmark_service, "build_snapshot", original)

    assert active_version(db) == snapshot["active"]
    assert {(p.id, p.rule_version, p.salary_median) for p in db.query(Posting).all()} \
        == snapshot["postings"]
    assert {(r.id, r.rule_version, r.status) for r in db.query(RawPosting).all()} \
        == snapshot["raws"]
    assert {(b.id, b.rule_version, b.review_status, b.version, b.p50)
            for b in db.query(Benchmark).all()} == snapshot["benchmarks"]
    assert {(r.id, r.is_active_set) for r in db.query(ParseRule).all()} == snapshot["rules"]
    assert db.query(RuleUpgrade).count() == snapshot["upgrades"], "失败不留下半成品批次"


def test_activate_cannot_change_active_version(db):
    from src.services import rule_service
    from src.constants import error_codes as codes
    from src.utils.errors import AppError

    with pytest.raises(AppError) as exc:
        rule_service.activate(db, "v2", _admin(db), "127.0.0.1")
    assert exc.value.code == codes.CONFLICT

    # 同版本激活仍是幂等的无操作
    assert rule_service.activate(db, "v1", _admin(db), "127.0.0.1")["active"] is True


def test_reparse_cannot_change_active_version(db):
    from src.services import rule_service
    from src.constants import error_codes as codes
    from src.utils.errors import AppError

    with pytest.raises(AppError) as exc:
        rule_service.reparse(db, "v2", _admin(db), "127.0.0.1")
    assert exc.value.code == codes.CONFLICT
    assert "upgrade" in exc.value.detail
