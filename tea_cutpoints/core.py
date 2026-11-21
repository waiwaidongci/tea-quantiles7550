"""茶样含水率换档点：精确分段与切点计数引擎。

模型
----
- 送检顺序固定的 n 个批次，第 i 批有 m_i 份含水率读数（1 <= m_i <= 40）。
- 每批的经验分位曲线 Q_i(p) = 第 ceil(m_i*p) 个次序值（p 属于 (0,1]），阶梯函数。
- 切段 [a,b) 的代表曲线 M(p) = 段内各批 Q_i(p) 的逐点中位数；偶数批时取低中位数
  （绝对差之和对两中值之间的任意取法不变，故代价定义无歧义）。
- 段代价 = sum_i integral_0^1 |Q_i(p) - M(p)| dp，各批等权。
- 总代价 = 各段代价之和 + 每刀罚分 * 刀数（刀数 = 段数 - 1），每段至少 min_segment 批。

精确性
------
读数缩放为 1e6 整数（微单位）。所有分位阶梯的拐点都是 k/m_i（m_i <= 40），
取公分母 DEN = lcm(1..40) = 5342931457063200 后，拐点全部落在整数网格上，
段代价 = 整数分子 / DEN。总代价的比较与并列判定全部在整数上进行，无浮点误差。

计数
----
动态规划求最小总代价；前向/后向两遍计数得到并列最优切法总数以及每个切点
在全部最优切法中的出现次数，不逐套枚举。
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

try:  # numpy 为性能加速；缺失时退回纯 Python（结果完全一致，仅更慢）
    import numpy as _np
except ImportError:  # pragma: no cover
    _np = None

SCALE = 1_000_000          # 读数缩放因子：微单位整数
MAX_BATCH_SIZE = 40        # 每批最多 40 份
MIN_SEGMENT = 3            # 每段至少三批


def _lcm_upto(n: int) -> int:
    g = 1
    for k in range(2, n + 1):
        g = g * k // math.gcd(g, k)
    return g


DEN = _lcm_upto(MAX_BATCH_SIZE)  # 5342931457063200 = lcm(1..40)，全局公分母


# ---------------------------------------------------------------- 输入解析

def parse_reading(x) -> int:
    """十进制读数 -> 微单位整数（精确、确定性舍入）。"""
    if isinstance(x, bool):
        raise ValueError("读数必须是数值")
    try:
        d = Decimal(str(x))
    except Exception:
        raise ValueError(f"读数不是合法数值: {x!r}")
    if not d.is_finite():
        raise ValueError("读数必须为有限数值")
    return int((d * SCALE).to_integral_value(rounding=ROUND_HALF_UP))


def parse_penalty(x) -> int:
    """每刀罚分 -> 微单位整数，不得为负。"""
    v = parse_reading(x)
    if v < 0:
        raise ValueError("每刀罚分不得为负")
    return v


def normalize_batches(batches) -> list[list[int]]:
    """校验并规范化批次列表 -> 微单位整数列表的列表（保持送检顺序）。"""
    if not isinstance(batches, (list, tuple)) or not batches:
        raise ValueError("批次列表不能为空")
    out = []
    for i, batch in enumerate(batches):
        if not isinstance(batch, (list, tuple)):
            raise ValueError(f"第 {i + 1} 批不是读数列表")
        if not 1 <= len(batch) <= MAX_BATCH_SIZE:
            raise ValueError(f"第 {i + 1} 批份数为 {len(batch)}，须在 1..{MAX_BATCH_SIZE} 之间")
        out.append([parse_reading(x) for x in batch])
    return out


def micro_to_str(micro: int) -> str:
    """微单位整数 -> 普通十进制字符串（展示用）。"""
    return format(Decimal(micro) / Decimal(SCALE), "f")


# ---------------------------------------------------------------- 结果

@dataclass
class Analysis:
    n_batches: int
    min_segment: int
    penalty_micro: int
    total_cost_num: int                 # 总代价分子（分母为 DEN，单位：微单位）
    total_cost_den: int
    num_optimal: int                    # 并列最优切法总数
    cut_counts: list                    # [(切点位置, 出现次数)]，位置 1..n-1（在第 i 批之后下刀）
    duration_sec: float
    engine: str                         # 'numpy' 或 'python'

    def total_cost_decimal(self, places: int = 6) -> str:
        q = Decimal(1).scaleb(-places)
        v = Decimal(self.total_cost_num) / Decimal(self.total_cost_den) / Decimal(SCALE)
        return format(v.quantize(q), "f")

    def cut_count_map(self) -> dict:
        return dict(self.cut_counts)


# ---------------------------------------------------------------- 曲线准备

class _Curve:
    """单批经验分位曲线：排序读数 + 拐点在 DEN 网格上的整数位置。"""
    __slots__ = ("vals", "steps", "m")

    def __init__(self, vals, steps, m):
        self.vals = vals
        self.steps = steps
        self.m = m


def _prepare(batches_micro: list[list[int]]) -> list[_Curve]:
    curves = []
    for vals in batches_micro:
        sv = sorted(vals)
        m = len(sv)
        if not 1 <= m <= MAX_BATCH_SIZE:
            raise ValueError(f"每批份数须在 1..{MAX_BATCH_SIZE} 之间，实际 {m}")
        unit = DEN // m  # m <= 40 必整除 DEN
        steps = [k * unit for k in range(1, m)]
        if _np is not None:
            curves.append(_Curve(_np.array(sv, dtype=_np.int64),
                                 _np.array(steps, dtype=_np.int64), m))
        else:
            curves.append(_Curve(tuple(sv), tuple(steps), m))
    return curves


# ---------------------------------------------------------------- 段代价

def _dot_exact(w, s) -> int:
    """精确计算 sum(w_t * s_t)（非负 int64 数组），返回 Python int。

    直接 int64 点积可能溢出，故按动态位宽把 w 切成若干“肢”，
    每肢的点积保证不溢出，最后以 Python 大整数移位合成。
    """
    T = int(s.shape[0])
    if T == 0:
        return 0
    smax = int(s.max())
    wmax = int(w.max())
    if smax == 0 or wmax == 0:
        return 0
    sb = smax.bit_length()
    tb = T.bit_length()
    if wmax.bit_length() + sb + tb <= 62:
        return int(_np.dot(w, s))
    limb_bits = 62 - sb - tb
    if limb_bits < 1:  # 极端规模，退回逐项大整数求和
        return sum(int(wi) * int(si) for wi, si in zip(w.tolist(), s.tolist()))
    mask = _np.int64((1 << limb_bits) - 1)
    total = 0
    shift = 0
    rem = w
    while True:
        limb = rem & mask
        rem = rem >> limb_bits
        total += int(_np.dot(limb, s)) << shift
        shift += limb_bits
        if not bool(rem.any()):
            return total


if _np is not None:
    _ENDS = _np.array([0, DEN], dtype=_np.int64)


def _segment_cost_np(curves: list[_Curve], a: int, b: int) -> int:
    """段 [a,b) 的代价分子（分母 DEN）。numpy 向量化精确实现。"""
    sub = curves[a:b]
    B = b - a
    # 段内全部拐点（DEN 网格整数位置）排序去重
    K = _np.unique(_np.concatenate([c.steps for c in sub] + [_ENDS]))
    left = K[:-1]                                    # 各基本区间左端点
    ms = _np.array([c.m for c in sub], dtype=_np.int64)[:, None]
    idx = (ms * left) // DEN                         # (B,T) 各批在区间上的次序下标
    flat = _np.concatenate([c.vals for c in sub])
    offs = _np.cumsum([0] + [c.m for c in sub])[:-1][:, None]
    V = flat[offs + idx]                             # (B,T) 各批在区间上的取值
    med = _np.partition(V, (B - 1) // 2, axis=0)[(B - 1) // 2]   # 逐点低中位数
    sadev = _np.abs(V - med).sum(axis=0)             # 各区间绝对差之和
    return _dot_exact(K[1:] - left, sadev)


def _segment_cost_py(curves: list[_Curve], a: int, b: int) -> int:
    """段 [a,b) 的代价分子（分母 DEN）。纯 Python 回退实现，结果与 numpy 版一致。"""
    points = {0, DEN}
    for c in curves[a:b]:
        points.update(int(s) for s in c.steps)   # 转 Python int，避免 numpy 标量溢出
    K = sorted(points)
    sub = curves[a:b]
    total = 0
    for t in range(len(K) - 1):
        L = K[t]
        w = K[t + 1] - L
        vals = sorted(int(c.vals[(c.m * L) // DEN]) for c in sub)
        med = vals[(len(vals) - 1) // 2]
        total += w * sum(abs(v - med) for v in vals)
    return total


# ---------------------------------------------------------------- 主入口

def analyze(batches_micro: list[list[int]], penalty_micro: int = 0,
            min_segment: int = MIN_SEGMENT) -> Analysis:
    """对按送检顺序排列的批次做最优分段并计数。

    batches_micro: 每批读数（微单位整数）的列表，顺序即送检顺序。
    penalty_micro: 每刀罚分（微单位整数）。
    min_segment:   每段至少批数（默认 3）。
    """
    t0 = time.perf_counter()
    n = len(batches_micro)
    if min_segment < 1:
        raise ValueError("每段最少批数必须为正")
    if n < min_segment:
        raise ValueError(f"共 {n} 批，不足每段最少 {min_segment} 批，无法切段")
    if penalty_micro < 0:
        raise ValueError("每刀罚分不得为负")
    curves = _prepare(batches_micro)
    seg_cost = _segment_cost_np if _np is not None else _segment_cost_py

    def is_boundary(x: int) -> bool:
        return x == 0 or x == n or min_segment <= x <= n - min_segment

    # 全部可用段的精确代价分子
    cost = {}
    for a in range(n):
        if not is_boundary(a):
            continue
        for b in range(a + min_segment, n + 1):
            if is_boundary(b):
                cost[(a, b)] = seg_cost(curves, a, b)

    pen = penalty_micro * DEN  # 罚分换算为同一分母的分子

    # 前向：f[j] = 切到边界 j 的最小代价，g[j] = 达到该最小值的切法数
    f = [None] * (n + 1)
    g = [0] * (n + 1)
    f[0] = 0
    g[0] = 1
    for j in range(1, n + 1):
        if not is_boundary(j):
            continue
        best = None
        cnt = 0
        for i in range(0, j - min_segment + 1):
            if not is_boundary(i) or f[i] is None:
                continue
            c = f[i] + cost[(i, j)] + (pen if i else 0)
            if best is None or c < best:
                best, cnt = c, g[i]
            elif c == best:
                cnt += g[i]
        f[j], g[j] = best, cnt

    # 后向：sf[i] = 从边界 i 切到末尾的最小代价，h[i] = 对应切法数
    sf = [None] * (n + 1)
    h = [0] * (n + 1)
    sf[n] = 0
    h[n] = 1
    for i in range(n - 1, -1, -1):
        if not is_boundary(i):
            continue
        best = None
        cnt = 0
        for j in range(i + min_segment, n + 1):
            if not is_boundary(j) or sf[j] is None:
                continue
            c = cost[(i, j)] + (pen if j < n else 0) + sf[j]
            if best is None or c < best:
                best, cnt = c, h[j]
            elif c == best:
                cnt += h[j]
        sf[i], h[i] = best, cnt

    total = f[n]
    # 经过切点 i 的切法 = 最优前缀 + i 处一刀 + 最优后缀，
    # 其最小代价为 f[i] + pen + sf[i]；等于全局最优时才计入。
    cuts = []
    for i in range(1, n):
        c = 0
        if f[i] is not None and sf[i] is not None and f[i] + pen + sf[i] == total:
            c = g[i] * h[i]
        cuts.append((i, c))

    return Analysis(
        n_batches=n,
        min_segment=min_segment,
        penalty_micro=penalty_micro,
        total_cost_num=total,
        total_cost_den=DEN,
        num_optimal=g[n],
        cut_counts=cuts,
        duration_sec=time.perf_counter() - t0,
        engine="numpy" if _np is not None else "python",
    )


def analyze_decimal(batches, penalty=0, min_segment: int = MIN_SEGMENT) -> Analysis:
    """便捷入口：接受原始十进制读数/罚分（数值或字符串）。"""
    return analyze(normalize_batches(batches), parse_penalty(penalty), min_segment)
