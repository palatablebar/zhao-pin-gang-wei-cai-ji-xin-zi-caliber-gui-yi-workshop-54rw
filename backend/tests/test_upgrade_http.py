"""HTTP 层验证：升级预览/执行/幂等，旧报告仍可读且标待复核。"""
from __future__ import annotations

import json
import os
import tempfile

os.environ.setdefault("SEED_DEMO", "false")

import pytest  # noqa: E402


@pytest.fixture()
def client():
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker

    db_path = os.path.join(tempfile.mkdtemp(prefix="jobnorm-http-"), "test.db")
    engine = create_engine(f"sqlite:///{db_path}", future=True)

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

    seed_all()

    from fastapi.testclient import TestClient
    from src.config.app import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


def _login(client, email="admin@jobnorm.io"):
    res = client.post("/api/auth/login", json={"email": email, "password": "Demo@2026"})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_upgrade_http_flow(client):
    headers = _login(client)

    preview = client.get("/api/rules/v2/upgrade/preview", headers=headers)
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["already_applied"] is False
    assert body["affected_totals"]["postings"] > 0
    assert body["published_reports"]
    old_published_ids = [row["id"] for row in body["published_reports"]]
    assert old_published_ids

    # 发布前先记录旧报告内容
    old_report = client.get(f"/api/benchmarks/{old_published_ids[0]}", headers=headers).json()

    run = client.post("/api/rules/v2/upgrade", headers=headers)
    assert run.status_code == 200, run.text
    batch = run.json()
    assert batch["status"] == "applied"
    assert batch["idempotent"] is False
    assert batch["reports_created"] >= 1

    # 旧报告仍可读，标待复核，数值/分布不变
    old_after = client.get(f"/api/benchmarks/{old_report['id']}", headers=headers)
    assert old_after.status_code == 200
    old_data = old_after.json()
    assert old_data["review_status"] == "pending_review"
    assert old_data["superseded_by_version"] == "v2"
    assert old_data["p50"] == old_report["p50"]
    assert old_data["distribution"] == old_report["distribution"]

    # 重复执行同一版本：不新增批次、不抬高报告版本
    versions_before = {
        row["id"]: row["version"] for row in client.get("/api/benchmarks", headers=headers).json()
    }
    again = client.post("/api/rules/v2/upgrade", headers=headers)
    assert again.status_code == 200, again.text
    again_body = again.json()
    assert again_body["idempotent"] is True
    assert again_body["id"] == batch["id"]
    versions_after = {
        row["id"]: row["version"] for row in client.get("/api/benchmarks", headers=headers).json()
    }
    assert versions_after == versions_before

    batches = client.get("/api/rules/upgrades", headers=headers).json()
    assert len(batches) == 1

    # 直接跨版本 reparse 被拦截（必须走升级流程）
    reparse = client.post("/api/rules/v1/reparse", headers=headers)
    assert reparse.status_code == 409
    assert "upgrade" in reparse.json()["detail"]

    # 同版本重跑仍允许
    same = client.post("/api/rules/v2/reparse", headers=headers)
    assert same.status_code == 200, same.text


def test_client_role_cannot_upgrade(client):
    headers = _login(client, "client@jobnorm.io")
    res = client.post("/api/rules/v2/upgrade", headers=headers)
    assert res.status_code == 403
