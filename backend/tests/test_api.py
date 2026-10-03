"""端到端 API 测试：建实验 → 推送批次 → 多次查看 → 越界 → 更正冻结 → 重放。"""

from __future__ import annotations

import pytest


def _create(client, **overrides):
    payload = {
        "name": "落地页改版",
        "baseline_rate": 0.10,
        "target_rate": 0.12,
        "alpha": 0.05,
        "power": 0.80,
    }
    payload.update(overrides)
    r = client.post("/api/experiments", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _batch(client, eid, no, av, ac, bv, bc, expected=200):
    r = client.post(f"/api/experiments/{eid}/batches", json={
        "batch_no": no,
        "group_a_visits": av, "group_a_conv": ac,
        "group_b_visits": bv, "group_b_conv": bc,
    })
    assert r.status_code == expected, r.text
    return r.json()


def _view(client, eid, expected=201):
    r = client.post(f"/api/experiments/{eid}/views", json={"trigger": "manual"})
    assert r.status_code == expected, r.text
    return r.json()


# ---------------------------------------------------------------------------
# 样本量与建实验
# ---------------------------------------------------------------------------

def test_create_experiment_sample_size(client):
    e = _create(client)
    assert e["n_per_group"] == 3841
    assert e["status"] == "running"
    assert e["target_rate"] == pytest.approx(0.12)
    assert e["mde_abs"] == pytest.approx(0.02)


def test_create_experiment_validation_errors(client):
    r = client.post("/api/experiments", json={
        "name": "", "baseline_rate": 1.2, "target_rate": 0.5,
        "alpha": 0, "power": 2,
    })
    assert r.status_code == 422
    errs = r.json()["detail"]["errors"]
    assert set(errs) == {"name", "baseline_rate", "alpha", "power"}


def test_target_equals_baseline_rejected(client):
    r = client.post("/api/experiments", json={
        "name": "x", "baseline_rate": 0.1, "target_rate": 0.1,
        "alpha": 0.05, "power": 0.8,
    })
    assert r.status_code == 422
    assert "target_rate" in r.json()["detail"]["errors"]


def test_batch_validation_errors(client):
    e = _create(client)
    # 转化数大于访问数、负数
    r = client.post(f"/api/experiments/{e['id']}/batches", json={
        "batch_no": 1,
        "group_a_visits": 100, "group_a_conv": 120,
        "group_b_visits": 100, "group_b_conv": -1,
    })
    assert r.status_code == 422
    errs = r.json()["detail"]["errors"]
    assert errs["group_a_conv"] == "A组转化数不能大于访问数"
    assert "group_b_conv" in errs


def test_push_to_nonexistent_experiment(client):
    r = client.post("/api/experiments/expdeadbeef/batches", json={
        "batch_no": 1, "group_a_visits": 10, "group_a_conv": 1,
        "group_b_visits": 10, "group_b_conv": 1,
    })
    assert r.status_code == 422
    assert "experiment_id" in r.json()["detail"]["errors"]


def test_view_without_data_conflicts(client):
    e = _create(client)
    r = client.post(f"/api/experiments/{e['id']}/views", json={})
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# 幂等、更正、批次号
# ---------------------------------------------------------------------------

def test_duplicate_batch_idempotent(client):
    e = _create(client)
    a = _batch(client, e["id"], 7, 100, 10, 100, 8)
    b = _batch(client, e["id"], 7, 100, 10, 100, 8)
    assert a["action"] == "created"
    assert b["action"] == "duplicate_ignored"
    assert b["version"] == 1
    batches = client.get(f"/api/experiments/{e['id']}/batches").json()
    assert len(batches) == 1


def test_correction_records_version(client):
    e = _create(client)
    _batch(client, e["id"], 1, 100, 10, 100, 8)
    corr = _batch(client, e["id"], 1, 100, 12, 100, 8)
    assert corr["action"] == "corrected"
    assert corr["version"] == 2
    assert "更正" in corr["message"]
    versions = client.get(f"/api/experiments/{e['id']}/corrections").json()
    kinds = [(v["batch_no"], v["version"], v["kind"]) for v in versions]
    assert kinds == [(1, 1, "push"), (1, 2, "correction")]
    # 再来一次相同内容 → 幂等忽略，不新增版本
    again = _batch(client, e["id"], 1, 100, 12, 100, 8)
    assert again["action"] == "duplicate_ignored" and again["version"] == 2


# ---------------------------------------------------------------------------
# 多查看边界与 α 记账
# ---------------------------------------------------------------------------

def test_boundaries_and_spending_accounting(client):
    e = _create(client)
    n = e["n_per_group"]
    # 三次查看的信息比例约 0.25 / 0.5 / 1（按累计目标精确补齐），给无效果数据
    cum_sizes = [int(n * 0.25), int(n * 0.50), n]
    views = []
    prev = 0
    for k, cum in enumerate(cum_sizes, start=1):
        size = cum - prev
        _batch(client, e["id"], k, size, int(size * 0.10), size, int(size * 0.10))
        v = _view(client, e["id"])
        views.append(v)
        prev = cum

    # 累计 α 单调不减且不超总 α
    spents = [v["spent_at"] for v in views]
    assert all(spents[i] <= spents[i + 1] + 1e-12 for i in range(2))
    assert spents[-1] == pytest.approx(0.05, abs=1e-9)
    # 边界单调下降，终局贴近固定样本
    bounds = [v["boundary"] for v in views]
    assert bounds[0] > bounds[1] > bounds[2]
    assert abs(bounds[2] - 1.959963984540054) < 0.03
    # 查看序号与 spent_before 衔接
    assert views[0]["spent_before"] == 0.0
    assert views[1]["spent_before"] == pytest.approx(spents[0], abs=1e-12)
    assert all(v["crossed"] is False and v["conclusion"] == "inconclusive"
               for v in views)


def test_invalid_trigger_rejected(client):
    e = _create(client)
    _batch(client, e["id"], 1, 100, 10, 100, 10)
    r = client.post(f"/api/experiments/{e['id']}/views", json={"trigger": "cron"})
    assert r.status_code == 422
    assert "trigger" in r.json()["detail"]["errors"]


def test_scheduled_view_recorded(client):
    e = _create(client)
    _batch(client, e["id"], 1, 500, 50, 500, 55)
    r = client.post(f"/api/experiments/{e['id']}/views", json={"trigger": "scheduled"})
    assert r.status_code == 201 and r.json()["trigger"] == "scheduled"


def test_single_terminal_look_boundary_exact(client):
    e = _create(client)
    n = e["n_per_group"]
    _batch(client, e["id"], 1, n, int(n * 0.10), n, int(n * 0.105))
    v = _view(client, e["id"])
    assert v["boundary"] == pytest.approx(1.959963984540054, abs=1e-9)
    assert v["info_fraction"] == pytest.approx(1.0, abs=1e-9)


def test_information_capped_flag(client):
    e = _create(client)
    n = e["n_per_group"]
    _batch(client, e["id"], 1, n + 500, 100, n + 500, 100)
    v = _view(client, e["id"])
    assert v["capped"] is True
    assert v["info_fraction"] == 1.0
    assert any("按 1 处理" in w for w in v["warnings"])


# ---------------------------------------------------------------------------
# 越界下结论 + 冻结 + 更正不改写历史
# ---------------------------------------------------------------------------

def _push_totals_over_looks(client, eid, n, rate_a, rate_b, n_looks=5):
    """每次推进约 1/n_looks 的样本，返回 views。"""
    views = []
    per = n // n_looks
    for k in range(1, n_looks + 1):
        av = per if k < n_looks else n - per * (n_looks - 1)
        _batch(client, eid, k, av, round(av * rate_a), av, round(av * rate_b))
        views.append(_view(client, eid))
    return views


def test_crossing_concludes_and_freezes(client):
    e = _create(client)
    n = e["n_per_group"]
    views = _push_totals_over_looks(client, e["id"], n, 0.14, 0.10, n_looks=5)
    crossed = [v for v in views if v["crossed"]]
    assert crossed, "14% vs 10% 在计划样本量内应越过某级边界"
    first = crossed[0]
    assert first["conclusion"] == "a_wins"
    assert first["z_value"] > 0

    exp = client.get(f"/api/experiments/{e['id']}").json()
    assert exp["status"] == "stopped"
    assert exp["conclusion"] == "a_wins"
    assert exp["concluded_view_seq"] == first["seq"]


def test_correction_after_freeze_does_not_rewrite(client):
    e = _create(client)
    n = e["n_per_group"]
    # 批次 1 造强效果
    _batch(client, e["id"], 1, n, int(n * 0.15), n, int(n * 0.10))
    v1 = _view(client, e["id"])
    assert v1["crossed"] is True and v1["conclusion"] == "a_wins"
    z1, b1 = v1["z_value"], v1["boundary"]

    # 更正批次 1：把 A 组效果抹掉
    corr = _batch(client, e["id"], 1, n, int(n * 0.10), n, int(n * 0.10))
    assert corr["frozen"] is True
    assert corr["changed_since_latest_view"] is True

    v2 = _view(client, e["id"])
    # 历史结论未改写
    exp = client.get(f"/api/experiments/{e['id']}").json()
    assert exp["conclusion"] == "a_wins"
    # 冻结提示
    assert any("冻结" in w for w in v2["warnings"])
    # 第 1 次查看记录原样
    stored = client.get(f"/api/experiments/{e['id']}/views").json()
    assert stored[0]["z_value"] == pytest.approx(z1, abs=1e-12)
    assert stored[0]["boundary"] == pytest.approx(b1, abs=1e-12)


# ---------------------------------------------------------------------------
# 对称性：两组互换 → z 变号、结论对称
# ---------------------------------------------------------------------------

def test_correction_decrease_keeps_envelope_monotone(client):
    """更正减量让当前累计信息比例低于历史查看点：后续信息时间沿历史
    非递减包络取值，α 不倒流、边界沿用。"""
    e = _create(client)
    n = e["n_per_group"]

    # 查看 1：t≈0.8（单批大量样本）
    big = int(n * 0.8)
    _batch(client, e["id"], 1, big, int(big * 0.105), big, int(big * 0.10))
    v1 = _view(client, e["id"])
    assert 0.79 < v1["info_fraction"] < 0.81

    # 更正批次 1：大幅减量，累计只剩 t≈0.3
    small = int(n * 0.3)
    _batch(client, e["id"], 1, small, int(small * 0.105), small, int(small * 0.10))
    v2 = _view(client, e["id"])

    # 实际信息比例倒退，但使用值沿包络保持 0.8 → 沿用上一边界、不新增 α
    assert v2["info_fraction_raw"] < 0.31
    assert v2["info_fraction"] == pytest.approx(v1["info_fraction"], abs=1e-9)
    assert v2["boundary"] == pytest.approx(v1["boundary"], abs=1e-12)
    assert v2["spent_at"] == pytest.approx(v1["spent_at"], abs=1e-12)

    # 再来新数据推进到 t=1：消耗继续单调增加、不超总 α
    rest = n - small
    _batch(client, e["id"], 2, rest, int(rest * 0.105), rest, int(rest * 0.10))
    v3 = _view(client, e["id"])
    assert v3["info_fraction"] == pytest.approx(1.0, abs=1e-9)
    assert v3["spent_at"] >= v2["spent_at"] - 1e-12
    assert v3["spent_at"] <= 0.05 + 1e-9
    assert v3["boundary"] < v2["boundary"]

    rep = client.post(f"/api/experiments/{e['id']}/replay").json()
    assert rep["all_match"] is True


def test_swap_groups_symmetric(client):
    n = 3841
    e1 = _create(client, name="正向")
    _batch(client, e1["id"], 1, n, int(n * 0.145), n, int(n * 0.10))
    v1 = _view(client, e1["id"])

    e2 = _create(client, name="反向")
    _batch(client, e2["id"], 1, n, int(n * 0.10), n, int(n * 0.145))
    v2 = _view(client, e2["id"])

    assert v1["boundary"] == pytest.approx(v2["boundary"], abs=1e-12)
    assert v1["z_value"] == pytest.approx(-v2["z_value"], abs=1e-12)
    assert v1["conclusion"] == "a_wins" and v2["conclusion"] == "b_wins"


# ---------------------------------------------------------------------------
# 重放
# ---------------------------------------------------------------------------

def test_replay_matches_online_views(client):
    e = _create(client)
    n = e["n_per_group"]
    _batch(client, e["id"], 1, 1000, 95, 1000, 110)
    _view(client, e["id"])
    _batch(client, e["id"], 2, 900, 90, 900, 100)
    _batch(client, e["id"], 2, 900, 88, 900, 100)  # 更正
    _view(client, e["id"])
    _batch(client, e["id"], 3, 2000, 205, 2000, 190)
    _view(client, e["id"])

    r = client.post(f"/api/experiments/{e['id']}/replay")
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["replayed_views"] == 3
    assert rep["all_match"] is True
    for item in rep["views"]:
        assert item["match"] is True


def test_restart_recovers_same_state(client, engine):
    """服务重启 = 引擎重建；所有状态从库恢复，重放仍一致。"""
    e = _create(client)
    n = e["n_per_group"]
    _batch(client, e["id"], 1, 1500, 140, 1500, 160)
    _view(client, e["id"])
    _batch(client, e["id"], 2, n - 1500, int((n - 1500) * 0.10),
           n - 1500, int((n - 1500) * 0.12))
    _view(client, e["id"])

    # 模拟重启：清掉模块级引擎，重新绑定同一数据库
    from app import db as db_module
    db_module._engine = None
    db_module._engine = engine

    views = client.get(f"/api/experiments/{e['id']}/views").json()
    assert len(views) == 2
    rep = client.post(f"/api/experiments/{e['id']}/replay").json()
    assert rep["all_match"] is True
