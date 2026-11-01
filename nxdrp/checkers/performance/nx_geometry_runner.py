# -*- coding: utf-8 -*-
"""调用 NX ``run_journal`` 生成 PERF 参数化试验件。"""

from __future__ import annotations

import argparse
import json

from .nx_cae_runner import run_nx_journal


def run_geometry(
    request_path: str,
    response_path: str,
    *,
    run_journal: str = "",
    timeout_seconds: int = 900,
) -> dict:
    return run_nx_journal(
        "build_perf_geometry",
        request_path,
        response_path,
        run_journal=run_journal,
        timeout_seconds=timeout_seconds,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="按 PERF 样本参数生成 NX 试验件")
    parser.add_argument("--request", required=True)
    parser.add_argument("--response", required=True)
    parser.add_argument("--run-journal", default="")
    parser.add_argument("--timeout", type=int, default=900)
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
