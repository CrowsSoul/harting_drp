# -*- coding: utf-8 -*-
"""通过统一的 NX 批处理适配器执行 PERF Simcenter journal。"""

from __future__ import annotations

import argparse
import json
import os

from ...adapters.nx_batch import NxBatchAdapter, NxConfig, detect_run_journal
from ...errors import AdapterError


DEFAULT_SOLVE_TIMEOUT_S = 4 * 60 * 60


def find_run_journal(explicit: str = "") -> str:
    path = os.path.abspath(explicit) if explicit else detect_run_journal()
    if not path or not os.path.isfile(path):
        raise FileNotFoundError("找不到 run_journal.exe；请设置 UGII_BASE_DIR 或传 --run-journal")
    return path


def run_nx_journal(
    journal: str,
    request_path: str,
    response_path: str,
    *,
    run_journal: str = "",
    timeout_seconds: int = 900,
) -> dict:
    """执行一个 NX journal，并把阶段响应保留在调用方指定位置。"""
    request = os.path.abspath(request_path)
    if not os.path.isfile(request):
        raise FileNotFoundError(request)
    with open(request, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    adapter = NxBatchAdapter(NxConfig(
        run_journal=find_run_journal(run_journal),
        timeout_s=float(timeout_seconds),
    ))
    try:
        return adapter.run_journal(
            journal,
            payload,
            timeout_s=float(timeout_seconds),
            response_path=os.path.abspath(response_path),
        )
    except AdapterError as exc:
        raise RuntimeError(str(exc)) from exc


def run_nx_case(
    request_path: str,
    response_path: str,
    *,
    run_journal: str = "",
    timeout_seconds: int = 900,
) -> dict:
    return run_nx_journal(
        "create_simcenter_case",
        request_path,
        response_path,
        run_journal=run_journal,
        timeout_seconds=timeout_seconds,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="调用 NX 创建 Simcenter FEM/SIM 容器")
    parser.add_argument("--request", required=True)
    parser.add_argument("--response", required=True)
    parser.add_argument("--run-journal", default="")
    parser.add_argument("--timeout", type=int, default=900)
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
