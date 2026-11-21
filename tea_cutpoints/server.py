"""HTTP 服务：JSON API + 单页面。仅用标准库，零 Web 依赖。

    python3 -m tea_cutpoints [--host 127.0.0.1] [--port 8000]
"""
from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .page import PAGE
from .store import Store


class _ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def make_server(store: Store, host: str = "127.0.0.1", port: int = 8000):
    routes = _build_routes(store)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "TeaCutpoints/1.0"

        # ---------- 基础工具 ----------
        def _send_json(self, obj, status=200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_page(self):
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
            if length > 20 * 1024 * 1024:
                raise _ApiError(413, "请求体过大")
            raw = self.rfile.read(length)
            try:
                return json.loads(raw.decode("utf-8"))
            except Exception:
                raise _ApiError(400, "请求体不是合法 JSON")

        def log_message(self, *args):  # 静默访问日志
            pass

        # ---------- 分发 ----------
        def _dispatch(self, method):
            try:
                path = self.path.split("?", 1)[0].rstrip("/") or "/"
                if method == "GET" and path == "/":
                    return self._send_page()
                body = self._read_json() if method in ("POST", "PUT") else None
                for m, pattern, func in routes:
                    if m != method:
                        continue
                    match = re.fullmatch(pattern, path)
                    if match:
                        return self._send_json(func(body, **match.groupdict()))
                raise _ApiError(404, "接口不存在")
            except _ApiError as e:
                self._send_json({"error": e.message}, e.status)
            except KeyError as e:
                self._send_json({"error": str(e).strip("'")}, 404)
            except (ValueError, TypeError) as e:
                self._send_json({"error": str(e)}, 422)
            except Exception as e:  # 兜底，保证连接可恢复
                self._send_json({"error": f"服务器内部错误: {e}"}, 500)

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_PUT(self):
            self._dispatch("PUT")

        def do_DELETE(self):
            self._dispatch("DELETE")

    return ThreadingHTTPServer((host, port), Handler)


def _int(name):
    return rf"(?P<{name}>\d+)"


def _build_routes(store: Store):
    return [
        ("GET", r"/api/health", lambda body: {"status": "ok"}),
        ("GET", r"/api/studies", lambda body: {"studies": store.list_studies()}),
        ("POST", r"/api/studies", lambda body: store.create_study(
            body.get("name", ""), body.get("batches", []), body.get("penalty", 0))),
        ("GET", rf"/api/studies/{_int('sid')}",
         lambda body, sid: store.get_study(int(sid))),
        ("PUT", rf"/api/studies/{_int('sid')}",
         lambda body, sid: store.update_study(int(sid), name=body.get("name"),
                                              penalty=body.get("penalty"))),
        ("PUT", rf"/api/studies/{_int('sid')}/batches",
         lambda body, sid: store.replace_batches(int(sid), body.get("batches", []))),
        ("POST", rf"/api/studies/{_int('sid')}/batches",
         lambda body, sid: store.add_batch(int(sid), body.get("readings", []))),
        ("PUT", rf"/api/studies/{_int('sid')}/batches/{_int('idx')}",
         lambda body, sid, idx: store.update_batch(int(sid), int(idx),
                                                   body.get("readings", []))),
        ("DELETE", rf"/api/studies/{_int('sid')}/batches/{_int('idx')}",
         lambda body, sid, idx: store.delete_batch(int(sid), int(idx))),
        ("POST", rf"/api/studies/{_int('sid')}/move",
         lambda body, sid: store.move_batch(int(sid), int(body.get("from", -1)),
                                            int(body.get("to", -1)))),
        ("POST", rf"/api/studies/{_int('sid')}/runs",
         lambda body, sid: store.request_run(int(sid))),
        ("GET", rf"/api/studies/{_int('sid')}/runs/{_int('rid')}",
         lambda body, sid, rid: store.get_run(int(sid), int(rid))),
        ("POST", rf"/api/studies/{_int('sid')}/runs/{_int('rid')}/rerun",
         lambda body, sid, rid: store.request_run(int(sid), rerun_of=int(rid))),
    ]
