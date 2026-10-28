"""双击启动脚本的后端：选端口、复用已在跑的实例、起服务、自动打开浏览器。

由仓库根目录的 ``启动平台.cmd`` 调用；也可以手动跑：

    .venv\\Scripts\\python.exe tools\\launch_platform.py [端口]

之所以把这套逻辑放在 Python 里，是因为纯 .cmd 既要挑空闲端口、又要等
``/api/health`` 就绪再开浏览器，批处理写起来既难读也容易在中文路径上出错。
"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

# 直接双击 .cmd 时 sys.path[0] 是 tools\，把仓库根目录补进去才能 import nxdrp。
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 8000 常被 C-Lodop 打印服务占用，所以按顺序尝试，第一个空闲的就用。
CANDIDATE_PORTS = (8000, 8010, 8020, 8030, 8040, 8050, 8060)
PROVIDER = "nxdrp.checkers.report:generate_report"


def probe(port: int, timeout: float = 1.0) -> dict | None:
    """返回本平台的 /api/health；端口上不是本平台就返回 None。"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=timeout) as response:
            if response.status != 200:
                return None
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    # status 之外再要求 nx_slots：占着同一端口的其他 Web 服务不会返回这个字段。
    if payload.get("status") != "ok" or "nx_slots" not in payload:
        return None
    return payload


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def browser_enabled() -> bool:
    """NXDRP_NO_BROWSER=1 时不自动开浏览器（服务器/无界面环境用）。"""
    return os.environ.get("NXDRP_NO_BROWSER", "").strip().lower() not in {"1", "true", "yes"}


def open_browser_when_ready(port: int, timeout: float = 90.0) -> None:
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if probe(port) is not None:
            if browser_enabled():
                webbrowser.open(url)
                print(f"[平台] 浏览器已打开：{url}", flush=True)
            else:
                print(f"[平台] 服务已就绪：{url}", flush=True)
            return
        time.sleep(0.4)
    print(f"[平台] 没能确认服务就绪，请手动打开 {url}", flush=True)


def parse_port(argv: list[str]) -> int | None:
    for raw in argv[1:]:
        text = raw.lstrip("-")
        if text.lower().startswith("port="):
            text = text[5:]
        try:
            value = int(text)
        except ValueError:
            print(f"[平台] 忽略无法识别的参数：{raw}", flush=True)
            continue
        if not 1024 <= value <= 65535:
            print(f"[平台] 端口超出范围：{value}", flush=True)
            continue
        return value
    return None


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    wanted = parse_port(argv)
    ports = ([wanted] if wanted else []) + [p for p in CANDIDATE_PORTS if p != wanted]

    # 已经跑着一份就别再起第二个：同一个数据目录起第二个进程会被 SQLite 锁拒绝。
    for port in ports:
        payload = probe(port)
        if payload is not None:
            print(f"[平台] 平台已经在运行：http://127.0.0.1:{port}", flush=True)
            if browser_enabled():
                webbrowser.open(f"http://127.0.0.1:{port}")
            return 0

    port = next((p for p in ports if port_free(p)), None)
    if port is None:
        print("[平台] 8000-8060 都被占用。关掉占用端口的程序，或指定端口：", flush=True)
        print("       启动平台.cmd 8123", flush=True)
        return 1

    os.environ.setdefault("NXDRP_REPORT_PROVIDER", PROVIDER)

    import uvicorn

    from nxdrp.checkers.platform_web.backend._server import create_app

    url = f"http://127.0.0.1:{port}"
    print("=" * 62, flush=True)
    print(f"  HARTING 设计检查平台   {url}", flush=True)
    print(f"  接口文档               {url}/docs", flush=True)
    print("  看到下面出现 Uvicorn running on 就是启动成功。", flush=True)
    print("  浏览器会自动打开；关掉这个窗口就等于停止服务。", flush=True)
    print("=" * 62, flush=True)

    threading.Thread(target=open_browser_when_ready, args=(port,), daemon=True).start()
    try:
        uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="info")
    except OSError as exc:
        print(f"[平台] 端口 {port} 启动失败：{exc}", flush=True)
        return 1
    except KeyboardInterrupt:
        pass
    print("[平台] 服务已停止。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
