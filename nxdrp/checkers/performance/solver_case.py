# -*- coding: utf-8 -*-
"""输出可直接交给 NX / Simcenter / FloEFD 工程师的 PERF 工况清单。

该命令只生成本地输入清单，不声称已经启动或完成求解。求解完成后应按
``contracts/schema/perf_solver_result.schema.json`` 回填证据，再把
``solver_result_path`` 写入对应规则。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone

from ...contracts import ModelBundle, RuleBook
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
        "status": "ready_for_solver",
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
        "next_action": (
            "在具备授权的 NX/Simcenter/FloEFD 环境中按 case 执行求解，"
            "再用 result_contract 回填 convergence_status 与 outputs。"
        ),
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
    source_part: str,
    out_dir: str,
    *,
    body_tags: list[int] | None = None,
    create_solution: bool = False,
    solution_type: str = "",
    mesh_enabled: bool = False,
    element_size_mm: float | None = None,
    bindings_path: str = "",
    binding_digest: str = "",
) -> dict:
    cases = load_cases()["cases"]
    case = next((item for item in cases if item.get("case_id") == case_id), None)
    if case is None:
        raise ValueError(f"未知 PERF CAE 工况：{case_id}")
    kind = (
        "thermal"
        if "thermal" in str(case.get("analysis_type", "")).casefold()
        else "structural"
    )
    return {
        "case_id": case_id,
        "kind": kind,
        "source_part": os.path.abspath(source_part),
        "out_dir": os.path.abspath(out_dir),
        "body_tags": list(body_tags or []),
        "create_solution": bool(create_solution),
        "solution_type": solution_type,
        "bindings_path": os.path.abspath(bindings_path) if bindings_path else "",
        "binding_digest": binding_digest,
        "mesh": {
            "enabled": bool(mesh_enabled),
            "element_size_mm": element_size_mm,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 PERF CAE 求解工况清单")
    parser.add_argument(
        "--case",
        required=True,
        choices=[item["case_id"] for item in load_cases()["cases"]],
    )
    parser.add_argument("--model", help="可选：已提取的 ModelBundle JSON")
    parser.add_argument("--out", required=True)
    parser.add_argument("--source-part", help="可选：生成 NX FEM/SIM 容器请求时使用的 .prt")
    parser.add_argument("--out-dir", help="NX FEM/SIM 输出目录")
    parser.add_argument("--body-tag", action="append", type=int, default=[])
    parser.add_argument("--create-solution", action="store_true")
    parser.add_argument("--solution-type", default="")
    parser.add_argument("--mesh", action="store_true")
    parser.add_argument("--element-size", type=float)
    parser.add_argument("--binding", help="已确认的 bindings.json")
    parser.add_argument("--nx-request-out", help="输出 create_simcenter_case.py 使用的请求 JSON")
    args = parser.parse_args()
    model = ModelBundle.load(args.model) if args.model else None
    manifest = build_case_manifest(args.case, model=model)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    print(args.out)
    if args.nx_request_out:
        binding_payload = {}
        if args.binding:
            with open(args.binding, "r", encoding="utf-8") as fh:
                binding_payload = json.load(fh)
            from .cae_bindings import validate_bindings

            validation = validate_bindings(binding_payload)
            if not validation["valid"]:
                raise SystemExit("绑定未通过校验：" + "；".join(validation["errors"]))
            args.source_part = args.source_part or binding_payload["source_geometry"]["source_part"]
            if not args.body_tag:
                args.body_tag = list(binding_payload["source_geometry"]["body_tags"])
        if not args.source_part or not args.out_dir:
            raise SystemExit("--nx-request-out 需要 --source-part/--out-dir，或完整 --binding")
        request = build_nx_journal_request(
            args.case,
            args.source_part,
            args.out_dir,
            body_tags=args.body_tag,
            create_solution=args.create_solution,
            solution_type=args.solution_type,
            mesh_enabled=args.mesh,
            element_size_mm=args.element_size,
            bindings_path=args.binding,
            binding_digest=binding_payload.get("binding_digest", ""),
        )
        with open(args.nx_request_out, "w", encoding="utf-8") as fh:
            json.dump(request, fh, ensure_ascii=False, indent=2)
        print(args.nx_request_out)
    print("状态：ready_for_solver（尚未执行 NX/Simcenter/FloEFD 求解）")


if __name__ == "__main__":
    main()
