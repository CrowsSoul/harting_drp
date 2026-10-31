# -*- coding: utf-8 -*-
"""调用 NX ``run_journal`` 生成 PERF 参数化试验件。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess

from .nx_cae_runner import find_run_journal
from .rule_engine import PROJECT_ROOT


JOURNAL = os.path.join(PROJECT_ROOT, "nxdrp", "journals", "build_perf_geometry.py")


def run_geometry(
    request_path: str,
    response_path: str,
    *,
    run_journal: str = "",
    timeout_seconds: int = 180,
) -> dict:
    request = os.path.abspath(request_path)
    response = os.path.abspath(response_path)
    if not os.path.isfile(request):
        raise FileNotFoundError(request)
    if os.path.exists(response):
        os.remove(response)
    env = dict(os.environ)
    env["NXDRP_PERF_GEOMETRY_REQUEST"] = request
    env["NXDRP_PERF_GEOMETRY_RESPONSE"] = response
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
        raise RuntimeError(f"NX 几何 journal 失败，退出码 {proc.returncode}：{detail[-2000:]}")
    if not os.path.isfile(response):
        raise RuntimeError("NX 几何 journal 未产生响应文件")
    with open(response, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not payload.get("ok"):
        raise RuntimeError(f"NX 几何生成失败：{payload.get('error') or payload}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="按 PERF 样本参数生成 NX 试验件")
    parser.add_argument("--request", required=True)
    parser.add_argument("--response", required=True)
    parser.add_argument("--run-journal", default="")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    payload = run_geometry(
        args.request,
        args.response,
        run_journal=args.run_journal,
        timeout_seconds=args.timeout,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
