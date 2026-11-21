"""命令行入口：python3 -m tea_cutpoints [--host H] [--port P]"""
from __future__ import annotations

import argparse

from .server import make_server
from .store import Store


def main():
    parser = argparse.ArgumentParser(description="茶样含水率换档点分析服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    httpd = make_server(Store(), host=args.host, port=args.port)
    host, port = httpd.server_address[:2]
    print(f"茶样含水率换档点分析：http://{host}:{port}/  (Ctrl+C 停止)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
