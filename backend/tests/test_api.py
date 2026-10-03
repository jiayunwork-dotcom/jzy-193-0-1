"""API 层集成测试：建实验、样本量、批次幂等/更正、查看、冻结、重放、对称性、校验。"""

from __future__ import annotations

from app import stats


# ----------------------------- 建实验/样本量 -------------------------------- #


def test_create_experiment_returns_3841(make_experiment):
    e = make_experiment()
    assert e["planned_n_per_group"] == 3841
    assert e["min_effect_abs"] == 0.02 or abs(e["min_effect_abs"] - 0.02) < 1e-12
    assert e["freeze_past_looks"] is True


def test_create_experiment_validation_errors(client):
    bad = [
        ({"baseline_rate": 1.0, "target_rate": 0.12}, "baseline_rate"),
        ({"baseline_rate": -0.1, "target_rate": 0.12}, "baseline_rate"),
        ({"baseline_rate": 0.1, "target_rate": 2}, "target_rate"),
        ({"baseline_rate": 0.1, "target_rate": 0.1}, "target_rate"),
        ({"baseline_rate": 0.1, "target_rate": 0.12, "alpha": 0}, "alpha"),
        ({"baseline_rate": 0.1, "target_rate": 0.12, "alpha": 1}, "alpha"),
        ({"baseline_rate": 0.1, "target_rate": 0.12, "power": 0}, "power"),
        ({"baseline_rate": 0.1, "target_rate": 0.12, "power": 1.5}, "power"),
    ]
    for body, field in bad:
        payload = {"name": "x", "baseline_rate": 0.1, "target_rate": 0.12,
                   "alpha": 0.05, "power": 0.8}
        payload.update(body)
        r = client.post("/api/experiments", json=payload)
        assert r.status_code == 422, (body, r.text)
        fields = {f["field"] for f in r.json()["fields"]}
        assert field in fields, (body, fields)


def test_push_to_nonexistent_experiment_404(client):
    r = client.post("/api/experiments/9999/batches", json={
        "batch_no": 1, "control_visits": 10, "control_conversions": 1,
        "treatment_visits": 10, "treatment_conversions": 1})
    assert r.status_code == 404


# ------------------------------- 批次校验 ----------------------------------- #


def _batch(client, eid, no, cv, cc, tv, tc, **kw):
    return client.post(f"/api/experiments/{eid}/batches", json={
        "batch_no": no, "control_visits": cv, "control_conversions": cc,
        "treatment_visits": tv, "treatment_conversions": tc, **kw})


def test_batch_field_validation(make_experiment, client):
    e = make_experiment()
    eid = e["id"]
    assert _batch(client, eid, 1, 10, 11, 10, 1).status_code == 422  # 转化>访问
    assert _batch(client, eid, 2, 10, -1, 10, 1).status_code == 422  # 负数
    assert _batch(client, eid, 3, -1, 0, 10, 1).status_code == 422
    r = _batch(client, eid, 4, 10, 11, 10, 12)
    fields = {f["field"] for f in r.json()["fields"]}
    assert fields == {"control_conversions", "treatment_conversions"}


def test_duplicate_batch_idempotent(make_experiment, client):
    e = make_experiment()
    eid = e["id"]
    r1 = _batch(client, eid, 7, 100, 10, 100, 12)
    r2 = _batch(client, eid, 7, 100, 10, 100, 12)
    assert r1.status_code == 200 and r1.json()["status"] == "insert"
    assert r2.status_code == 200 and r2.json()["status"] == "duplicate_ignored"
    batches = client.get(f"/api/experiments/{eid}/batches").json()
    assert len(batches) == 1
    totals = client.get(f"/api/experiments/{eid}").json()
    assert totals["control_visits"] == 100 and totals["treatment_visits"] == 100


def test_conflicting_batch_without_correction_rejected(make_experiment, client):
    e = make_experiment()
    eid = e["id"]
    _batch(client, eid, 1, 100, 10, 100, 12)
    r = _batch(client, eid, 1, 100, 9, 100, 12)
    assert r.status_code == 409
    assert "is_correction" in {f["field"] for f in r.json()["fields"]}
    # 旧值保留
    b = client.get(f"/api/experiments/{eid}/batches").json()[0]
    assert b["control_conversions"] == 10


def test_correction_updates_value_and_flags(make_experiment, client):
    e = make_experiment()
    eid = e["id"]
    _batch(client, eid, 1, 1000, 100, 1000, 120)
    r = _batch(client, eid, 1, 1000, 80, 1000, 120, is_correction=True)
    assert r.status_code == 200
    assert r.json()["status"] == "correction"
    assert r.json()["batch"]["correction_count"] == 1
    events = client.get(f"/api/experiments/{eid}/events").json()
    kinds = [x["event_type"] for x in events]
    assert kinds == ["insert", "correction"]
    corr = events[1]
    assert corr["prior_control_conversions"] == 100
    assert corr["control_conversions"] == 80


def test_correction_nonexistent_batch_rejected(make_experiment, client):
    e = make_experiment()
    r = _batch(client, e, 1, 100, 10, 100, 12, is_correction=True) if False else \
        client.post(f"/api/experiments/{e['id']}/batches", json={
            "batch_no": 9, "control_visits": 1, "control_conversions": 0,
            "treatment_visits": 1, "treatment_conversions": 0,
            "is_correction": True})
    assert r.status_code == 409


# ------------------------------- 查看流程 ----------------------------------- #


def test_single_look_at_full_info_boundary_195996(make_experiment, client):
    e = make_experiment()
    eid = e["id"]
    # 一次推到计划样本，转化率相同 -> Z≈0，不显著
    _batch(client, eid, 1, 3841, 384, 3841, 384)
    r = client.post(f"/api/experiments/{eid}/looks", json={"trigger": "manual"})
    assert r.status_code == 200
    look = r.json()["look"]
    assert look["boundary"] == 1.959963984540054  # 仅在 t=1 查看一次
    assert look["info_time"] == 1.0
    assert look["decision"] == "continue"


def test_early_look_conservative_boundary(make_experiment, client):
    e = make_experiment()
    eid = e["id"]
    _batch(client, eid, 1, 1920, 192, 1920, 230)
    r = client.post(f"/api/experiments/{eid}/looks").json()
    assert r["look"]["boundary"] > 2.7  # t≈0.5 首次查看约 2.77
    assert r["look"]["info_time"] < 1.0


def test_look_with_no_samples_rejected(make_experiment, client):
    e = make_experiment()
    r = client.post(f"/api/experiments/{e['id']}/looks")
    assert r.status_code == 409


def test_repeat_look_without_new_events_rejected(make_experiment, client):
    e = make_experiment()
    eid = e["id"]
    _batch(client, eid, 1, 1000, 100, 1000, 100)
    assert client.post(f"/api/experiments/{eid}/looks").status_code == 200
    r = client.post(f"/api/experiments/{eid}/looks")
    assert r.status_code == 409


def test_crossing_boundary_concludes(make_experiment, client):
    e = make_experiment()
    eid = e["id"]
    # 在 t=0.5 给出极大差异（远超 ~2.77）
    _batch(client, eid, 1, 1920, 100, 1920, 300)
    r = client.post(f"/api/experiments/{eid}/looks").json()
    assert r["look"]["decision"] == "reject"
    assert r["look"]["z_stat"] > r["look"]["boundary"]
    exp = client.get(f"/api/experiments/{eid}").json()
    assert exp["concluded"] is True
    # 冻结策略：无新事件时重复查看被拒绝
    r_dup = client.post(f"/api/experiments/{eid}/looks")
    assert r_dup.status_code == 409
    # 但有更正/新数据时仍可继续查看（历史结论冻结，可能出现"证据反转"提示）
    _batch(client, eid, 1, 1920, 100, 1920, 120, is_correction=True)
    r_after = client.post(f"/api/experiments/{eid}/looks")
    assert r_after.status_code == 200
    if r_after.json()["look"]["decision"] == "continue":
        assert "不再支持" in (r_after.json().get("correction_warning") or "")


def test_info_time_clipped_flag(make_experiment, client):
    e = make_experiment()
    eid = e["id"]
    _batch(client, eid, 1, 5000, 500, 5000, 600)
    look = client.post(f"/api/experiments/{eid}/looks").json()["look"]
    assert look["raw_info_time"] > 1.0
    assert look["info_time"] == 1.0
    assert look["clipped"] is True


# ------------------------- 冻结 + 更正不改变历史 ---------------------------- #


def test_frozen_history_after_correction(make_experiment, client):
    e = make_experiment()
    eid = e["id"]
    _batch(client, eid, 1, 2000, 200, 2000, 240)
    first = client.post(f"/api/experiments/{eid}/looks").json()["look"]
    # 更正批次 1（把实验组转化数改小，结论可能翻转）
    _batch(client, eid, 1, 2000, 200, 2000, 150, is_correction=True)
    second = client.post(f"/api/experiments/{eid}/looks").json()
    assert second["correction_warning"] is not None
    # 历史快照保持原值
    looks = client.get(f"/api/experiments/{eid}/looks").json()
    assert looks[0]["z_stat"] == first["z_stat"]
    assert looks[0]["boundary"] == first["boundary"]
    assert looks[0]["decision"] == first["decision"]
    assert looks[1]["correction_since_last"] is True
    # 新查看使用新数据
    assert looks[1]["treatment_conversions"] == 150
    assert looks[1]["z_stat"] < looks[0]["z_stat"]


def test_correction_regressing_info_time_is_clamped(make_experiment, client):
    e = make_experiment()
    eid = e["id"]
    _batch(client, eid, 1, 3000, 300, 3000, 330)
    first = client.post(f"/api/experiments/{eid}/looks").json()["look"]
    assert first["decision"] == "continue"
    # 更正使样本大幅减少（信息时间倒退）；更正本身是新事件，允许立刻再查看
    _batch(client, eid, 1, 1000, 100, 1000, 120, is_correction=True)
    r = client.post(f"/api/experiments/{eid}/looks").json()
    look2 = r["look"]
    assert look2["raw_info_time"] < first["info_time"]
    assert look2["info_time"] == first["info_time"]  # 夹到上次值，单调不减
    assert look2["clipped"] is True
    assert "倒退" in r["correction_warning"]
    # 再推新数据后正常增长（总量控制在计划样本以内，避免 t>1 的另一种 clipped）
    _batch(client, eid, 2, 2200, 220, 2200, 240)
    look3 = client.post(f"/api/experiments/{eid}/looks").json()["look"]
    assert look3["raw_info_time"] > first["info_time"]
    assert look3["raw_info_time"] < 1.0
    assert look3["clipped"] is False


# ------------------------------- 对称性 ------------------------------------- #


def test_swap_groups_flips_z_and_decision(make_experiment, client):
    e = make_experiment()
    eid = e["id"]
    # 原始：treatment 更好
    _batch(client, eid, 1, 1920, 150, 1920, 300)
    r1 = client.post(f"/api/experiments/{eid}/looks").json()["look"]

    e2 = make_experiment(name="互换实验")
    eid2 = e2["id"]
    _batch(client, eid2, 1, 1920, 300, 1920, 150)
    r2 = client.post(f"/api/experiments/{eid2}/looks").json()["look"]

    assert r1["z_stat"] == -r2["z_stat"]
    assert r1["boundary"] == r2["boundary"]
    assert r1["decision"] == "reject"
    assert r2["decision"] == "reject_negative"


# ------------------------------- 重放 -------------------------------------- #


def _push_scenario(client, eid):
    _batch(client, eid, 1, 800, 80, 800, 100)
    client.post(f"/api/experiments/{eid}/looks")
    _batch(client, eid, 2, 800, 70, 800, 110)
    client.post(f"/api/experiments/{eid}/looks")
    # 更正批次 1：只改转化数（信息时间不变 -> 同点重复查看，边界沿用）
    _batch(client, eid, 1, 800, 60, 800, 100, is_correction=True)
    client.post(f"/api/experiments/{eid}/looks")
    _batch(client, eid, 3, 800, 90, 800, 90)
    client.post(f"/api/experiments/{eid}/looks")
    _batch(client, eid, 2, 800, 70, 800, 110)  # 幂等重复


def test_replay_matches_online_pointwise(make_experiment, client):
    e = make_experiment()
    eid = e["id"]
    _push_scenario(client, eid)
    online = client.get(f"/api/experiments/{eid}/looks").json()
    report = client.post(f"/api/experiments/{eid}/replay").json()
    assert report["match"] is True, report["discrepancies"]
    assert report["looks_replayed"] == 4
    # 事件：b1 insert, b2 insert, b1 correction, b3 insert, b2 duplicate
    assert report["events_replayed"] == 5
    for a, b in zip(report["looks"], online):
        assert a["boundary"] == b["boundary"]
        assert a["z_stat"] == b["z_stat"]
        assert a["decision"] == b["decision"]
        assert a["info_time"] == b["info_time"]


def test_replay_deterministic_across_calls(make_experiment, client):
    e = make_experiment()
    eid = e["id"]
    _push_scenario(client, eid)
    r1 = client.post(f"/api/experiments/{eid}/replay").json()
    r2 = client.post(f"/api/experiments/{eid}/replay").json()
    assert r1 == r2


def test_trajectory_and_preview(make_experiment, client):
    e = make_experiment()
    eid = e["id"]
    _batch(client, eid, 1, 1920, 192, 1920, 240)
    client.post(f"/api/experiments/{eid}/looks")
    tr = client.get(f"/api/experiments/{eid}/trajectory").json()
    assert len(tr["points"]) == 1
    assert tr["points"][0]["lower_boundary"] == -tr["points"][0]["boundary"]
    assert len(tr["planned_preview"]) == 10
    assert tr["planned_preview"][-1]["boundary"] > stats.Z_0975 - 1e-9
    # 消耗预览单调不减
    spends = [p["cumulative_spend"] for p in tr["planned_preview"]]
    assert spends[-1] <= 0.05 + 1e-12
    assert all(spends[i] < spends[i + 1] for i in range(9))
