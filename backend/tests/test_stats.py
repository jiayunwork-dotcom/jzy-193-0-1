"""统计核心数值测试。"""

from __future__ import annotations

import math

import pytest

from app import stats


def test_normal_ppf_known_values():
    assert stats.normal_ppf(0.975) == pytest.approx(1.959963984540054, abs=1e-12)
    assert stats.normal_ppf(0.5) == pytest.approx(0.0, abs=1e-12)
    # CDF/PPF 互逆
    for p in (0.001, 0.01, 0.1, 0.3, 0.7, 0.999):
        assert stats.normal_cdf(stats.normal_ppf(p)) == pytest.approx(p, abs=1e-12)


def test_sample_size_reference_3841():
    # 基线 10%、目标 12%、α=0.05 双侧、功效 0.8 → 每组 3841
    n = stats.sample_size_per_group(0.10, 0.02, 0.05, 0.80)
    assert n == 3841


def test_sample_size_monotone():
    n_more_power = stats.sample_size_per_group(0.10, 0.02, 0.05, 0.90)
    n_small_mde = stats.sample_size_per_group(0.10, 0.01, 0.05, 0.80)
    n_base = stats.sample_size_per_group(0.10, 0.02, 0.05, 0.80)
    assert n_more_power > n_base
    assert n_small_mde > n_base
    # 负向最小提升与对称正向相同（取绝对差）
    assert stats.sample_size_per_group(0.12, -0.02, 0.05, 0.80) == n_base


def test_obf_spending_reference():
    # 信息比例 0.5 处累计消耗 ≈ 0.00557
    assert stats.obrien_fleming_spend(0.5, 0.05) == pytest.approx(0.00557, abs=3e-5)
    assert stats.obrien_fleming_spend(0.5, 0.05) == pytest.approx(0.0055746, abs=1e-6)
    # t=1 恰好总 α
    assert stats.obrien_fleming_spend(1.0, 0.05) == pytest.approx(0.05, abs=1e-15)
    assert stats.obrien_fleming_spend(0.0, 0.05) == 0.0


def test_single_look_boundary_at_terminal():
    # 只在信息比例 1 处查看一次 → 1.95996
    b = stats.sequential_boundaries([1.0], [0.05])
    assert b[0] == pytest.approx(1.959963984540054, abs=1e-9)


def test_spent_series_monotone_and_capped():
    times = [0.1, 0.1, 0.35, 0.9, 1.0, 1.0]
    spent = stats.spent_series(times, 0.05)
    assert spent[-1] == pytest.approx(0.05, abs=1e-15)
    assert all(spent[i] <= spent[i + 1] + 1e-15 for i in range(len(spent) - 1))
    assert all(0.0 <= s <= 0.05 + 1e-15 for s in spent)


def test_boundaries_decreasing_and_symmetric():
    times = [0.2, 0.4, 0.6, 0.8, 1.0]
    spent = stats.spent_series(times, 0.05)
    b = stats.sequential_boundaries(times, spent)
    assert b[0] > b[-1]
    assert all(b[i] >= b[i + 1] - 1e-9 for i in range(len(b) - 1))
    # 消耗对称（双侧等距边界由 α/2 定义，与数据符号无关——对调数据只影响 z 符号）
    assert all(c > 0 for c in b)


def test_repeated_information_time_reuses_boundary():
    # t 相同：α 增量为 0 且沿用上一边界
    times = [0.4, 0.4, 1.0]
    spent = stats.spent_series(times, 0.05)
    b = stats.sequential_boundaries(times, spent)
    assert b[1] == pytest.approx(b[0], abs=1e-12)
    # 总边界仍在终局附近
    assert b[2] == pytest.approx(1.97, abs=0.03)


def test_total_spending_does_not_exceed_alpha():
    """边界序列在联合分布下的总穿越概率（Simpson 自校）等于总 α。"""
    import numpy as np

    times = [0.2, 0.4, 0.6, 0.8, 1.0]
    spent = stats.spent_series(times, 0.05)
    b = stats.sequential_boundaries(times, spent)
    n = stats.GRID_N
    a = max(6.0, b[0] * 2.2)
    g = np.linspace(-a, a, n + 1)
    w = stats._simpson_weights(g, n)
    dens = np.exp(-0.5 * g * g) / stats._SQRT2PI
    dens = np.where(np.abs(g) >= b[0], 0.0, dens)
    total = stats._cross_prob_first(b[0])
    pt = times[0]
    for t, c in zip(times[1:], b[1:]):
        rho = math.sqrt(pt / t)
        total += stats._cross_prob_mid_scalar(g, dens, rho, c, w)
        sd = math.sqrt(1.0 - rho * rho)
        z = (g[None, :] - rho * g[:, None]) / sd
        cpdf = np.exp(-0.5 * z * z) / (sd * stats._SQRT2PI)
        dens = (dens * w) @ cpdf
        dens = np.where(np.abs(g) >= c, 0.0, dens)
        pt = t
    assert total == pytest.approx(0.05, abs=2e-6)
    assert total <= 0.05 + 2e-6


def test_determinism():
    times = [0.13, 0.31, 0.58, 0.83, 1.0]
    spent = stats.spent_series(times, 0.05)
    b1 = stats.sequential_boundaries(times, spent)
    b2 = stats.sequential_boundaries(times, spent)
    assert b1 == b2


def test_z_swap_groups_flips_sign():
    z1 = stats.z_statistic(4000, 480, 4000, 400)
    z2 = stats.z_statistic(4000, 400, 4000, 480)
    assert z1 == pytest.approx(-z2, abs=1e-12)
    assert abs(z1) > 0
    # 等比例 → z=0
    assert stats.z_statistic(1000, 100, 2000, 200) == pytest.approx(0.0, abs=1e-12)
    # 全转化 / 全未转化（合并方差 0）→ 定义为 0
    assert stats.z_statistic(100, 100, 100, 100) == 0.0
    assert stats.z_statistic(100, 0, 100, 0) == 0.0


def test_z_requires_both_groups_positive():
    with pytest.raises(ValueError):
        stats.z_statistic(0, 0, 100, 10)
    with pytest.raises(ValueError):
        stats.z_statistic(100, 5, 0, 0)


def test_information_fraction():
    t, capped = stats.information_fraction(3841, 3841, 3841)
    assert t == pytest.approx(1.0) and capped is False
    t, capped = stats.information_fraction(5000, 4000, 3841)
    assert t == 1.0 and capped is True
    t, _ = stats.information_fraction(3841, 0, 3841)
    assert t == pytest.approx(0.5, abs=1e-9)
    t, _ = stats.information_fraction(1920, 1920, 3841)
    assert t == pytest.approx(1920 / 3841, abs=1e-9)
