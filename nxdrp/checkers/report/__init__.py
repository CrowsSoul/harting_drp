"""报告与知识库，仅消费检查结果。"""
import shutil
from pathlib import Path

__version__ = "1.1.0"
CHECKERS = []


def _generate(*args, **kwargs):
    from .service import generate_report as generate
    return generate(*args, **kwargs)


def generate_report(*args, **kwargs):
    """生成报告。两种调用方式都支持：

    1. 平台内部（报告 原生）：
       ``generate_report(check_run, "report_archives", model=..., rules=...)``
       返回归档目录信息。

    2. Web 平台对接（见 nxdrp/checkers/platform_web/backend/_service.py）：
       ``generate_report(result=..., model=..., rulebook=..., output_path=".../report.pdf")``
       生成后把报告文件复制到 ``output_path``，平台 据此提供下载。
    """
    if "result" in kwargs and "payload" not in kwargs:
        kwargs["payload"] = kwargs.pop("result")
    if "rulebook" in kwargs:
        kwargs["rules"] = kwargs.pop("rulebook")
    target = kwargs.pop("output_path", None)
    if target is None:
        return _generate(*args, **kwargs)

    target = Path(target)
    fmt = target.suffix.lower().lstrip(".") or "pdf"
    if fmt not in {"pdf", "docx"}:
        raise ValueError(f"平台 只请求 pdf/docx，收到 {fmt}")
    kwargs.setdefault("formats", (fmt,))
    kwargs.setdefault("output_root", target.parent / "report")
    report = _generate(*args, **kwargs)
    produced = Path(report["directory"]) / f"report.{fmt}"
    if not produced.is_file():
        raise ValueError(f"报告 未生成 report.{fmt}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(produced, target)
    return report
