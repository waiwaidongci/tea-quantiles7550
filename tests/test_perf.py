"""性能与后端一致性：80 批 × 40 份在 30 秒内算完；numpy 与纯 Python 路径结果一致。"""
import random
import unittest

from tea_cutpoints import core
from tea_cutpoints.core import analyze


def make_batches(n, m, seed=42, jitter=0.6):
    """四个含水率档位的合成数据（段内平稳、段间跳变）。"""
    rng = random.Random(seed)
    levels = [8.0, 11.2, 9.3, 13.1]
    batches = []
    for i in range(n):
        lv = levels[(i // max(1, n // 4)) % len(levels)]
        batches.append([round(lv + (rng.random() - 0.5) * jitter, 2) for _ in range(m)])
    return batches


class TestPerformance(unittest.TestCase):
    def test_80x40_under_30s(self):
        batches = make_batches(80, 40)
        res = core.analyze_decimal(batches, penalty=0.5)
        print(f"\n80批×40份: {res.duration_sec:.2f}s (引擎 {res.engine}), "
              f"并列最优 {res.num_optimal}, 非零切点 "
              f"{sum(1 for _, c in res.cut_counts if c > 0)} 个")
        self.assertLess(res.duration_sec, 30)
        self.assertGreaterEqual(res.num_optimal, 1)
        self.assertEqual(len(res.cut_counts), 79)

    def test_80_batches_unequal_sizes_under_30s(self):
        rng = random.Random(7)
        batches = [[round(8 + (i // 20) * 1.7 + (rng.random() - 0.5), 2)
                    for _ in range(rng.randint(1, 40))] for i in range(80)]
        res = core.analyze_decimal(batches, penalty=1.5)
        print(f"\n80批×1..40份(不等): {res.duration_sec:.2f}s (引擎 {res.engine})")
        self.assertLess(res.duration_sec, 30)
        self.assertGreaterEqual(res.num_optimal, 1)


    def test_80_batches_adversarial_sizes_under_30s(self):
        # 份数 31..40 循环：不同分数拐点最多，段代价计算最重
        rng = random.Random(3)
        batches = [[round(rng.uniform(5, 15), 2) for _ in range(31 + i % 10)]
                   for i in range(80)]
        res = core.analyze_decimal(batches, penalty=1.0)
        print(f"\n80批×31..40份(对抗): {res.duration_sec:.2f}s (引擎 {res.engine})")
        self.assertLess(res.duration_sec, 30)
        self.assertGreaterEqual(res.num_optimal, 1)


class TestBackendParity(unittest.TestCase):
    @unittest.skipUnless(core._np is not None, "numpy 未安装")
    def test_numpy_matches_pure_python(self):
        rng = random.Random(2026)
        for _ in range(15):
            n = rng.randint(3, 9)
            batches = core.normalize_batches(
                [[round(rng.uniform(4, 16), rng.randint(0, 2))
                  for _ in range(rng.randint(1, 9))] for _ in range(n)])
            curves = core._prepare(batches)
            for a in range(n):
                for b in range(a + 1, n + 1):
                    x = core._segment_cost_np(curves, a, b)
                    y = core._segment_cost_py(curves, a, b)
                    self.assertEqual(x, y, f"段[{a},{b}) 两种实现不一致")


if __name__ == "__main__":
    unittest.main()
