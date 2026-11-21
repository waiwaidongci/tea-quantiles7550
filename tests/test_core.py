"""核心引擎测试：小例穷举核对（并列、样本量不等）、构造并列、确定性。"""
import random
import unittest
from fractions import Fraction

from tea_cutpoints import core
from tea_cutpoints.core import DEN, analyze
from tests.oracle import brute_analyze, segment_cost


def engine_fraction(res):
    return Fraction(res.total_cost_num, res.total_cost_den)


class TestHandcrafted(unittest.TestCase):
    def test_identical_batches_all_tied_penalty0(self):
        # 全部批次相同 -> 所有段代价为 0；罚分 0 时所有合法切法并列最优
        expected = {6: (2, {3: 1}), 7: (3, {3: 1, 4: 1}),
                    8: (4, {3: 1, 4: 1, 5: 1}), 9: (6, {3: 2, 4: 1, 5: 1, 6: 2})}
        for n, (num, cuts) in expected.items():
            res = analyze([[100, 100, 100]] * n, penalty_micro=0)
            self.assertEqual(res.num_optimal, num, f"n={n}")
            self.assertEqual(res.total_cost_num, 0)
            self.assertEqual(res.cut_count_map(), {i: cuts.get(i, 0) for i in range(1, n)},
                             f"n={n}")

    def test_identical_batches_penalty_prefers_single_segment(self):
        res = analyze([[100, 100, 100]] * 9, penalty_micro=5)
        self.assertEqual(res.num_optimal, 1)          # 唯一最优：整段，零刀
        self.assertTrue(all(c == 0 for _, c in res.cut_counts))

    def test_two_clusters_unique_cut(self):
        batches = [[10, 10, 10, 10, 10]] * 3 + [[20, 20, 20, 20, 20]] * 3
        res = analyze(batches, penalty_micro=10)      # 10 < 混合段代价 30
        self.assertEqual(res.num_optimal, 1)
        self.assertEqual(res.cut_count_map().get(3), 1)
        self.assertEqual(res.total_cost_num, 10 * DEN)  # 仅一次罚分

    def test_two_clusters_zero_penalty(self):
        batches = [[10, 10, 10]] * 3 + [[20, 20, 20]] * 3
        res = analyze(batches, penalty_micro=0)
        self.assertEqual(res.num_optimal, 1)
        self.assertEqual(res.cut_count_map().get(3), 1)
        self.assertEqual(res.total_cost_num, 0)

    def test_min_segment_single_solution(self):
        res = analyze([[1, 2], [3, 4], [5, 6]], penalty_micro=0)
        self.assertEqual(res.num_optimal, 1)
        self.assertEqual(res.cut_counts, [(1, 0), (2, 0)])

    def test_unequal_sizes_vs_oracle(self):
        # 样本量不等：1,2,3,4,5 份，含并列中位数（偶数批段）
        batches = [[7], [8, 12], [9, 9, 10], [6, 14, 8, 10], [11, 7, 9, 13, 8]]
        for pen in (0, 1, 4):
            res = analyze(batches, penalty_micro=pen)
            best, num, counts = brute_analyze(batches, penalty=pen)
            self.assertEqual(engine_fraction(res), best, f"pen={pen}")
            self.assertEqual(res.num_optimal, num, f"pen={pen}")
            self.assertEqual(res.cut_count_map(), counts, f"pen={pen}")

    def test_deterministic_repeat(self):
        rng = random.Random(7)
        batches = [[rng.randint(50, 150) for _ in range(rng.randint(1, 6))]
                   for _ in range(10)]
        r1 = analyze(batches, penalty_micro=3)
        r2 = analyze(batches, penalty_micro=3)
        self.assertEqual((r1.total_cost_num, r1.num_optimal, r1.cut_counts),
                         (r2.total_cost_num, r2.num_optimal, r2.cut_counts))


class TestBruteForceRandom(unittest.TestCase):
    def test_random_small_cases(self):
        rng = random.Random(20261121)
        cases = 0
        for _ in range(220):
            n = rng.randint(3, 8)
            # 小值域制造大量并列；样本量 1..5 覆盖不等样本量
            batches = [[rng.randint(0, 12) for _ in range(rng.randint(1, 5))]
                       for _ in range(n)]
            pen = rng.choice([0, 1, 2, 5, 9])
            res = analyze(batches, penalty_micro=pen)
            best, num, counts = brute_analyze(batches, penalty=pen)
            self.assertEqual(engine_fraction(res), best, f"代价不符: {batches} pen={pen}")
            self.assertEqual(res.num_optimal, num, f"并列数不符: {batches} pen={pen}")
            self.assertEqual(res.cut_count_map(), counts, f"切点计数不符: {batches} pen={pen}")
            cases += 1
        self.assertEqual(cases, 220)

    def test_random_decimal_readings(self):
        # 带小数的读数（经微单位缩放）同样与 oracle 一致
        rng = random.Random(99)
        for _ in range(60):
            n = rng.randint(3, 7)
            raw = [[round(rng.uniform(5, 15), rng.choice([1, 2]))
                    for _ in range(rng.randint(1, 5))] for _ in range(n)]
            pen = rng.choice([0, 0.5, 2.25])
            res = core.analyze_decimal(raw, penalty=pen)
            micro = core.normalize_batches(raw)
            best, num, counts = brute_analyze(micro, penalty=core.parse_penalty(pen))
            self.assertEqual(engine_fraction(res), best)
            self.assertEqual(res.num_optimal, num)
            self.assertEqual(res.cut_count_map(), counts)


class TestValidation(unittest.TestCase):
    def test_too_few_batches(self):
        with self.assertRaises(ValueError):
            analyze([[1, 2], [3, 4]])

    def test_empty_batch_rejected(self):
        with self.assertRaises(ValueError):
            core.normalize_batches([[1, 2], []])

    def test_over_40_rejected(self):
        with self.assertRaises(ValueError):
            core.normalize_batches([[1.0] * 41])

    def test_bad_reading_rejected(self):
        for bad in ("abc", float("nan"), float("inf"), True):
            with self.assertRaises(ValueError, msg=repr(bad)):
                core.normalize_batches([[bad]])

    def test_negative_penalty_rejected(self):
        with self.assertRaises(ValueError):
            core.parse_penalty(-1)

    def test_parse_reading_exact(self):
        self.assertEqual(core.parse_reading("12.34"), 12340000)
        self.assertEqual(core.parse_reading(12.34), 12340000)
        self.assertEqual(core.parse_reading(8), 8000000)


if __name__ == "__main__":
    unittest.main()
