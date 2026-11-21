"""研究存储与任务队列：并发改样/调序时，排队并冻结同一时点的顺序、读数和罚分。

设计要点
--------
- 所有改动（编辑读数、增删批次、调序、调罚分）与“发起计算”都抢同一把锁，
  因此每次运行在入队瞬间原子地冻结一份完整快照（批次顺序 + 全部读数 + 罚分），
  快照要么包含某次改动、要么不包含，绝不会出现半改半算的混杂输入。
- 计算任务排入单个 worker 的 FIFO 队列，逐个执行；运行期间继续发生的改动
  只影响研究的“当前状态”，不会改写已冻结的快照。
- 引擎是确定性的：同一冻结输入重跑，切点计数必然一致；重跑接口显式复核这一点。
"""
from __future__ import annotations

import copy
import hashlib
import json
import queue
import threading
import time

from . import core


def _snapshot_hash(snapshot: dict) -> str:
    blob = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


class Store:
    def __init__(self, compute_hook=None):
        self._lock = threading.RLock()
        self._studies = {}          # id -> study
        self._next_study_id = 1
        self._queue = queue.Queue()
        self._compute_hook = compute_hook  # 测试注入：每次计算前调用（如 sleep）
        self._worker = threading.Thread(target=self._work_loop, daemon=True,
                                        name="cutpoints-worker")
        self._worker.start()

    # ------------------------------------------------------------ 研究维护

    def create_study(self, name: str, batches, penalty=0) -> dict:
        batches_micro = core.normalize_batches(batches)
        penalty_micro = core.parse_penalty(penalty)
        if len(batches_micro) < core.MIN_SEGMENT:
            raise ValueError(
                f"共 {len(batches_micro)} 批，不足每段最少 {core.MIN_SEGMENT} 批，无法切段")
        with self._lock:
            sid = self._next_study_id
            self._next_study_id += 1
            study = {
                "id": sid,
                "name": (name or "").strip() or f"研究 {sid}",
                "created_at": time.time(),
                "penalty_micro": penalty_micro,
                "batches": [list(b) for b in batches_micro],  # 顺序即送检顺序
                "runs": {},
                "run_order": [],
                "next_run_id": 1,
            }
            self._studies[sid] = study
            return self._study_json(study)

    def list_studies(self) -> list:
        with self._lock:
            return [self._study_json(s, with_batches=False)
                    for s in sorted(self._studies.values(), key=lambda x: x["id"])]

    def get_study(self, sid: int) -> dict:
        with self._lock:
            return self._study_json(self._require(sid))

    def update_study(self, sid: int, name=None, penalty=None) -> dict:
        with self._lock:
            st = self._require(sid)
            if name is not None:
                name = str(name).strip()
                if not name:
                    raise ValueError("研究名称不能为空")
                st["name"] = name
            if penalty is not None:
                st["penalty_micro"] = core.parse_penalty(penalty)
            return self._study_json(st)

    def replace_batches(self, sid: int, batches) -> dict:
        batches_micro = core.normalize_batches(batches)
        with self._lock:
            st = self._require(sid)
            st["batches"] = [list(b) for b in batches_micro]
            return self._study_json(st)

    def add_batch(self, sid: int, readings) -> dict:
        (batch,) = core.normalize_batches([readings])
        with self._lock:
            st = self._require(sid)
            st["batches"].append(list(batch))
            return self._study_json(st)

    def update_batch(self, sid: int, index: int, readings) -> dict:
        (batch,) = core.normalize_batches([readings])
        with self._lock:
            st = self._require(sid)
            if not 0 <= index < len(st["batches"]):
                raise KeyError("批次序号不存在")
            st["batches"][index] = list(batch)
            return self._study_json(st)

    def delete_batch(self, sid: int, index: int) -> dict:
        with self._lock:
            st = self._require(sid)
            if not 0 <= index < len(st["batches"]):
                raise KeyError("批次序号不存在")
            st["batches"].pop(index)
            return self._study_json(st)

    def move_batch(self, sid: int, src: int, dst: int) -> dict:
        """调序：把第 src 批移动到第 dst 位（0 基）。"""
        with self._lock:
            st = self._require(sid)
            n = len(st["batches"])
            if not (0 <= src < n and 0 <= dst < n):
                raise KeyError("批次序号不存在")
            batch = st["batches"].pop(src)
            st["batches"].insert(dst, batch)
            return self._study_json(st)

    # ------------------------------------------------------------ 运行

    def request_run(self, sid: int, rerun_of: int = None) -> dict:
        """冻结当前（或指定历史运行的）输入快照，排队一个计算任务。"""
        with self._lock:
            st = self._require(sid)
            if rerun_of is None:
                snapshot = {
                    "batches": copy.deepcopy(st["batches"]),
                    "penalty_micro": st["penalty_micro"],
                    "min_segment": core.MIN_SEGMENT,
                }
            else:
                orig = st["runs"].get(rerun_of)
                if orig is None:
                    raise KeyError("原运行不存在")
                snapshot = copy.deepcopy(orig["snapshot"])  # 用冻结输入重跑
            if len(snapshot["batches"]) < snapshot["min_segment"]:
                raise ValueError(
                    f"共 {len(snapshot['batches'])} 批，不足每段最少 "
                    f"{snapshot['min_segment']} 批，无法切段")
            rid = st["next_run_id"]
            st["next_run_id"] += 1
            run = {
                "id": rid,
                "study_id": sid,
                "status": "queued",
                "created_at": time.time(),
                "started_at": None,
                "finished_at": None,
                "snapshot": snapshot,
                "input_sha256": _snapshot_hash(snapshot),
                "rerun_of": rerun_of,
                "consistent": None,
                "result": None,
                "error": "",
            }
            st["runs"][rid] = run
            st["run_order"].append(rid)
            self._queue.put((sid, rid))
            return self._run_json(run)

    def get_run(self, sid: int, rid: int) -> dict:
        with self._lock:
            st = self._require(sid)
            run = st["runs"].get(rid)
            if run is None:
                raise KeyError("运行不存在")
            return self._run_json(run)

    # ------------------------------------------------------------ worker

    def _work_loop(self):
        while True:
            sid, rid = self._queue.get()
            run = None
            try:
                with self._lock:
                    st = self._studies.get(sid)
                    if st is None or rid not in st["runs"]:
                        continue
                    run = st["runs"][rid]
                    run["status"] = "running"
                    run["started_at"] = time.time()
                    snapshot = copy.deepcopy(run["snapshot"])
                if self._compute_hook is not None:
                    self._compute_hook()
                result = core.analyze(
                    snapshot["batches"],
                    snapshot["penalty_micro"],
                    snapshot.get("min_segment", core.MIN_SEGMENT),
                )
                with self._lock:
                    run["status"] = "completed"
                    run["finished_at"] = time.time()
                    run["result"] = result
                    if run["rerun_of"] is not None:
                        orig = st["runs"][run["rerun_of"]]
                        run["consistent"] = bool(
                            orig["result"] is not None
                            and orig["result"].num_optimal == result.num_optimal
                            and orig["result"].cut_counts == result.cut_counts
                        )
            except Exception as exc:  # 计算失败保留错误，不拖垮队列
                if run is not None:
                    with self._lock:
                        run["status"] = "failed"
                        run["finished_at"] = time.time()
                        run["error"] = str(exc)
            finally:
                self._queue.task_done()

    # ------------------------------------------------------------ 序列化

    def _require(self, sid: int) -> dict:
        st = self._studies.get(sid)
        if st is None:
            raise KeyError("研究不存在")
        return st

    def _study_json(self, st: dict, with_batches: bool = True) -> dict:
        out = {
            "id": st["id"],
            "name": st["name"],
            "created_at": st["created_at"],
            "penalty": core.micro_to_str(st["penalty_micro"]),
            "n_batches": len(st["batches"]),
            "runs": [self._run_json(st["runs"][rid], with_result=False)
                     for rid in st["run_order"]],
        }
        if with_batches:
            out["batches"] = [
                {"index": i, "size": len(b),
                 "readings": [core.micro_to_str(v) for v in b]}
                for i, b in enumerate(st["batches"])
            ]
        return out

    def _run_json(self, run: dict, with_result: bool = True) -> dict:
        out = {
            "id": run["id"],
            "study_id": run["study_id"],
            "status": run["status"],
            "created_at": run["created_at"],
            "started_at": run["started_at"],
            "finished_at": run["finished_at"],
            "input_sha256": run["input_sha256"],
            "rerun_of": run["rerun_of"],
            "consistent": run["consistent"],
            "error": run["error"],
            "n_batches": len(run["snapshot"]["batches"]),
            "penalty": core.micro_to_str(run["snapshot"]["penalty_micro"]),
        }
        if run["result"] is not None:
            a = run["result"]
            out["result_summary"] = {
                "num_optimal": str(a.num_optimal),
                "total_cost": a.total_cost_decimal(),
                "duration_sec": round(a.duration_sec, 3),
            }
            if with_result:
                out["result"] = analysis_json(a)
        return out


def analysis_json(a: core.Analysis) -> dict:
    return {
        "n_batches": a.n_batches,
        "min_segment": a.min_segment,
        "penalty": core.micro_to_str(a.penalty_micro),
        "total_cost": a.total_cost_decimal(),
        "total_cost_fraction": f"{a.total_cost_num}/{a.total_cost_den}",
        "num_optimal": str(a.num_optimal),
        "cut_counts": [{"position": p, "count": str(c)} for p, c in a.cut_counts],
        "engine": a.engine,
        "duration_sec": round(a.duration_sec, 3),
    }
