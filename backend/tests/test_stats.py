"""统计内核数值用例。"""

from __future__ import annotations

import math

import pytest

from app import stats


def test_sample_size_reference_3841():
    n = stats.sample_size_per_group(0.10, 0.12, 0.05, 0.8)
    assert n == 3841


def test_sample_size_formula_value():
    # 未取整值 3840.847…
    from scipy.stats import norm

    p0, p1 = 0.10, 0.12
    pbar = 0.11
    za = norm.ppf(0.975)
    zb = norm.ppf(0.8)
    expected = (
        za * math.sqrt(2 * pbar * 0.89) + zb * math.sqrt(0.1 * 0.9 + 0.12 * 0.88)
    ) ** 2 / 0.0004
    assert expected == pytest.approx(3840.8474824, rel=1e-7)


@pytest.mark.parametrize(
    "p0,p1,a,power",
    [
        (0.05, 0.07, 0.05, 0.8),
        (0.2, 0.25, 0.01, 0.9),
        (0.5, 0.55, 0.1, 0.8),
    ],
)
def test_sample_size_finite_positive(p0, p1, a, power):
    n = stats.sample_size_per_group(p0, p1, a, power)
    assert n > 0


def test_alpha_spend_reference_values():
    assert stats.alpha_spend(0.5, 0.05) == pytest.approx(0.0055745967, abs=1e-9)
    assert stats.alpha_spend(1.0, 0.05) == pytest.approx(0.05, abs=1e-12)
    assert stats.alpha_spend(0.0, 0.05) == 0.0
    # 单调不减
    ts = [i / 20 for i in range(1, 21)]
    vals = [stats.alpha_spend(t, 0.05) for t in ts]
    assert all(vals[i] < vals[i + 1] for i in range(len(vals) - 1))
    assert vals[-1] <= 0.05 + 1e-15


def test_boundary_single_look_at_one():
    (b,) = stats.boundaries([1.0], 0.05)
    assert b == pytest.approx(1.95996398, abs=1e-7)


def test_boundary_known_two_look():
    b1, b2 = stats.boundaries([0.5, 1.0], 0.05)
    # 首次边界来自闭式
    assert b1 == pytest.approx(2.77180765, abs=1e-8)
    # 末期边界略高于固定样本临界值（LD-OBF 已知性质，教科书值约 1.979）
    assert b2 == pytest.approx(1.9793, abs=5e-4)
    assert b2 > 1.95996398


def test_boundaries_five_equal_spaced_textbook():
    bs = stats.boundaries([0.2, 0.4, 0.6, 0.8, 1.0], 0.05)
    expected = [4.3826, 3.0997, 2.5534, 2.2541, 2.0635]
    for got, exp in zip(bs, expected):
        assert got == pytest.approx(exp, abs=5e-4)


def test_boundaries_monotone_decreasing():
    bs = stats.boundaries([i / 10 for i in range(1, 11)], 0.05)
    assert all(bs[i] > bs[i + 1] for i in range(len(bs) - 1))


def test_boundary_determinism_bit_identical():
    ts = [0.13, 0.31, 0.48, 0.72, 0.91, 1.0]
    a = stats.boundaries(ts, 0.05)
    b = stats.boundaries(ts, 0.05)
    assert a == b


def test_boundary_requires_nondecreasing():
    with pytest.raises(ValueError):
        stats.boundaries([0.6, 0.4], 0.05)
    with pytest.raises(ValueError):
        stats.boundaries([0.5, 1.2], 0.05)


def test_boundary_equal_info_time_reuses_previous():
    # 同信息时点（更正只改转化数）：边界不变、不新消耗 alpha
    bs = stats.boundaries([0.5, 0.5], 0.05)
    assert bs[0] == bs[1]
    # 与只在 0.5 查看一次完全相同
    assert bs[0] == stats.boundaries([0.5], 0.05)[0]


def test_z_sign_flip_under_swap():
    z1 = stats.z_statistic(100, 1000, 130, 1000)
    z2 = stats.z_statistic(130, 1000, 100, 1000)
    assert z1 > 0
    assert z2 == -z1


def test_z_zero_edge_cases():
    assert stats.z_statistic(0, 0, 0, 0) == 0.0
    # 两组转化率相同
    assert stats.z_statistic(100, 1000, 100, 1000) == pytest.approx(0.0, abs=1e-12)


def test_info_time_equal_groups():
    eff, raw, clip = stats.info_time(1920, 1920, 3841)
    assert eff == pytest.approx(1920 / 3841, rel=1e-12)
    assert clip is False


def test_info_time_clipped_at_one():
    eff, raw, clip = stats.info_time(5000, 5000, 3841)
    assert eff == 1.0
    assert raw > 1.0
    assert clip is True


def test_info_time_unequal_groups_harmonic():
    eff, _, _ = stats.info_time(1000, 3000, 2000)
    n_eff = 2 / (1 / 1000 + 1 / 3000)
    assert eff == pytest.approx(n_eff / 2000, rel=1e-12)
    assert eff == pytest.approx(0.75)


def test_evaluate_look_rejects_both_sides_symmetric():
    rpos = stats.evaluate_look(1, [], 0.5, 0.5, False, 3.0, 0.05)
    rneg = stats.evaluate_look(1, [], 0.5, 0.5, False, -3.0, 0.05)
    assert rpos.decision == "reject"
    assert rpos.direction == "treatment_better"
    assert rneg.decision == "reject_negative"
    assert rneg.direction == "control_better"
    assert rpos.boundary == rneg.boundary
    rmid = stats.evaluate_look(1, [], 0.5, 0.5, False, 0.1, 0.05)
    assert rmid.decision == "continue"


def test_cumulative_spend_monotone_and_bounded():
    ts = [0.15, 0.33, 0.51, 0.7, 0.9, 1.0]
    bs = stats.boundaries(ts, 0.05)
    spends = [stats.alpha_spend(t, 0.05) for t in ts]
    assert all(spends[i] < spends[i + 1] for i in range(len(spends) - 1))
    assert spends[-1] == pytest.approx(0.05, abs=1e-12)
    assert max(spends) <= 0.05 + 1e-12
    assert bs[-1] > 1.95996398 - 1e-9  # 末点为 1 的多次查看，末期 >= 固定样本值
