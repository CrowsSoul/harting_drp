# -*- coding: utf-8 -*-
"""调用 NX ``run_journal`` 创建 Simcenter CAE 容器。

该程序只负责进程调用和结果读取，不修改许可证。若 NX 许可证无效，
``run_journal`` 会直接失败并把错误写入 stderr。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess

from .rule_engine import PROJECT_ROOT


JOURNAL = os.path.join(PROJECT_ROOT, "nxdrp", "journals", "create_simcenter_case.py")


def find_run_journal(explicit: str = "") -> str:
    if explicit:
        path = os.path.abspath(explicit)
    else:
        base = os.environ.get("UGII_BASE_DIR", "")
        path = os.path.join(base, "NXBIN", "run_journal.exe") if base else ""
    if not path or not os.path.isfile(path):
        raise FileNotFoundError("找不到 run_journal.exe；请设置 UGII_BASE_DIR 或传 --run-journal")
    return path


def run_nx_case(
    request_path: str,
    response_path: str,
    *,
    run_journal: str = "",
    timeout_seconds: int = 180,
) -> dict:
    """执行 journal，返回 response JSON。超时或 NX 失败时抛 RuntimeError。"""
    request = os.path.abspath(request_path)
    response = os.path.abspath(response_path)
    if not os.path.isfile(request):
        raise FileNotFoundError(request)
    if os.path.exists(response):
        os.remove(response)
    env = dict(os.environ)
    env["NXDRP_CAE_REQUEST"] = request
    env["NXDRP_CAE_RESPONSE"] = response
    proc = subprocess.run(
        [find_run_journal(run_journal), JOURNAL],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"run_journal 失败，退出码 {proc.returncode}：{detail[-2000:]}")
    if not os.path.isfile(response):
        raise RuntimeError("run_journal 成功退出但没有写响应文件")
    with open(response, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not payload.get("ok"):
        raise RuntimeError(f"NX CAE journal 失败：{payload.get('error') or payload}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="调用 NX 创建 Simcenter FEM/SIM 容器")
    parser.add_argument("--request", required=True)
    parser.add_argument("--response", required=True)
    parser.add_argument("--run-journal", default="")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    payload = run_nx_case(
        args.request,
        args.response,
        run_journal=args.run_journal,
        timeout_seconds=args.timeout,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
