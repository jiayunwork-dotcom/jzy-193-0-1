"""序贯监测试验的统计核心：样本量、α 消耗函数、多查看相关边界。

全部计算使用双精度浮点（IEEE 754 float64，约 15~17 位有效数字）。
边界数值精度：
- 正态分位数 ``normal_ppf`` 绝对误差 < 1.2e-9（Acklam 有理逼近 + 一次 Halley 校正）；
- 边界根求解（二分）容差 5e-13；
- 多维正态联合穿越概率用确定性复合 Simpson 积分（固定 600 等距格点），
  在 0.05 双侧 O'Brien-Fleming 消耗函数下边界绝对误差约 1e-4 量级，
  对「单次查看」特例直接解析返回 1.959963984540054。
同机、同 Python/numpy 版本结果按位可重复；不同平台因浮点求和顺序可能有
1e-12 级别的差异，不影响任何判定。
"""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray
from scipy.special import ndtr  # 标准正态 CDF，双精度机器精度

# ---------------------------------------------------------------------------
# 常数与正态分布函数
# ---------------------------------------------------------------------------

SQRT2 = math.sqrt(2.0)
_SQRT2PI = math.sqrt(2.0 * math.pi)

# Acklam (2003) 逆正态 CDF 有理逼近系数，相对机器精度约 1.15e-9
_A = [-3.969683028665376e+01, 2.209460984245205e+02,
      -2.759285104469687e+02, 1.383577518672690e+02,
      -3.066479806614716e+01, 2.506628277459239e+00]
_B = [-5.447609879822406e+01, 1.615858368580409e+02,
      -1.556989798598866e+02, 6.680131188771972e+01,
      -1.328068155288572e+01]
_C = [-7.784894002430293e-03, -3.223964580411365e-01,
      -2.400758277161838e+00, -2.549732539343734e+00,
      4.374664141464968e+00, 2.938163982698783e+00]
_D = [7.784695709041462e-03, 3.224671290700398e-01,
      2.445134137142996e+00, 3.754408661907416e+00]
_P_LOW = 0.02425
_P_HIGH = 1.0 - _P_LOW


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / SQRT2))


def normal_ppf(p: float) -> float:
    """标准正态分位数（inverse CDF）。p 必须在 (0, 1)。"""
    if not 0.0 < p < 1.0:
        raise ValueError("normal_ppf: p 必须严格在 (0,1) 之间")
    if p < _P_LOW:
        q = math.sqrt(-2.0 * math.log(p))
        x = (((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / \
            ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0)
    elif p <= _P_HIGH:
        q = p - 0.5
        r = q * q
        x = (((((_A[0] * r + _A[1]) * r + _A[2]) * r + _A[3]) * r + _A[4]) * r + _A[5]) * q / \
            (((((_B[0] * r + _B[1]) * r + _B[2]) * r + _B[3]) * r + _B[4]) * r + 1.0)
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        x = -(((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / \
            ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0)
    # 一次 Halley 校正，把误差推到机器精度附近
    e = normal_cdf(x) - p
    u = e * _SQRT2PI * math.exp(x * x / 2.0)
    x = x - u / (1.0 + x * u / 2.0)
    return x


# ---------------------------------------------------------------------------
# 样本量
# ---------------------------------------------------------------------------

def sample_size_per_group(
    baseline: float, mde_abs: float, alpha: float, power: float
) -> int:
    """每组所需样本量，正态近似（Fleiss《Statistical Methods for Rates and
    Proportions》未合并方差口径）：

        n = [ z_{1-α/2} · sqrt(2·p̄·(1-p̄)) + z_{1-β} · sqrt(p1(1-p1)+p2(1-p2)) ]² / Δ²

    其中 p1 = baseline，p2 = baseline + mde_abs（也接受负向提升，只取绝对差），
    p̄ = (p1+p2)/2，Δ = |p2-p1|。

    参考值：baseline=0.10、目标=0.12（Δ=0.02）、α=0.05（双侧）、power=0.8
    得 n = 3841/组。

    口径说明：若改用「合并方差、零假设方差」口径
    n = (z_{1-α/2}+z_{1-β})² · 2p(1-p) / Δ² 会得到约 3839；
    Fleiss 口径在备择假设下单独估计两组方差，略保守，是功效分析常用口径。
    """
    p1 = baseline
    p2 = baseline + mde_abs
    delta = abs(p2 - p1)
    pbar = 0.5 * (p1 + p2)
    za = normal_ppf(1.0 - alpha / 2.0)
    zb = normal_ppf(power)
    num = (
        za * math.sqrt(2.0 * pbar * (1.0 - pbar))
        + zb * math.sqrt(p1 * (1.0 - p1) + p2 * (1.0 - p2))
    ) ** 2
    n = num / (delta * delta)
    # 抵消 1e-12 量级浮点噪声后向上取整
    return int(math.ceil(n - 1e-9))


# ---------------------------------------------------------------------------
# α 消耗函数
# ---------------------------------------------------------------------------

TOTAL_INFO = 1.0  # 信息比例上限固定为 1


def obrien_fleming_spend(t: float, alpha: float) -> float:
    """Lan-DeMets (1983) 对 O'Brien-Fleming 边界的近似消耗函数：

        α*(t) = 2 · ( 1 - Φ( z_{1-α/2} / sqrt(t) ) )

    性质：
    - α*(0)=0，α*(1)=α（最终一次查看恰好等于固定样本检验）；
    - 早期极保守：t=0.5、α=0.05 时 α* ≈ 0.00557；
    - 双侧总消耗（上下两侧之和）。
    """
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return alpha
    z = normal_ppf(1.0 - alpha / 2.0)
    return 2.0 * (1.0 - normal_cdf(z / math.sqrt(t)))


SPENDING_FUNCTIONS = {
    # 早期保守、终局贴近固定样本检验
    "obf": obrien_fleming_spend,
}


# ---------------------------------------------------------------------------
# 信息比例与检验统计量
# ---------------------------------------------------------------------------

def information_fraction(n_a: int, n_b: int, n_per_group: int) -> float:
    """信息比例 t = (n_a + n_b) / (2 · n_per_group)，截断到 [0, 1]。

    两组等样本设计；实际入组不等时按平均入组量折算（与教科书信息时间一致）。
    返回 (t, truncated)，truncated=True 表示实际信息已超过 1。
    """
    if n_per_group <= 0:
        raise ValueError("每组计划样本量必须为正")
    raw = (n_a + n_b) / (2.0 * n_per_group)
    if raw >= 1.0:
        return 1.0, raw > 1.0 + 1e-12
    return raw, False


def z_statistic(
    n_a: int, x_a: int, n_b: int, x_b: int
) -> float:
    """两独立比例比较的合并 z 统计量（等方差、零假设口径）：

        z = (p_A - p_B) / sqrt( p̂(1-p̂)(1/n_A + 1/n_B) )，p̂ = (x_A+x_B)/(n_A+n_B)

    两组样本互换时 z 变号（本函数调用方负责交换数据）。
    两组访问数均为 0 时无定义，由调用方拦截。
    """
    n = n_a + n_b
    if n <= 0 or n_a <= 0 or n_b <= 0:
        raise ValueError("两组访问数都必须为正才能计算两组比较的 z 统计量")
    p_pool = (x_a + x_b) / n
    pa = x_a / n_a
    pb = x_b / n_b
    var = p_pool * (1.0 - p_pool) * (1.0 / n_a + 1.0 / n_b)
    if var <= 0.0:
        # 全部转化或全部未转化：合并方差为 0，统计量定义为 0
        return 0.0
    return (pa - pb) / math.sqrt(var)


# ---------------------------------------------------------------------------
# 序贯边界（Lan-DeMets，相关结构 = Brownian motion 信息时间）
# ---------------------------------------------------------------------------

GRID_N = 600          # 每维 Simpson 等距格点数（偶数），确定性
ROOT_TOL = 5.0e-13    # 二分求根容差


def _corr(t_prev: float, t_cur: float) -> float:
    """规范 Brownian 运动在信息时间 t_prev、t_cur 处的相关系数 sqrt(t_prev/t_cur)。"""
    return math.sqrt(t_prev / t_cur)


def _cross_prob_mid_scalar(
    grid: NDArray[np.float64],
    density: NDArray[np.float64],
    rho: float,
    c: float,
    weights: NDArray[np.float64],
) -> float:
    """给定上一阶段存活密度 density（定义在 [-a, a] 的 grid 上），
    本阶段首次穿越 ±c（c 为标量）的概率（复合 Simpson 积分，确定性）。

    条件分布 X_k | X_{k-1}=x ~ N(ρx, 1-ρ²)。
    """
    sd = math.sqrt(max(1.0 - rho * rho, 0.0))
    z_hi = (c - rho * grid) / sd
    z_lo = (-c - rho * grid) / sd
    tail_hi = 1.0 - ndtr(z_hi)             # P(X_k >= c | x)
    tail_lo = ndtr(z_lo)                   # P(X_k <= -c | x) = Φ(z_lo)
    integrand = density * (tail_hi + tail_lo)
    return float(weights @ integrand)


def _simpson_weights(grid: NDArray[np.float64], n: int) -> NDArray[np.float64]:
    a = float(grid[-1])
    weights = np.ones(n + 1)
    weights[1:n:2] = 4.0
    weights[2:n:2] = 2.0
    weights *= (2.0 * a) / (3.0 * n)
    return weights


def _cross_prob_first(c: float) -> float:
    """第一阶段（信息时间 t1，z~N(0,1)）|z| >= c 的概率。"""
    return 2.0 * (1.0 - normal_cdf(c))


def _bisect_boundary(target: float, cross_fn, lo: float = 1.0e-6,
                     hi: float = 12.0) -> float:
    """求 cross_fn(c) = target 的单调递减正根。"""
    flo = cross_fn(lo)
    fhi = cross_fn(hi)
    # 极端情况下 target 可能小到数值上为 0；给出可行夹逼
    for _ in range(60):
        if flo >= target >= fhi:
            break
        hi *= 1.5
        fhi = cross_fn(hi)
    else:  # pragma: no cover
        raise RuntimeError("边界求根无法夹逼")
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if cross_fn(mid) > target:
            lo = mid
        else:
            hi = mid
        if hi - lo < ROOT_TOL * max(1.0, hi):
            break
    return 0.5 * (lo + hi)


def sequential_boundaries(
    times: list[float],
    spent: list[float],
    grid_n: int = GRID_N,
) -> list[float]:
    """按 Lan-DeMets 消耗函数法计算各次查看的双侧等距停止边界 c_k。

    参数
    ----
    times : 历次查看（含本次）的信息时间 t_k，0 < t_1 < ... <= 1；
            允许相邻 t 相等（更正导致信息不增），此时沿用上一非重复边界。
    spent : 到该次查看为止的累计消耗 α*(t_k)（含本次），单调不减、
            spent[-1] <= 总 α。

    相关结构：Cov(Z(t_i), Z(t_j)) = sqrt(t_i/t_j)（规范 Brownian 运动）。
    第 k 次穿越概率增量 = spent[k] - spent[k-1]，通过对前 k-1 次
    存活密度逐维确定性 Simpson 卷积求得联合穿越概率，再二分反解 c_k。

    特例：到 t=1 只查看一次时返回 [z_{0.975}] = 1.9599639845...。
    """
    if len(times) != len(spent) or not times:
        raise ValueError("times 与 spent 长度须一致且非空")
    if any(t <= 0.0 for t in times):
        raise ValueError("信息时间必须为正")

    boundaries: list[float] = []
    grid = None
    density = None
    weights = None
    prev_t = None
    prev_c = None

    for k, (t, cum) in enumerate(zip(times, spent)):
        if k > 0 and t < times[k - 1] - 1e-12:
            raise ValueError("信息时间必须单调不减")
        if prev_t is not None and abs(t - prev_t) <= 1e-12:
            # 信息未增加：沿用上一阶段边界（α 增量也应为 0）
            boundaries.append(prev_c)
            continue

        inc = cum - (spent[k - 1] if k > 0 else 0.0)
        if inc < -1e-15:
            raise ValueError("累计消耗 α 必须单调不减")

        if k == 0:
            if len(times) == 1 and abs(t - 1.0) <= 1e-12:
                # 终局单次查看：精确解析边界
                c = normal_ppf(1.0 - cum / 2.0)
            else:
                c = _bisect_boundary(inc, _cross_prob_first)
            a = max(6.0, c * 2.2)
            grid = np.linspace(-a, a, grid_n + 1)
            weights = _simpson_weights(grid, grid_n)
            pdf = np.exp(-0.5 * grid * grid) / _SQRT2PI
            density = np.where(np.abs(grid) >= c, 0.0, pdf)
        else:
            rho = _corr(prev_t, t)
            c = _bisect_boundary(
                inc,
                lambda cand: _cross_prob_mid_scalar(
                    grid, density, rho, cand, weights
                ),
            )
            # 推进存活密度：对旧存活密度积分条件密度，并剔除本阶段穿越部分
            sd = math.sqrt(max(1.0 - rho * rho, 0.0))
            z = (grid[None, :] - rho * grid[:, None]) / sd
            cond_pdf = np.exp(-0.5 * z * z) / (sd * _SQRT2PI)
            new_density = (density * weights) @ cond_pdf
            new_density = np.where(np.abs(grid) >= c, 0.0, new_density)
            density = new_density

        boundaries.append(c)
        prev_t = t
        prev_c = c

    return boundaries


def spent_series(
    times: list[float], alpha: float, spending: str = "obf"
) -> list[float]:
    """信息时间序列对应的累计 α 消耗（直接由消耗函数点值给出，
    天然单调不减；t>=1 截断后最后一点强制等于总 α）。"""
    fn = SPENDING_FUNCTIONS[spending]
    out = [fn(min(max(t, 0.0), 1.0), alpha) for t in times]
    # 截断点与终局点的精确化
    for i, t in enumerate(times):
        if t >= 1.0 - 1e-12:
            out[i] = alpha
    # 强制单调（消除浮点往返噪声）
    for i in range(1, len(out)):
        if out[i] < out[i - 1]:
            out[i] = out[i - 1]
    return out
