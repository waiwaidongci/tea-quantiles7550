"""独立穷举参照实现：逐套枚举所有合法切法，用 Fraction 精确计算。

仅用于测试核对引擎（tea_cutpoints.core）的结果：
- 最小总代价（精确分数）
- 并列最优切法总数
- 每个切点在最优切法中的出现次数
"""
from fractions import Fraction


def curve_value_at(sorted_xs, p):
    """经验分位曲线 Q(p) = 第 ceil(m*p) 个次序值，p 为区间左端点（Fraction）。"""
    m = len(sorted_xs)
    idx = 0
    for k in range(1, m):
        if Fraction(k, m) <= p:
            idx = k
    return sorted_xs[idx]


def segment_cost(batches, a, b):
    """段 [a,b) 代价：sum_i integral |Q_i - 逐点中位数| dp，Fraction 精确值。"""
    pts = {Fraction(0), Fraction(1)}
    sorted_batch = []
    for i in range(a, b):
        xs = sorted(batches[i])
        sorted_batch.append(xs)
        m = len(xs)
        for k in range(1, m):
            pts.add(Fraction(k, m))
    pts = sorted(pts)
    total = Fraction(0)
    for t in range(len(pts) - 1):
        p0, p1 = pts[t], pts[t + 1]
        vals = sorted(curve_value_at(xs, p0) for xs in sorted_batch)
        med = vals[(len(vals) - 1) // 2]  # 低中位数（偶数时两中值之间面积不变）
        total += (p1 - p0) * sum(abs(v - med) for v in vals)
    return total


def compositions(n, min_part):
    """n 的所有各部分 >= min_part 的有序拆分。"""
    if n == 0:
        yield []
        return
    for first in range(min_part, n + 1):
        rest = n - first
        if rest == 0:
            yield [first]
        elif rest >= min_part:
            for tail in compositions(rest, min_part):
                yield [first] + tail


def brute_analyze(batches, penalty=0, min_segment=3):
    """逐套枚举。返回 (最小总代价 Fraction, 并列最优切法数, {切点: 出现次数})。"""
    n = len(batches)
    best = None
    best_cuts = []
    for comp in compositions(n, min_segment):
        cost = Fraction(penalty) * (len(comp) - 1)
        a = 0
        cuts = []
        for k, part in enumerate(comp):
            cost += segment_cost(batches, a, a + part)
            a += part
            if k < len(comp) - 1:
                cuts.append(a)
        if best is None or cost < best:
            best, best_cuts = cost, [tuple(cuts)]
        elif cost == best:
            best_cuts.append(tuple(cuts))
    counts = {i: 0 for i in range(1, n)}
    for cuts in best_cuts:
        for c in cuts:
            counts[c] += 1
    return best, len(best_cuts), counts
