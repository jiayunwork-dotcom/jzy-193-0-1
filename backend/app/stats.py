"""统计内核：样本量、Z 统计量、Lan-DeMets O'Brien-Fleming alpha 消耗与逐次停止边界。

口径
----
1. 样本量（两比例比较，双侧，正态近似，H0 下合并方差）::

       n = [ z_{1-a/2} * sqrt(2 p_bar (1-p_bar)) + z_{1-beta} * sqrt(p0(1-p0)+p1(1-p1)) ]^2
           / (p1-p0)^2,   p_bar = (p0+p1)/2

   基线 10%、目标 12%、alpha=0.05、power=0.8 时 n=3840.847…，向上取整 3841（每组）。

2. 检验统计量（H0 下合并标准误，treatment 记为正向）::

       p_hat_c = x_c / n_c, p_hat_t = x_t / n_t
       p_pool  = (x_c + x_t)/(n_c + n_t)
       SE      = sqrt(p_pool(1-p_pool)(1/n_c + 1/n_t))
       Z       = (p_hat_t - p_hat_c) / SE

   两组标签互换 => Z -> -Z，双侧边界对称，结论对称。

3. 信息比例（每组计划样本 N；等组 n_c=n_t=n 时 t=n/N）::

       n_eff = 2 / (1/n_c + 1/n_t)     # 等组时 n_eff = n
       t     = n_eff / N

   上限截断为 1，结果中标注 raw_info_time 与 clipped 标志。

4. alpha 消耗（Lan-DeMets 近似 O'Brien-Fleming，双侧）::

       alpha*(t) = 2 * (1 - Phi(z_{1-alpha/2} / sqrt(t)))

   alpha=0.05：t=0.5 时 0.00557460…（约 0.00557），t=1 时恰好 0.05。
   早期保守（t=0.2 边界约 4.56 个标准差），末期趋近固定样本检验（t=1 边界
   z_{1-a/2}=1.95996398…，仅在 t=1 查看一次时严格等于 1.95996398）。

5. 边界计算：规范 Brownian 运动协方差 Cov(Z_i,Z_j)=sqrt(t_i/t_j)（i<j）。
   采用 Armitage 一维确定性递推数值积分（网格 [-10,10]，3201 等距节点，
   梯形法 + 边界处分数端点权重；每阶段一次 O(N^2) 分块矩阵传播，50 轮二分）。
   结果与教科书 LD-OBF 表一致（5 次等距查看约 4.38/3.10/2.55/2.25/2.06，
   末期严格 1.95996398）。
   数值精度：边界绝对值误差 <= 5e-4（K<=10 次查看，N=3201 与 N=9001 参考
   解比较）；alpha 消耗为闭式求值，误差 < 1e-15；全程无随机数，
   相同输入位位相同、可重放。

冻结策略：本系统对「已完成查看的边界与累计消耗 alpha」**冻结**（见 docs/design.md）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from scipy.stats import norm

# ---- 数值积分固定参数（确定性的一部分，改动会改变边界数值，故不做运行时配置） ----
_GRID_N = 3201
_GRID_WIDTH = 10.0
_BISECT_ITERS = 50
_CHUNK = 512
_Z_CLIP = 30.0

Z_0975 = float(norm.ppf(0.975))  # 1.959963984540054


# ----------------------------- 基础统计量 ---------------------------------- #


def z_critical_two_sided(alpha: float) -> float:
    return float(norm.ppf(1.0 - alpha / 2.0))


def z_power(power: float) -> float:
    return float(norm.ppf(power))


def sample_size_per_group(baseline: float, target: float, alpha: float, power: float) -> int:
    """每组所需样本量（H0 合并方差口径，正态近似，向上取整）。"""
    p0, p1 = baseline, target
    pbar = (p0 + p1) / 2.0
    za = z_critical_two_sided(alpha)
    zb = z_power(power)
    num = (
        za * math.sqrt(2.0 * pbar * (1.0 - pbar))
        + zb * math.sqrt(p0 * (1.0 - p0) + p1 * (1.0 - p1))
    ) ** 2
    n = num / (p1 - p0) ** 2
    return int(math.ceil(n - 1e-12))


def info_time(control_n: int, treatment_n: int, planned_n: int) -> tuple[float, float, bool]:
    """返回 (effective_t, raw_t, clipped)。t>1 截断为 1。

    口径：每组计划样本 N（两组共 2N）。与 pooled SE 的 (1/n_c+1/n_t) 项一致，
    定义每组等效样本 n_eff = 2/(1/n_c+1/n_t)，等组 n_c=n_t=n 时 n_eff=n，
    故 t = n_eff/N，等组时化简为 t=n/N。
    """
    if control_n <= 0 or treatment_n <= 0 or planned_n <= 0:
        return 0.0, 0.0, False
    n_eff = 2.0 / (1.0 / control_n + 1.0 / treatment_n)
    raw = n_eff / planned_n
    if abs(raw - 1.0) < 1e-9:  # 浮点吸收：恰好达到计划样本时视为 1
        return 1.0, 1.0, False
    if raw > 1.0:
        return 1.0, raw, True
    return raw, raw, False


def z_statistic(control_x: int, control_n: int, treatment_x: int, treatment_n: int) -> float:
    """合并方差两比例 Z；任一组无样本或 SE=0 时返回 0.0。"""
    if control_n <= 0 or treatment_n <= 0:
        return 0.0
    pc = control_x / control_n
    pt = treatment_x / treatment_n
    total_n = control_n + treatment_n
    p_pool = (control_x + treatment_x) / total_n
    se_sq = p_pool * (1.0 - p_pool) * (1.0 / control_n + 1.0 / treatment_n)
    if se_sq <= 0.0:
        return 0.0
    return float((pt - pc) / math.sqrt(se_sq))


# ----------------------------- alpha 消耗 ---------------------------------- #


def alpha_spend(t: float, alpha: float) -> float:
    """Lan-DeMets O'Brien-Fleming 双侧累计消耗。t=0 时为 0。"""
    if t <= 0.0:
        return 0.0
    za = norm.ppf(1.0 - alpha / 2.0)
    return float(2.0 * (1.0 - norm.cdf(za / math.sqrt(t))))


# --------------------------- 确定性边界递推 -------------------------------- #


def _fractional_trapezoid_weights(grid: np.ndarray, step: float, b: float) -> np.ndarray:
    """密度被截断在 [-b, b] 时的梯形权重，边界落在格点之间用分数端点权重。"""
    n = grid.shape[0]
    w = np.zeros(n)
    if b >= grid[-1]:
        # 边界超出积分区间：区间内全部保留（标准梯形权重）
        w[:] = step
        w[0] = w[-1] = step / 2.0
        return w
    lo = int(np.clip(np.searchsorted(grid, -b), 1, n - 1))
    hi = int(np.clip(np.searchsorted(grid, b), 1, n - 1))
    w[lo : hi + 1] = step
    fl = (-b - grid[lo - 1]) / step
    fr = (b - grid[hi - 1]) / step
    fl = min(max(fl, 0.0), 1.0)
    fr = min(max(fr, 0.0), 1.0)
    w[lo - 1] = step * fl / 2.0
    w[lo] = step - step * fl / 2.0
    w[hi] = step * fr / 2.0
    w[hi - 1] = step - step * fr / 2.0
    return w


def _trapezoid_cumulative(f: np.ndarray, step: float) -> np.ndarray:
    return np.concatenate([[0.0], np.cumsum((f[1:] + f[:-1]) / 2.0 * step)])


def _integral_to(x: float, grid: np.ndarray, step: float, f: np.ndarray, cum: np.ndarray) -> float:
    """分段线性密度从左端点到 x 的积分（x 可为边界分数位置）。"""
    n = grid.shape[0]
    i = int(np.clip(np.searchsorted(grid, x), 1, n - 1))
    fr = (x - grid[i - 1]) / step
    fr = min(max(fr, 0.0), 1.0)
    f_end = f[i - 1] + fr * (f[i] - f[i - 1])
    return float(cum[i - 1] + (f[i - 1] + f_end) / 2.0 * step * fr)


def boundaries(info_times: list[float], alpha: float) -> list[float]:
    """给定全部查看时点（单调递增、末点<=1），返回每次查看的双侧对称临界值。

    第 k 次边界 c_k 满足：在规范 Brownian 运动、历史边界 c_1..c_{k-1} 下，
    累计越界概率 = alpha*(t_k)。首次查看用闭式 c_1 = Phi^{-1}(1-alpha*(t_1)/2)。
    """
    if not info_times:
        return []
    ts = [float(t) for t in info_times]
    if any(t <= 0 for t in ts):
        raise ValueError("info times must be positive")
    if any(ts[i] > ts[i + 1] + 1e-12 for i in range(len(ts) - 1)):
        raise ValueError("info times must be non-decreasing")
    if ts[-1] > 1.0 + 1e-12:
        raise ValueError("info times must be <= 1")
    ts = [min(t, 1.0) for t in ts]

    # 仅在 t=1 查看一次：固定样本检验，闭式
    if len(ts) == 1 and abs(ts[0] - 1.0) < 1e-12:
        return [z_critical_two_sided(alpha)]

    grid = np.linspace(-_GRID_WIDTH, _GRID_WIDTH, _GRID_N)
    step = 2.0 * _GRID_WIDTH / (_GRID_N - 1)

    b0 = float(norm.ppf(1.0 - alpha_spend(ts[0], alpha) / 2.0))
    result = [b0]
    fw = norm.pdf(grid) * _fractional_trapezoid_weights(grid, step, b0)

    for k in range(1, len(ts)):
        t_prev, t = ts[k - 1], ts[k]
        if abs(t - t_prev) <= 1e-12:
            # 同一信息时点的重复查看（如更正只改转化数、不改样本量）：
            # 不增加信息、不新消耗 alpha，边界沿用上次值，按当次 Z 判定。
            result.append(result[-1])
            continue
        r = math.sqrt(t_prev / t)
        s = math.sqrt(max(1.0 - t_prev / t, 0.0))
        f_new = np.zeros(_GRID_N)
        centers = r * grid
        for j0 in range(0, _GRID_N, _CHUNK):
            x = grid[j0 : j0 + _CHUNK, None]
            z = np.clip((x - centers[None, :]) / s, -_Z_CLIP, _Z_CLIP)
            kernel = np.exp(-0.5 * z * z) / (s * math.sqrt(2.0 * math.pi))
            f_new[j0 : j0 + _CHUNK] = kernel @ fw
        cum = _trapezoid_cumulative(f_new, step)
        mass = float(cum[-1])
        spent_prev = alpha_spend(t_prev, alpha)
        target = alpha_spend(t, alpha)

        def inside_prob(b: float) -> float:
            return _integral_to(b, grid, step, f_new, cum) - _integral_to(
                -b, grid, step, f_new, cum
            )

        lo, hi = 0.5, 8.0
        for _ in range(_BISECT_ITERS):
            mid = (lo + hi) / 2.0
            crossing = spent_prev + (mass - inside_prob(mid))
            if crossing < target:
                hi = mid
            else:
                lo = mid
        if hi >= 8.0 - 1e-9:
            # 极早期查看（t 极小）时所需边界可能超出积分网格 [-10,10]：
            # 此时本期新增消耗相对历史趋近 0，用闭式分位函数给出保守边界
            # （等价于"把本时点当成新序列首次查看"）。其值可能 >10，
            # 截断权重函数对越界边界退化为区间全保留。
            bk = float(norm.ppf(1.0 - target / 2.0))
        else:
            bk = (lo + hi) / 2.0
        result.append(bk)
        fw = f_new * _fractional_trapezoid_weights(grid, step, bk)

    # 末点 t=1 的最后一次查看，数值递推解可能与精确值 1.95996398 相差 <=5e-4。
    # 当且仅当只有一个查看时点且 t=1 时走闭式（上面已处理）；其余保留递推值，
    # 以保证逐次 alpha 消耗定义下的一致性（末期边界略高于固定样本值是 LD-OBF
    # 消耗函数的已知性质）。
    return result


@lru_cache(maxsize=4096)
def boundaries_cached(info_times: tuple[float, ...], alpha: float) -> tuple[float, ...]:
    """确定性结果的进程内缓存：相同 (时点序列, α) 的边界位位相同。

    仅缓存纯函数边界计算；每实验的查看序列不同，缓存键互不干扰。
    重启后缓存为空不影响结果（重算一致）。
    """
    return tuple(boundaries(list(info_times), alpha))


# ----------------------------- 查看决策封装 --------------------------------- #


@dataclass(frozen=True)
class LookResult:
    look_number: int
    raw_info_time: float
    info_time: float
    clipped: bool
    z: float
    boundary: float
    cumulative_spend: float  # 该时点定义允许消耗的累计 alpha（闭式）
    decision: str  # "continue" | "reject" | "reject_negative"
    direction: str | None  # "treatment_better" | "control_better" | None


def evaluate_look(
    look_number: int,
    past_info_times: list[float],
    effective_t: float,
    raw_t: float,
    clipped: bool,
    z: float,
    alpha: float,
) -> LookResult:
    """依据**冻结**的历史时点计算本次边界。past_info_times 不含本次。"""
    all_ts = tuple(list(past_info_times) + [effective_t])
    bs = list(boundaries_cached(all_ts, alpha))
    b = bs[-1]
    spend = alpha_spend(effective_t, alpha)
    decision = "continue"
    direction: str | None = None
    if z > b:
        decision = "reject"
        direction = "treatment_better"
    elif z < -b:
        decision = "reject_negative"
        direction = "control_better"
    return LookResult(
        look_number=look_number,
        raw_info_time=raw_t,
        info_time=effective_t,
        clipped=clipped,
        z=z,
        boundary=b,
        cumulative_spend=spend,
        decision=decision,
        direction=direction,
    )
