"""口径版本升级服务：预览 → 单事务执行 → 批次留痕。

设计约束（对应「可追踪的数据升级」）：
1. 预览不改库：列出受影响岗位、已发布报告、将生成的报告。
2. 同一目标版本只允许一个批次：重复执行直接回放既有批次（不新增批次、不抬高报告版本）。
3. 历史基准按规则版本快照保存；升级后旧报告仍可查看，标 review_status=pending_review。
4. 新报告只使用目标规则版本下的有效岗位；人工修正条目在重跑时保留、不被覆盖。
5. 执行全程单事务：任一步失败整体回滚，不留下半成品批次或改了一半的岗位/报告。
"""
from __future__ import annotations

import time
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.constants import error_codes as codes
from src.constants.enums import (
    FUNCTION_LABELS,
    RAW_DUPLICATE,
    RAW_INVALID,
)
from src.models.benchmark import Benchmark
from src.models.posting import Posting
from src.models.raw_posting import RawPosting
from src.models.rule_upgrade import RuleUpgrade
from src.services import audit_service, benchmark_service
from src.services.rule_service import (
    _flags_after,
    _status_after,
    _validate_version,
    active_version,
    apply_version_to_queue,
)
from src.services.salary_parser import parse_salary
from src.services.title_normalizer import normalize_title
from src.utils.cities import normalize_city
from src.utils.errors import AppError

UPGRADE_APPLIED = "applied"


def serialize_upgrade(batch: RuleUpgrade, idempotent: bool = False) -> dict:
    return {
        "id": batch.id,
        "target_version": batch.target_version,
        "previous_version": batch.previous_version,
        "status": batch.status,
        "before_rate": batch.before_rate,
        "after_rate": batch.after_rate,
        "affected_snapshot": batch.affected_snapshot,
        "updated_raws": batch.updated_raws,
        "updated_postings": batch.updated_postings,
        "skipped_corrected": batch.skipped_corrected,
        "benchmarks_marked": batch.benchmarks_marked,
        "reports_created": batch.reports_created,
        "reports_skipped": batch.reports_skipped,
        "actor_email": batch.actor_email,
        "duration_ms": batch.duration_ms,
        "summary": batch.summary,
        "started_at": batch.started_at.isoformat() if batch.started_at else None,
        "finished_at": batch.finished_at.isoformat() if batch.finished_at else None,
        "idempotent": idempotent,
    }


def list_upgrades(db: Session) -> list[dict]:
    rows = db.query(RuleUpgrade).order_by(RuleUpgrade.id.desc()).all()
    return [serialize_upgrade(row) for row in rows]


def get_batch(db: Session, target_version: str) -> RuleUpgrade | None:
    return db.query(RuleUpgrade).filter(RuleUpgrade.target_version == target_version).first()


def _published_reports(db: Session) -> list[Benchmark]:
    return (
        db.query(Benchmark)
        .filter(Benchmark.published.is_(True))
        .order_by(Benchmark.city, Benchmark.function_type, Benchmark.rule_version)
        .all()
    )


def _benchmark_pairs(db: Session) -> list[tuple[str, str]]:
    rows = (
        db.query(Benchmark.city, Benchmark.function_type)
        .distinct()
        .order_by(Benchmark.city, Benchmark.function_type)
        .all()
    )
    return [(city, function_type) for city, function_type in rows]


def _serialize_benchmark_row(row: Benchmark) -> dict:
    data = benchmark_service.serialize(row)
    data["function_label"] = FUNCTION_LABELS.get(row.function_type, row.function_type)
    return data


def _posting_snapshot(posting: Posting, raw: RawPosting) -> dict:
    return {
        "posting_id": posting.id,
        "raw_id": raw.id,
        "title": posting.canonical_title,
        "raw_title": raw.title_raw,
        "salary_raw": raw.salary_raw,
        "city": posting.city,
        "salary_min": posting.salary_min,
        "salary_max": posting.salary_max,
        "salary_median": posting.salary_median,
        "rule_version": posting.rule_version,
        "quality_flags": list(posting.quality_flags or []),
        "raw_status": raw.status,
        "is_corrected": posting.is_corrected,
    }


def _projected_posting(raw: RawPosting, version: str) -> dict:
    salary = parse_salary(raw.salary_raw, version)
    title = normalize_title(raw.title_raw, raw.experience_raw)
    return {
        "title": title.canonical_title,
        "city": normalize_city(raw.city_raw),
        "salary_min": salary.salary_min,
        "salary_max": salary.salary_max,
        "salary_median": salary.salary_median,
        "quality_flags": _flags_after(raw, salary, title.confidence),
        "raw_status": _status_after(
            raw,
            salary.is_hit,
            salary.status == "negotiable",
            title.confidence,
            unparsed=salary.status == "unparsed",
        ),
        "status": salary.status,
        "reason_code": salary.reason_code,
    }


def build_preview(db: Session, version: str) -> dict:
    """只读预览：不改动任何数据，供切换前人工确认。"""
    _validate_version(version)
    previous = active_version(db)
    existing = get_batch(db, version)

    affected: list[dict] = []
    corrected_kept = 0
    for raw, posting in (
        db.query(RawPosting, Posting)
        .join(Posting, Posting.raw_id == RawPosting.id)
        .order_by(RawPosting.id)
        .all()
    ):
        if raw.status in (RAW_DUPLICATE, RAW_INVALID):
            continue
        before = _posting_snapshot(posting, raw)
        if posting.is_corrected:
            corrected_kept += 1
            affected.append(
                {
                    **before,
                    "after": None,
                    "changed": False,
                    "kept_corrected": True,
                }
            )
            continue
        after = _projected_posting(raw, version)
        after["rule_version"] = version
        # 「变化」只看实质结果：薪资数值与质量标记；版本号推进本身不算受影响
        changed = any(
            (
                before["salary_min"] != after["salary_min"],
                before["salary_max"] != after["salary_max"],
                before["salary_median"] != after["salary_median"],
                before["quality_flags"] != after["quality_flags"],
            )
        )
        affected.append({**before, "after": after, "changed": changed, "kept_corrected": False})

    # 受影响 = 解析结果会变的岗位 + 会被保留（不覆盖）的人工修正岗位
    changed_rows = [row for row in affected if row["changed"] or row["kept_corrected"]]
    published = _published_reports(db)
    target_pairs = _benchmark_pairs(db)
    target_existing = [
        _serialize_benchmark_row(row)
        for row in db.query(Benchmark).filter(Benchmark.rule_version == version).all()
    ]

    return {
        "target_version": version,
        "active_version": previous,
        "already_applied": existing is not None,
        "existing_batch": serialize_upgrade(existing) if existing else None,
        "affected_totals": {
            "postings": len(affected),
            "changed": len(changed_rows),
            "kept_corrected": corrected_kept,
        },
        "affected_postings": changed_rows,
        # 旧报告：按规则版本 != 目标版本即视为受口径切换影响
        "reports_to_mark": [
            _serialize_benchmark_row(row)
            for row in db.query(Benchmark)
            .filter(Benchmark.rule_version != version)
            .order_by(Benchmark.city, Benchmark.function_type, Benchmark.rule_version)
            .all()
        ],
        "published_reports": [_serialize_benchmark_row(row) for row in published],
        "reports_to_generate": [
            {
                "city": city,
                "function_type": function_type,
                "function_label": FUNCTION_LABELS.get(function_type, function_type),
            }
            for city, function_type in target_pairs
        ],
        "target_existing_reports": target_existing,
    }


def upgrade(db: Session, version: str, actor, ip: str) -> dict:
    """执行升级：单事务；同一版本幂等回放；失败不落半成品。"""
    _validate_version(version)
    existing = get_batch(db, version)
    if existing is not None:
        # 幂等：不新增批次、不重算、不抬高报告版本
        audit_service.record(
            db, actor, "rule.upgrade.replay", "rule_upgrade", existing.id,
            f"target={version} status={existing.status} (already applied, no-op)", ip,
        )
        db.flush()
        return serialize_upgrade(existing, idempotent=True)

    started = time.perf_counter()
    previous = active_version(db)
    preview = build_preview(db, version)

    batch = RuleUpgrade(
        target_version=version,
        previous_version=previous,
        status=UPGRADE_APPLIED,
        actor_email=actor.email if actor else "system",
        affected_snapshot={
            "affected_totals": preview["affected_totals"],
            "affected_postings": preview["affected_postings"],
            "reports_to_mark": preview["reports_to_mark"],
            "published_reports": preview["published_reports"],
            "reports_to_generate": preview["reports_to_generate"],
        },
        started_at=datetime.utcnow(),
    )
    db.add(batch)
    try:
        db.flush()
    except IntegrityError:
        # 并发重复执行：另一请求已落批次 → 回滚本事务并回放既有批次
        db.rollback()
        existing = get_batch(db, version)
        if existing is None:
            raise
        return serialize_upgrade(existing, idempotent=True)

    # 1) 冻结旧报告明细快照（在重跑改写岗位之前，保证历史报告仍可复现）
    to_mark = (
        db.query(Benchmark)
        .filter(Benchmark.rule_version != version)
        .order_by(Benchmark.id)
        .all()
    )
    for benchmark in to_mark:
        if not benchmark.detail_snapshot:
            benchmark.detail_snapshot = benchmark_service.capture_detail(db, benchmark)
        benchmark.review_status = benchmark_service.REVIEW_PENDING
        benchmark.superseded_by_version = version
        benchmark.upgrade_id = batch.id

    # 2) 重跑全部原始队列（人工修正跳过），并激活目标规则版本
    result = apply_version_to_queue(db, version)

    # 3) 新报告：目标规则版本下逐城市×职能生成快照；已有同版本报告不重复生成、不加版本
    reports_created = 0
    reports_skipped = 0
    for city, function_type in _benchmark_pairs(db):
        already = (
            db.query(Benchmark)
            .filter(
                Benchmark.city == city,
                Benchmark.function_type == function_type,
                Benchmark.rule_version == version,
            )
            .first()
        )
        if already is not None:
            reports_skipped += 1
            continue
        try:
            new_row = benchmark_service.build_snapshot(
                db, city, function_type, version, actor, ip, bump=True
            )
        except AppError as exc:
            if exc.code != codes.CONFLICT:
                raise
            reports_skipped += 1
            continue
        batch_row = db.get(Benchmark, new_row["id"])
        if batch_row is not None:
            batch_row.upgrade_id = batch.id
        reports_created += 1

    # 4) 批次收尾 + 审计
    duration_ms = int((time.perf_counter() - started) * 1000)
    batch.before_rate = result["before"]
    batch.after_rate = result["after"]
    batch.updated_raws = result["updated_raws"]
    batch.updated_postings = result["updated_postings"]
    batch.skipped_corrected = result["skipped_corrected"]
    batch.benchmarks_marked = len(to_mark)
    batch.reports_created = reports_created
    batch.reports_skipped = reports_skipped
    batch.duration_ms = duration_ms
    batch.finished_at = datetime.utcnow()
    batch.summary = (
        f"rule {previous}->{version} hit {result['before']['hits']}/{result['before']['attempts']}"
        f"->{result['after']['hits']}/{result['after']['attempts']}"
        f" postings updated={result['updated_postings']}"
        f" corrected_kept={result['skipped_corrected']}"
        f" old_reports_marked={len(to_mark)} new_reports={reports_created}"
        f" skipped={reports_skipped} duration={duration_ms}ms"
    )
    audit_service.record(
        db, actor, "rule.upgrade", "rule_upgrade", batch.id,
        f"target={version} batch={batch.id} {batch.summary}", ip,
    )
    db.flush()
    return serialize_upgrade(batch)
