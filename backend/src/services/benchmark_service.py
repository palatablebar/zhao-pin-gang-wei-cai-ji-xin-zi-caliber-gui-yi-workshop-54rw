"""薪资基准服务：按规则版本快照生成（numpy 线性插值分位）、发布、复核标记、导出 CSV。

口径升级约束：
- 基准是「城市 × 职能 × 规则版本」的唯一快照，切换规则版本不会原地覆盖旧快照；
- 旧快照保留 generated_at 时的分布/职级明细（detail_snapshot），规则重跑后仍可复现；
- 口径升级后旧快照标记 review_status=pending_review（待复核），新快照只取新规则下的
  有效岗位（rule_version=目标版本、无质量标记、有中位数），人工修正条目不被重跑覆盖。
"""
from __future__ import annotations

import csv
import io
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.constants import error_codes as codes
from src.constants.enums import FUNCTION_LABELS, SENIORITY_LABELS
from src.models.benchmark import Benchmark
from src.models.posting import Posting
from src.services import audit_service
from src.services.percentile import distribution, percentiles
from src.utils.errors import AppError

REVIEW_OK = "ok"
REVIEW_PENDING = "pending_review"


def serialize(benchmark: Benchmark) -> dict:
    return {
        "id": benchmark.id,
        "city": benchmark.city,
        "function_type": benchmark.function_type,
        "function_label": FUNCTION_LABELS.get(benchmark.function_type, benchmark.function_type),
        "sample_count": benchmark.sample_count,
        "p25": benchmark.p25,
        "p50": benchmark.p50,
        "p75": benchmark.p75,
        "rule_version": benchmark.rule_version,
        "version": benchmark.version,
        "published": benchmark.published,
        "review_status": benchmark.review_status,
        "superseded_by_version": benchmark.superseded_by_version or "",
        "upgrade_id": benchmark.upgrade_id,
        "generated_at": benchmark.generated_at.isoformat() if benchmark.generated_at else None,
    }


def list_benchmarks(db: Session) -> list[dict]:
    rows = (
        db.query(Benchmark)
        .order_by(Benchmark.city, Benchmark.function_type, Benchmark.rule_version, Benchmark.version)
        .all()
    )
    return [serialize(row) for row in rows]


def _sample_values(db: Session, city: str, function_type: str, rule_version: str) -> list[int]:
    """只取该规则版本下的有效岗位样本。

    有效 = 已解析成功（无质量标记）+ 有月薪中位数。人工修正条目不随重跑被覆盖，
    其口径由修正人决定：只有规则版本仍为当前自动版本时才计入，避免把人为修正与
    目标规则的计算结果混算；若修正发生在旧版本期间，则在旧版本快照里保留。
    """
    rows = (
        db.query(Posting.salary_median)
        .filter(Posting.city == city, Posting.function_type == function_type)
        .filter(Posting.rule_version == rule_version)
        .filter(Posting.salary_median.isnot(None))
        .filter(func.json_length(Posting.quality_flags) == 0)
        .all()
    )
    return sorted(int(row[0]) for row in rows if row[0] is not None)


def _build_detail(db: Session, city: str, function_type: str, rule_version: str,
                  values: list[int]) -> dict:
    rows = (
        db.query(Posting.seniority, Posting.salary_median)
        .filter(Posting.city == city, Posting.function_type == function_type)
        .filter(Posting.rule_version == rule_version)
        .filter(Posting.salary_median.isnot(None))
        .filter(func.json_length(Posting.quality_flags) == 0)
        .all()
    )
    buckets: dict[str, list[int]] = {}
    for seniority, median in rows:
        buckets.setdefault(seniority, []).append(int(median))
    return {
        "distribution": distribution(values),
        "seniority_breakdown": [
            {
                "seniority": seniority,
                "label": SENIORITY_LABELS.get(seniority, seniority),
                "sample_count": len(values_),
                "p50": percentiles(values_)[50] if values_ else 0,
            }
            for seniority, values_ in sorted(buckets.items())
        ],
    }


def capture_detail(db: Session, benchmark: Benchmark) -> dict:
    """按基准自身规则版本重算明细快照（用于升级前冻结旧报告）。"""
    values = _sample_values(db, benchmark.city, benchmark.function_type, benchmark.rule_version)
    detail = _build_detail(db, benchmark.city, benchmark.function_type, benchmark.rule_version, values)
    detail["sample_count"] = len(values)
    detail["p25"], detail["p50"], detail["p75"] = (
        (percentiles(values)[25], percentiles(values)[50], percentiles(values)[75])
        if values else (benchmark.p25, benchmark.p50, benchmark.p75)
    )
    return detail


def generate(db: Session, city: str, function_type: str, actor, ip: str) -> dict:
    from src.services.rule_service import active_version

    rule_version = active_version(db)
    return build_snapshot(db, city, function_type, rule_version, actor, ip, bump=True)


def build_snapshot(db: Session, city: str, function_type: str, rule_version: str, actor, ip: str,
                   bump: bool = True) -> dict:
    """生成/刷新某规则版本下的基准快照。同一版本重复调用只更新该版本快照。"""
    values = _sample_values(db, city, function_type, rule_version)
    pct = percentiles(values)
    if not values or pct is None:
        raise AppError(codes.CONFLICT, "样本不足，无法生成基准", f"{city}/{function_type}/{rule_version}")
    benchmark = (
        db.query(Benchmark)
        .filter(
            Benchmark.city == city,
            Benchmark.function_type == function_type,
            Benchmark.rule_version == rule_version,
        )
        .first()
    )
    created = benchmark is None
    if created:
        benchmark = Benchmark(city=city, function_type=function_type, rule_version=rule_version)
        db.add(benchmark)
        db.flush()
    benchmark.sample_count = len(values)
    benchmark.p25 = pct[25]
    benchmark.p50 = pct[50]
    benchmark.p75 = pct[75]
    # 同一版本内重算才抬高版本号；新快照从 v1 起
    if bump and not created:
        benchmark.version = (benchmark.version or 1) + 1
    else:
        benchmark.version = benchmark.version or 1
    if bump:
        benchmark.generated_at = datetime.utcnow()
        benchmark.review_status = REVIEW_OK
        benchmark.superseded_by_version = ""
    benchmark.detail_snapshot = _build_detail(db, city, function_type, rule_version, values)
    db.flush()
    if bump:
        audit_service.record(
            db, actor, "benchmark.generate", "benchmark", benchmark.id,
            f"{city}/{function_type} rule={rule_version} n={len(values)} "
            f"p25={pct[25]} p50={pct[50]} p75={pct[75]}", ip,
        )
    return serialize(benchmark)


def report(db: Session, benchmark_id: int) -> dict:
    benchmark = db.get(Benchmark, benchmark_id)
    if benchmark is None:
        raise AppError(codes.NOT_FOUND, "基准不存在", f"benchmark_id={benchmark_id}")
    data = serialize(benchmark)
    if benchmark.detail_snapshot:
        data["distribution"] = benchmark.detail_snapshot.get("distribution", [])
        data["seniority_breakdown"] = benchmark.detail_snapshot.get("seniority_breakdown", [])
        return data
    values = _sample_values(db, benchmark.city, benchmark.function_type, benchmark.rule_version)
    detail = _build_detail(db, benchmark.city, benchmark.function_type, benchmark.rule_version, values)
    data["distribution"] = detail["distribution"]
    data["seniority_breakdown"] = detail["seniority_breakdown"]
    return data


def publish(db: Session, benchmark_id: int, actor, ip: str) -> dict:
    benchmark = db.get(Benchmark, benchmark_id)
    if benchmark is None:
        raise AppError(codes.NOT_FOUND, "基准不存在", f"benchmark_id={benchmark_id}")
    benchmark.published = True
    benchmark.review_status = REVIEW_OK
    audit_service.record(
        db, actor, "benchmark.publish", "benchmark", benchmark.id,
        f"{benchmark.city}/{benchmark.function_type} rule={benchmark.rule_version} v{benchmark.version}", ip,
    )
    db.flush()
    return {"id": benchmark.id, "published": benchmark.published}


def export_csv(db: Session, benchmark_id: int) -> str:
    data = report(db, benchmark_id)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "city", "function_type", "sample_count", "p25", "p50", "p75",
        "rule_version", "version", "published", "review_status", "superseded_by_version", "generated_at",
    ])
    writer.writerow([
        data["city"], data["function_type"], data["sample_count"],
        data["p25"], data["p50"], data["p75"], data["rule_version"],
        data["version"], data["published"], data["review_status"],
        data["superseded_by_version"], data["generated_at"],
    ])
    writer.writerow([])
    writer.writerow(["seniority", "sample_count", "p50"])
    for row in data["seniority_breakdown"]:
        writer.writerow([row["seniority"], row["sample_count"], row["p50"]])
    return buffer.getvalue()
