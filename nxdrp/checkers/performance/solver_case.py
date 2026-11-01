# -*- coding: utf-8 -*-
"""生成 PERF 求解交接单，或从已确认绑定构造统一 Simcenter 请求。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone

from ...contracts import ModelBundle, RuleBook
from .cae_bindings import validate_bindings
from .cae_orchestrator import build_journal_request, build_setup_manifest
from .rule_engine import PROJECT_ROOT


CASES_PATH = os.path.join(PROJECT_ROOT, "rules", "perf_cae_cases.json")
RULES_PATH = os.path.join(PROJECT_ROOT, "rules", "dfm_default.json")


def load_cases(path: str = CASES_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if payload.get("schema_version") != "1.0.0":
        raise ValueError("PERF 工况库 schema_version 必须为 1.0.0")
    return payload


def build_case_manifest(
    case_id: str,
    model: ModelBundle | None = None,
    rulebook: RuleBook | None = None,
) -> dict:
    cases = load_cases()["cases"]
    case = next((item for item in cases if item.get("case_id") == case_id), None)
    if case is None:
        raise ValueError(f"未知 PERF CAE 工况：{case_id}")
    book = rulebook or RuleBook.load(RULES_PATH)
    item_id = case["check_item_id"]
    rule = book.get(item_id)
    if rule is None:
        raise ValueError(f"规则库缺少 {item_id}")
    manifest = {
        "schema_version": "1.0.0",
        "manifest_id": hashlib.sha256(
            f"{case_id}:{datetime.now(timezone.utc).isoformat()}".encode("utf-8")
        ).hexdigest()[:16],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "ready_for_preparation",
        "solver_run_performed": False,
        "case": case,
        "rule": {
            "rule_id": rule.rule_id,
            "check_item_id": item_id,
            "version": rule.version,
            "formula_ref": rule.formula_ref,
            "expression": rule.expression,
            "unit": rule.unit,
            "reference": rule.reference,
            "params": rule.params,
        },
        "model": None,
        "result_contract": "contracts/schema/perf_solver_result.schema.json",
        "next_action": "确认参数化 case 的 bindings，再用 cae_orchestrator prepare 生成设置清单。",
    }
    if model is not None:
        manifest["model"] = {
            "model_id": model.model_id,
            "source": model.source,
            "nx_version": model.nx_version,
            "content_digest": model.content_digest(),
            "parts": len(model.parts),
            "faces": len(model.faces),
        }
    return manifest


def build_nx_journal_request(
    case_id: str,
    source_part: str = "",
    out_dir: str = "",
    *,
    body_tags: list[int] | None = None,
    bindings_path: str,
    nx_release: str,
    binding_digest: str = "",
    **legacy,
) -> dict:
    """兼容旧函数名；实际请求只能来自已确认 binding 和版本能力映射。"""
    if legacy.get("solution_type"):
        raise ValueError("不允许自由覆盖 solution_type；请使用版本化 capability")
    binding_path = os.path.abspath(bindings_path)
    root = os.path.dirname(binding_path)
    with open(binding_path, "r", encoding="utf-8") as fh:
        binding = json.load(fh)
    if binding.get("case_id") != case_id:
        raise ValueError("bindings.json 的 case_id 与请求不一致")
    validation = validate_bindings(binding)
    if not validation["valid"]:
        raise ValueError("绑定未通过校验：" + "；".join(validation["errors"]))
    if binding_digest and binding.get("binding_digest") != binding_digest:
        raise ValueError("binding_digest 与已确认绑定不一致")
    source = (binding.get("source_geometry") or {}).get("source_part", "")
    if source_part and os.path.abspath(source_part) != os.path.abspath(source):
        raise ValueError("source_part 与已确认绑定不一致")
    if body_tags and set(body_tags) != set((binding.get("source_geometry") or {}).get("body_tags", [])):
        raise ValueError("body_tags 与已确认绑定不一致")
    if out_dir and os.path.abspath(out_dir) != root:
        raise ValueError("out_dir 必须是绑定所在的工况目录")
    manifest = build_setup_manifest(root, nx_release)
    return build_journal_request(manifest, "setup", online=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 PERF CAE 求解工况清单")
    parser.add_argument(
        "--case",
        required=True,
        choices=[item["case_id"] for item in load_cases()["cases"]],
    )
    parser.add_argument("--model", help="可选：已提取的 ModelBundle JSON")
    parser.add_argument("--out", required=True)
    parser.add_argument("--binding", help="参数化工况中已确认的 bindings.json")
    parser.add_argument("--nx-release", default=os.environ.get("NXDRP_NX_RELEASE", ""))
    parser.add_argument("--nx-request-out", help="输出统一 Simcenter setup 请求 JSON")
    args = parser.parse_args()
    model = ModelBundle.load(args.model) if args.model else None
    manifest = build_case_manifest(args.case, model=model)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    print(args.out)
    if args.nx_request_out:
        if not args.binding or not args.nx_release:
            raise SystemExit("--nx-request-out 需要已确认 --binding 和精确 --nx-release")
        with open(args.binding, "r", encoding="utf-8") as fh:
            binding = json.load(fh)
        request = build_nx_journal_request(
            binding["case_id"],
            bindings_path=args.binding,
            nx_release=args.nx_release,
        )
        with open(args.nx_request_out, "w", encoding="utf-8") as fh:
            json.dump(request, fh, ensure_ascii=False, indent=2)
        print(args.nx_request_out)
    print("状态：ready_for_preparation（尚未执行 NX/Simcenter/FloEFD 求解）")


if __name__ == "__main__":
    main()
