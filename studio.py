"""Start the local studio with its in-process native inference engines."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import socket
import threading
import webbrowser


def main():
    parser = argparse.ArgumentParser(description="明 · 本地语音工作台")
    parser.add_argument("--port", type=int)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--data", type=Path)
    args = parser.parse_args()
    if args.data:
        os.environ["MING_T8_DATA"] = str(args.data.resolve())
    from ming_t8.config import configuration
    import uvicorn
    settings = configuration()
    port = args.port or settings["port"]
    host = "127.0.0.1"
    try:
        with socket.socket() as probe:
            probe.bind((host, port))
    except OSError:
        raise SystemExit(f"端口{port}已被占用。已有工作台请直接打开http://{host}:{port}，或使用--port选择其他端口。")
    url = f"http://{host}:{port}"
    print(f"\n明 · 本地语音工作台\n{url}\n模型按需加载；关闭此窗口可结束工作台。\n", flush=True)
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run("ming_t8.server:create_app", factory=True, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
