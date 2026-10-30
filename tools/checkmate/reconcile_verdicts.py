# -*- coding: utf-8 -*-
"""新旧规则双跑对账：同一模型分别用两本规则库跑管线，逐条比较判定口径。

比较字段：check_item_id / severity / measured / threshold / unit / part_refs / face_ids
（忽略 message、suggestion 等文案）。measured/threshold 默认对齐到 2 位小数——
规则库声明的 rounding 变化属于"展示精度"变更，不应算判定漂移。

用法：
    # 新规则库 vs 去掉 expression 的旧路径（W1 迁移验收）
    python tools/checkmate/reconcile_verdicts.py --model mockdata/models \
        --no-expression-for DFM-27,DFM-28,DFM-33

    # 两本规则库直接对比
    python tools/checkmate/reconcile_verdicts.py --model a.model.json \
        --baseline rules/dfm_default.json --candidate rules/dfm_default_v2.json

退出码：0 = 零差异；1 = 有差异（差异清单打印到 stdout）。
"""

from __future__ import annotations

import argparse
import copy
import glob
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nxdrp.contracts import ModelBundle, RuleBook  # noqa: E402
from nxdrp.pipeline import run  # noqa: E402
from nxdrp.registry import discover  # noqa: E402

REGISTRY = discover()


def _projection(result, decimals: int):
    rows = []
    for finding in result.findings:
        rows.append(
            {
                "check_item_id": finding.check_item_id,
                "severity": finding.severity,
                "measured": None if finding.measured_value is None else round(finding.measured_value, decimals),
                "threshold": None if finding.threshold_value is None else round(finding.threshold_value, decimals),
                "unit": finding.unit,
                "part_refs": list(finding.part_refs),
                "face_ids": list(finding.evidence.face_ids),
            }
        )
    return sorted(rows, key=lambda r: json.dumps(r, ensure_ascii=False, sort_keys=True))


def _strip_expression(book: RuleBook, items: set[str]) -> RuleBook:
    clone = copy.deepcopy(book)
    for rule in clone.rules:
        if rule.check_item_id in items:
            rule.expression = {}
            rule.exceptions = []
            rule.unit = ""
            rule.rounding = None
    return clone


def _models(paths: list[str]) -> list[str]:
    out: list[str] = []
    for path in paths:
        if os.path.isdir(path):
            out.extend(sorted(glob.glob(os.path.join(path, "*.model.json"))))
        else:
            out.append(path)
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", action="append", required=True, help="模型文件或目录，可重复")
    parser.add_argument("--baseline", default=str(REPO_ROOT / "rules" / "dfm_default.json"))
    parser.add_argument("--candidate", default=str(REPO_ROOT / "rules" / "dfm_default.json"))
    parser.add_argument("--no-expression-for", default="", help="在 baseline 上去掉这些 ID 的 expression（模拟旧路径）")
    parser.add_argument("--only", default="", help="只跑这些检查项（逗号分隔）")
    parser.add_argument("--decimals", type=int, default=2)
    parser.add_argument("--json", dest="json_out", default="", help="把差异清单写成 JSON")
    args = parser.parse_args(argv)

    baseline = RuleBook.load(args.baseline)
    candidate = RuleBook.load(args.candidate)
    items = {x.strip() for x in args.no_expression_for.split(",") if x.strip()}
    if items:
        baseline = _strip_expression(baseline, items)
    only = [x.strip() for x in args.only.split(",") if x.strip()] or None

    report = {"models": [], "differences": [], "ok": True}
    for path in _models(args.model):
        model = ModelBundle.load(path)
        old = _projection(run(model, baseline, REGISTRY, only=only), args.decimals)
        new = _projection(run(model, candidate, REGISTRY, only=only), args.decimals)
        if old == new:
            report["models"].append({"model": path, "findings": len(new), "differences": 0})
            print(f"[一致] {os.path.basename(path)}：{len(new)} 条 finding")
            continue
        old_set = {json.dumps(r, ensure_ascii=False, sort_keys=True) for r in old}
        new_set = {json.dumps(r, ensure_ascii=False, sort_keys=True) for r in new}
        only_old = [json.loads(x) for x in sorted(old_set - new_set)]
        only_new = [json.loads(x) for x in sorted(new_set - old_set)]
        report["ok"] = False
        report["models"].append(
            {"model": path, "findings": len(new), "differences": len(only_old) + len(only_new),
             "only_baseline": only_old, "only_candidate": only_new}
        )
        report["differences"].extend(
            [{"model": path, "side": "baseline", **row} for row in only_old]
            + [{"model": path, "side": "candidate", **row} for row in only_new]
        )
        print(f"[差异] {os.path.basename(path)}：仅旧 {len(only_old)} 条 / 仅新 {len(only_new)} 条")
        for row in only_old:
            print(f"    - 旧: {row}")
        for row in only_new:
            print(f"    + 新: {row}")

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n差异清单已写出：{args.json_out}")
    print(f"\n结论：{'零差异' if report['ok'] else '存在差异，逐条核对是否为修正'}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
