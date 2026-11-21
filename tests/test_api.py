"""API 测试：页面链路（待算->完成->切点次数）、冻结快照、并发改动、冻结重跑一致。"""
import hashlib
import json
import threading
import time
import unittest
import urllib.error
import urllib.request

from tea_cutpoints import core
from tea_cutpoints.server import make_server
from tea_cutpoints.store import Store


def canonical_hash(snapshot):
    blob = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


class ApiCase(unittest.TestCase):
    compute_hook = None  # 子类可覆盖

    @classmethod
    def setUpClass(cls):
        cls.store = Store(compute_hook=cls.compute_hook)
        cls.httpd = make_server(cls.store, "127.0.0.1", 0)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def req(self, method, path, body=None):
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data,
            headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode() or "{}")

    def wait_run(self, sid, rid, timeout=30):
        deadline = time.time() + timeout
        while time.time() < deadline:
            status, run = self.req("GET", f"/api/studies/{sid}/runs/{rid}")
            self.assertEqual(status, 200)
            if run["status"] in ("completed", "failed"):
                return run
            time.sleep(0.05)
        self.fail("运行超时未完成")

    def create(self, batches, penalty="0.5", name="测试研究"):
        status, st = self.req("POST", "/api/studies",
                              {"name": name, "penalty": penalty, "batches": batches})
        assert status == 200, st
        return st


class TestFlow(ApiCase):
    def test_page_served(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/", timeout=10) as resp:
            html = resp.read().decode()
        self.assertIn("茶样含水率换档点分析", html)

    def test_full_flow_pending_to_counts(self):
        st = self.create([[8.01, 8.1, 8.05], [8.2, 8.15, 8.18], [8.1, 8.0, 8.22],
                          [11.3, 11.5, 11.4], [11.2, 11.6, 11.4], [11.5, 11.3, 11.45]])
        sid = st["id"]
        status, run = self.req("POST", f"/api/studies/{sid}/runs")
        self.assertEqual(status, 200)
        self.assertEqual(run["status"], "queued")          # 待算
        run = self.wait_run(sid, run["id"])
        self.assertEqual(run["status"], "completed")
        res = run["result"]
        # 与引擎直接计算一致
        expect = core.analyze_decimal(
            [[8.01, 8.1, 8.05], [8.2, 8.15, 8.18], [8.1, 8.0, 8.22],
             [11.3, 11.5, 11.4], [11.2, 11.6, 11.4], [11.5, 11.3, 11.45]],
            penalty=0.5)
        self.assertEqual(int(res["num_optimal"]), expect.num_optimal)
        self.assertEqual({c["position"]: int(c["count"]) for c in res["cut_counts"]},
                         expect.cut_count_map())
        self.assertEqual(res["min_segment"], 3)

    def test_rerun_frozen_consistent(self):
        st = self.create([[1, 2, 3], [2, 3, 4], [3, 4, 5], [9, 9, 9], [9, 8, 10], [8, 9, 9]],
                         penalty="1")
        sid = st["id"]
        _, run = self.req("POST", f"/api/studies/{sid}/runs")
        run = self.wait_run(sid, run["id"])
        # 改样 + 调序 + 调罚分（不影响已完成的冻结结果）
        self.req("PUT", f"/api/studies/{sid}/batches/0", {"readings": [50, 51]})
        self.req("POST", f"/api/studies/{sid}/move", {"from": 0, "to": 5})
        self.req("PUT", f"/api/studies/{sid}", {"penalty": "9.5"})
        # 用冻结输入重跑：切点计数必须保持一致
        _, re_run = self.req("POST", f"/api/studies/{sid}/runs/{run['id']}/rerun")
        re_run = self.wait_run(sid, re_run["id"])
        self.assertEqual(re_run["status"], "completed")
        self.assertTrue(re_run["consistent"])
        self.assertEqual(re_run["input_sha256"], run["input_sha256"])
        self.assertEqual(re_run["result"]["cut_counts"], run["result"]["cut_counts"])
        self.assertEqual(re_run["result"]["num_optimal"], run["result"]["num_optimal"])

    def test_validation_errors(self):
        status, _ = self.req("POST", "/api/studies",
                             {"name": "x", "penalty": "0", "batches": [[1, 2], [3, 4]]})
        self.assertEqual(status, 422)                      # 不足三批
        status, _ = self.req("POST", "/api/studies",
                             {"name": "x", "penalty": "-1",
                              "batches": [[1], [2], [3]]})
        self.assertEqual(status, 422)                      # 负罚分
        status, _ = self.req("POST", "/api/studies",
                             {"name": "x", "penalty": "0",
                              "batches": [[1.0] * 41, [2], [3]]})
        self.assertEqual(status, 422)                      # 超过40份
        status, _ = self.req("GET", "/api/studies/9999")
        self.assertEqual(status, 404)
        st = self.create([[1], [2], [3], [4]], penalty="0")
        sid = st["id"]
        self.req("DELETE", f"/api/studies/{sid}/batches/0")
        self.req("DELETE", f"/api/studies/{sid}/batches/0")
        status, err = self.req("POST", f"/api/studies/{sid}/runs")
        self.assertEqual(status, 422)                      # 删到不足三批后拒算


class TestFreezeConcurrency(ApiCase):
    """并发改样/调序：运行冻结同一时点的顺序、读数和罚分。"""

    compute_hook = staticmethod(lambda: time.sleep(0.5))  # 拖慢计算，制造并发窗口

    A = [[8.0, 8.1, 8.2], [8.3, 8.2, 8.1], [8.15, 8.05, 8.25],
         [11.4, 11.5, 11.3], [11.6, 11.4, 11.5], [11.35, 11.45, 11.55]]
    B = [[5.0, 5.1], [5.2, 5.0], [5.1, 5.2], [9.0, 9.1], [9.2, 9.0], [9.1, 9.2]]

    def test_snapshot_frozen_while_editing(self):
        st = self.create(self.A, penalty="0.5")
        sid = st["id"]
        _, run1 = self.req("POST", f"/api/studies/{sid}/runs")
        # 计算进行中：改样、调序、调罚分
        self.req("PUT", f"/api/studies/{sid}/batches",
                 {"batches": self.B})
        self.req("PUT", f"/api/studies/{sid}", {"penalty": "3"})
        _, run2 = self.req("POST", f"/api/studies/{sid}/runs")
        self.req("PUT", f"/api/studies/{sid}/batches/0", {"readings": [7.7, 7.8, 7.9]})

        run1 = self.wait_run(sid, run1["id"])
        run2 = self.wait_run(sid, run2["id"])
        self.assertEqual(run1["status"], "completed")
        self.assertEqual(run2["status"], "completed")

        # run1 对应冻结的 A/0.5，run2 对应冻结的 B/3 —— 与引擎直接核算一致
        exp1 = core.analyze_decimal(self.A, penalty=0.5)
        exp2 = core.analyze_decimal(self.B, penalty=3)
        self.assertEqual(int(run1["result"]["num_optimal"]), exp1.num_optimal)
        self.assertEqual({c["position"]: int(c["count"]) for c in run1["result"]["cut_counts"]},
                         exp1.cut_count_map())
        self.assertEqual(int(run2["result"]["num_optimal"]), exp2.num_optimal)
        self.assertEqual({c["position"]: int(c["count"]) for c in run2["result"]["cut_counts"]},
                         exp2.cut_count_map())

        # 冻结输入的 SHA256 与请求时点状态吻合
        snap1 = {"batches": core.normalize_batches(self.A),
                 "penalty_micro": core.parse_penalty("0.5"), "min_segment": 3}
        snap2 = {"batches": core.normalize_batches(self.B),
                 "penalty_micro": core.parse_penalty("3"), "min_segment": 3}
        self.assertEqual(run1["input_sha256"], canonical_hash(snap1))
        self.assertEqual(run2["input_sha256"], canonical_hash(snap2))
        self.assertNotEqual(run1["input_sha256"], run2["input_sha256"])

        # 两个任务排队串行执行：run2 在 run1 完成后才开始
        self.assertGreaterEqual(run2["started_at"], run1["finished_at"])


if __name__ == "__main__":
    unittest.main()
