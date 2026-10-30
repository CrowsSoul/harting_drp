# -*- coding: utf-8 -*-
"""在 NX 进程内执行 Check-Mate 检查器的 journal（取证 / 黑盒差分用）。

不要在本文件里 import nxdrp —— NX 用它自带的 Python，宿主 sys.path 不可见。
通信沿用项目约定（与 extract_geometry.py 相同）：

    输入  NXDRP_NX_REQUEST   {"part": "...prt", "checker": "Examples_NXOpenPython_CheckDeepHoles",
                              "parameters": {"DiameterDepthScale": 0.5},
                              "log_dir": "D:\\logs"}
    输出  NXDRP_NX_RESPONSE  {"ok": true, "results": [...], "logs": [...], "diagnostics": {...}}

调用口径来自 Check-Mate 自带文档
（DESIGN_TOOLS\\checkmate\\python\\CheckerExecutor.txt 与 examples 下的示例流程），
代码为本项目自写；Siemens 的示例源码不复制进仓库。

调试时可手动运行：
    set NXDRP_NX_REQUEST=D:\\req.json
    set NXDRP_NX_RESPONSE=D:\\resp.json
    "%UGII_BASE_DIR%\\NXBIN\\run_journal.exe" nxdrp\\journals\\checkmate_checker.py
"""

import glob
import json
import os
import sys
import time
import traceback

REQ_PATH = os.environ.get("NXDRP_NX_REQUEST", "")
RESP_PATH = os.environ.get("NXDRP_NX_RESPONSE", "")


def _read_request():
    with open(REQ_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_response(payload):
    with open(RESP_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)


def _checkmate_dirs():
    """返回需要加入 sys.path 的 Check-Mate 目录。"""
    base = os.environ.get("UGII_BASE_DIR", "")
    if not base:
        raise RuntimeError("UGII_BASE_DIR 未设置")
    checkmate = os.path.join(base, "DESIGN_TOOLS", "checkmate")
    return [
        os.path.join(checkmate, "python"),
        os.path.join(checkmate, "examples", "NXOpenCheckerExamples", "Python", "CheckDeepHoles"),
    ]


def _capture_validator(executor, response):
    """尽量把 Check-Mate 的判定结果从 validator 上读出来（不同版本 API 有差异）。

    读不到不视为失败：日志文件与诊断信息仍可作证据；黑盒差分会以能读到的最细粒度为准。
    """
    info = {}
    try:
        validator = getattr(executor, "validator", None)
        info["validator_type"] = type(validator).__name__ if validator is not None else ""
        info["validator_attrs"] = [a for a in dir(validator) if not a.startswith("_")][:80] if validator is not None else []
        for name in (
            "GetCheckerNodes", "GetPartNodes", "GetLastErrorListFromCommit",
            "GetResults", "GetCheckerResults", "GetPartResults", "GetValidationResults",
        ):
            fn = getattr(validator, name, None)
            if not callable(fn):
                continue
            try:
                info[name] = repr(fn())[:4000]
            except Exception as exc:  # 记录签名不匹配，继续尝试其它方法
                info[name] = f"ERR {type(exc).__name__}: {exc}"
    except Exception as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"
    response["diagnostics"]["validator"] = info


def _fresh_log_files(directory, since):
    pattern = os.path.join(directory, "*")
    out = []
    for path in glob.glob(pattern):
        try:
            if os.path.isfile(path) and os.path.getmtime(path) >= since - 1.0:
                out.append(path)
        except OSError:
            continue
    return sorted(out)


def main():
    t0 = time.time()
    response = {"ok": False, "results": [], "logs": [], "diagnostics": {}}
    try:
        request = _read_request()
        part = request["part"]
        checker = request["checker"]
        parameters = request.get("parameters") or {}
        log_dir = request.get("log_dir") or os.path.join(os.path.dirname(part), "checkmate_logs")
        os.makedirs(log_dir, exist_ok=True)
        response["diagnostics"].update(
            {"part": part, "checker": checker, "parameters": parameters, "log_dir": log_dir}
        )

        for path in _checkmate_dirs():
            if os.path.isdir(path) and path not in sys.path:
                sys.path.insert(0, path)

        import NXOpen  # noqa: F401  （CheckerExecutor 依赖）
        from CheckerExecutor import CheckerExecutor

        CheckerExecutor.InitValidatorOptions()
        options = CheckerExecutor.GetValidatorOptions()
        options.GenerateLogFile = True
        options.LogFileDirectory = log_dir
        options.LogFileMode = NXOpen.Validate.ValidatorOptions.LogModeTypes.LogPerPart

        executor = CheckerExecutor().AddChecker(checker).AddPart(part)
        titles = request.get("parameter_titles") or {}
        for key, value in parameters.items():
            try:
                executor = executor.SetParameter(key, value)
            except KeyError:
                # 某些版本按 AddParameter 的第一个字符串（参数标题）定位
                title = titles.get(key)
                if not title:
                    raise
                executor = executor.SetParameter(title, value)
        executor.Commit()

        _capture_validator(executor, response)
        logs = _fresh_log_files(log_dir, t0)
        response["logs"] = logs
        for path in logs:
            try:
                size = os.path.getsize(path)
            except OSError:
                size = -1
            # 结构化解析交给宿主侧工具（tools/checkmate/run_checkmate.py），这里只报路径与大小
            response["results"].append(
                {"checker": checker, "source": os.path.basename(path), "size": size}
            )
        response["ok"] = True
    except Exception as exc:  # 任何失败都要写响应文件，宿主才拿得到诊断
        response["error"] = f"{type(exc).__name__}: {exc}"
        response["diagnostics"]["traceback_tail"] = traceback.format_exc()[-3000:]
    finally:
        response["diagnostics"]["elapsed_s"] = round(time.time() - t0, 1)
        response["run_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        try:
            _write_response(response)
        except Exception:
            pass


if __name__ == "__main__":
    main()
