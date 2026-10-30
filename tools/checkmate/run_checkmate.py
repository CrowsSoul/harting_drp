# -*- coding: utf-8 -*-
"""驱动本机 NX Check-Mate 跑检查（黑盒差分取证用）。

两种通道：

* ``smoke`` —— 复用项目的 run_journal 通道执行 ``nxdrp/journals/checkmate_checker.py``，
  用 Check-Mate 自带的示例检查器（Examples_NXOpenPython_CheckDeepHoles）做许可冒烟；
* ``ug``    —— 直接调用 ``NXBIN\\ug_check_part.exe``，参数原样透传（用法见
  DESIGN_TOOLS\\checkmate\\customization\\guide.html）。

结果默认写到 ``.local/checkmate_results/``（.gitignore 保护，不入库）。

用法：
    python tools/checkmate/run_checkmate.py smoke
    python tools/checkmate/run_checkmate.py smoke --part "D:\\x.prt" --checker Examples_NXOpenPython_CheckDeepHoles
    python tools/checkmate/run_checkmate.py ug -- --help
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_CHECKER = "Examples_NXOpenPython_CheckDeepHoles"
#: 示例检查器（CheckDeepHoles）只声明了 DiameterDepthScale；LogOption 是 KF 检查器的参数
DEFAULT_PARAMETERS = {"DiameterDepthScale": 0.5}
#: 参数 ID -> 参数标题（某些 NX 版本 SetParameter 按标题定位）
PARAMETER_TITLES = {
    "DiameterDepthScale": "Diameter Depth Scale",
    "LogOption": "Log Option",
    "LogMessage": "Log Additional Message",
}


def default_part() -> str:
    """Check-Mate 自带的示例零件 DeepHole.prt（只读使用）。"""
    base = os.environ.get("UGII_BASE_DIR")
    roots = [base] if base else []
    roots += sorted(glob.glob(r"C:\Program Files\Siemens\Designcenter*"), reverse=True)
    for root in roots:
        candidate = os.path.join(
            root, "DESIGN_TOOLS", "checkmate", "examples", "NXOpenCheckerExamples",
            "Python", "CheckDeepHoles", "DeepHole.prt",
        )
        if os.path.isfile(candidate):
            return candidate
    raise SystemExit("未找到 Check-Mate 示例零件 DeepHole.prt，请用 --part 指定")


def _parse_value(text: str):
    """把命令行字符串转成检查器期望的类型（NX 会校验参数数据类型）。"""
    low = text.strip().lower()
    if low in ("true", "false"):
        return low == "true"
    if text.strip().startswith(("[", "{", '"')):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    for cast in (int, float):
        try:
            return cast(text)
        except ValueError:
            continue
    return text


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_checkmate_xml(path: str) -> dict:
    """把 Check-Mate 的 PLMXML 日志解析成结构化判定（黑盒样本的核心字段）。"""
    root = ET.parse(path).getroot()
    sample = {
        "log": path,
        "checker": "",
        "status": "",
        "parameters": {},
        "details": [],
        "messages": [],
    }
    for element in root.iter():
        tag = _local(element.tag)
        if tag == "CheckPart":
            sample["status"] = element.get("status", "")
        elif tag == "Checker":
            sample["checker"] = element.get("class", "")
            for param in element.iter():
                if _local(param.tag) == "Parameter" and param.get("title"):
                    sample["parameters"][param.get("title")] = param.get("value", "")
        elif tag == "DetailSetInfo":
            sample["details"].append(
                {"name": element.get("name", ""), "status": element.get("status", "")}
            )
        elif tag == "CheckMessageInfo" and element.text:
            message = " ".join(element.text.split())
            if message and len(sample["messages"]) < 20:
                sample["messages"].append(message)
    return sample


def _save(payload: dict, out: str | None) -> str:
    if out:
        path = Path(out)
    else:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = REPO_ROOT / ".local" / "checkmate_results" / f"smoke-{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def cmd_smoke(args) -> int:
    from nxdrp.adapters.nx_batch import NxBatchAdapter, NxConfig, NxNotAvailableError, JournalError

    part = args.part or default_part()
    # 默认参数只属于示例检查器；产品自带检查器（dfms_*）不预置任何参数
    parameters = {}
    if not args.no_params and args.checker == DEFAULT_CHECKER:
        parameters.update(DEFAULT_PARAMETERS)
    for item in args.param or []:
        key, _, value = item.partition("=")
        parameters[key.strip()] = _parse_value(value)
    request = {
        "part": part,
        "checker": args.checker,
        "parameters": parameters,
        "parameter_titles": {k: v for k, v in PARAMETER_TITLES.items() if k in parameters},
        "log_dir": str(REPO_ROOT / ".local" / "checkmate_logs" / time.strftime("%Y%m%d-%H%M%S")),
    }
    adapter = NxBatchAdapter(NxConfig())
    print(f"NX run_journal: {adapter.config.run_journal or '(未检测到)'}")
    print(f"part = {part}\nchecker = {args.checker}\nparameters = {parameters}")
    payload = {"schema_version": "1.0", "request": request, "ran_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    try:
        response = adapter.run_journal("checkmate_checker", request, timeout_s=args.timeout)
        payload["response"] = response
        payload["ok"] = True
        payload["samples"] = []
        for log in response.get("logs", []):
            if not log.lower().endswith(".xml"):
                continue
            try:
                payload["samples"].append(parse_checkmate_xml(log))
            except Exception as exc:
                payload["samples"].append({"log": log, "error": f"{type(exc).__name__}: {exc}"})
    except NxNotAvailableError as exc:
        payload.update({"ok": False, "error": f"NxNotAvailableError: {exc}"})
    except JournalError as exc:
        payload.update({"ok": False, "error": f"JournalError: {exc}", "diagnostics": exc.diagnostics})
    path = _save(payload, args.out)
    print(json.dumps(payload, ensure_ascii=False, indent=2)[:6000])
    print(f"\n样本已写出：{path}")
    return 0 if payload["ok"] else 2


def cmd_ug(args) -> int:
    base = os.environ.get("UGII_BASE_DIR") or ""
    if not base:
        matches = sorted(glob.glob(r"C:\Program Files\Siemens\Designcenter*"), reverse=True)
        base = matches[0] if matches else ""
    exe = os.path.join(base, "NXBIN", "ug_check_part.exe")
    if not os.path.isfile(exe):
        print(f"未找到 ug_check_part.exe：{exe}", file=sys.stderr)
        return 1
    command = [exe] + list(args.args or [])
    print(" ".join(command))
    proc = subprocess.run(command, capture_output=True)
    sys.stdout.write((proc.stdout or b"").decode("utf-8", "replace"))
    sys.stderr.write((proc.stderr or b"").decode("utf-8", "replace"))
    return proc.returncode


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    smoke = sub.add_parser("smoke", help="用 run_journal 跑一个 Check-Mate 检查（许可冒烟）")
    smoke.add_argument("--part", default="", help="零件路径（默认 Check-Mate 自带 DeepHole.prt）")
    smoke.add_argument("--checker", default=DEFAULT_CHECKER)
    smoke.add_argument("--param", action="append", help="检查参数 key=value，可重复")
    smoke.add_argument("--no-params", action="store_true", help="不传任何检查参数（诊断用）")
    smoke.add_argument("--timeout", type=float, default=300.0)
    smoke.add_argument("--out", default="", help="样本 JSON 输出路径（默认 .local/checkmate_results/）")
    smoke.set_defaults(func=cmd_smoke)

    ug = sub.add_parser("ug", help="直接调用 ug_check_part.exe，参数原样透传")
    ug.add_argument("args", nargs=argparse.REMAINDER)
    ug.set_defaults(func=cmd_ug)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
