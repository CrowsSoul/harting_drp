# -*- coding: utf-8 -*-
"""Deterministic, offline FloEFD engineer handoff for PERF-01.

The generated document is a work order, not a solver result.  It does not use
COM, NXOpen, proprietary automation, or process execution.  Native FloEFD goal
names remain null until they are established for the exact target release.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os

from .cae_bindings import (
    binding_digest,
    load_material_library,
    material_for,
    validate_bindings,
)
from .solver_environment import capability_for


RESULT_CONTRACT = "contracts/schema/perf_solver_result.schema.json"
DEFAULT_RELEASE = "NX 2606.3002"
REQUIRED_OUTPUTS = (
    ("maximum_temperature_c", "degC", "whole_model maximum absolute temperature"),
    ("delta_t_c", "degC", "maximum_temperature_c minus ambient_temperature_c"),
    ("total_resistance_ohm", "ohm", "electrical inlet-to-ground path resistance"),
    ("joule_power_w", "W", "total Joule heating power"),
    ("voltage_drop_v", "V", "electrical inlet-to-ground potential drop"),
)


class FloEFDHandoffError(ValueError):
    """A validation error with a stable machine-readable code."""

    def __init__(self, code: str, message: str, action: str):
        super().__init__(message)
        self.code = code
        self.action = action

    def as_dict(self) -> dict:
        return {
            "ok": False,
            "status": "not_done",
            "error": {
                "code": self.code,
                "message": str(self),
                "action": self.action,
            },
        }


def _fail(code: str, message: str, action: str) -> None:
    raise FloEFDHandoffError(code, message, action)


def _face_ids(binding: dict, role: str) -> list[str]:
    return list((binding.get("face_roles") or {}).get(role, {}).get("face_ids") or [])


def _model_identity(
    model_identity: dict | None,
    case: dict,
    source_geometry: dict,
) -> dict:
    supplied = copy.deepcopy(model_identity or {})
    model_digest = str(source_geometry.get("model_digest") or "")
    content_digest = str(supplied.get("content_digest") or model_digest)
    if supplied.get("content_digest") and model_digest:
        if str(supplied["content_digest"]) != model_digest:
            _fail(
                "model_digest_mismatch",
                "可选模型 identity 的 content_digest 与 binding.model_digest 不一致",
                "重新从同一源模型生成 ModelBundle 和 confirmed binding，禁止混用版本。",
            )
    identity = {
        "model_id": str(
            supplied.get("model_id")
            or case.get("model_id")
            or source_geometry.get("model_id")
            or ""
        ),
        "content_digest": content_digest,
        "input_digest": str(supplied.get("input_digest") or ""),
        "source": str(supplied.get("source") or source_geometry.get("source_part") or ""),
        "nx_version": str(supplied.get("nx_version") or ""),
    }
    return identity


def _validate_case_and_binding(case: dict, binding: dict) -> None:
    if not isinstance(case, dict) or not isinstance(binding, dict):
        _fail(
            "invalid_input",
            "case 和 binding 必须是 JSON 对象",
            "提供 perf CAE case JSON 及其 confirmed bindings JSON。",
        )
    item = str(case.get("check_item_id") or "")
    if item != "PERF-01":
        _fail(
            "unsupported_item",
            f"FloEFD handoff 仅支持 PERF-01，收到 {item!r}",
            "PERF-02 使用 SOL401/Nastran 流程；不要复用 FloEFD 电热 handoff。",
        )
    if binding.get("check_item_id") != item:
        _fail(
            "binding_item_mismatch",
            "binding.check_item_id 与 case 不一致",
            "为当前 PERF-01 case 重新生成并确认 binding。",
        )
    if not case.get("case_id") or binding.get("case_id") != case.get("case_id"):
        _fail(
            "binding_case_mismatch",
            "binding.case_id 与 case.case_id 不一致或缺失",
            "使用同一 case_id 的 case/binding 配对，禁止跨工况复用绑定。",
        )
    if binding.get("status") != "confirmed":
        _fail(
            "binding_not_confirmed",
            "binding.status 必须为 confirmed",
            "由工程师确认几何、面角色、材料、边界与结果查询后重新计算 binding_digest。",
        )
    expected_digest = binding.get("binding_digest")
    actual_digest = binding_digest(binding)
    if not expected_digest or expected_digest != actual_digest:
        _fail(
            "binding_digest_mismatch",
            "binding_digest 缺失或与绑定内容不一致",
            "确认全部绑定字段后用 cae_bindings.binding_digest 重新计算摘要，不要手工修补摘要。",
        )
    validation = validate_bindings(binding)
    if not validation.get("valid"):
        _fail(
            "binding_validation_failed",
            "confirmed binding 未通过 cae_bindings 校验：" + "；".join(validation.get("errors") or []),
            "按 cae_bindings 报告补齐面角色、材料、载荷和结果查询，并重新确认及计算摘要。",
        )
    case_material = str(case.get("material") or "")
    binding_material = str((binding.get("material") or {}).get("material") or "")
    if case_material and case_material != binding_material:
        _fail(
            "material_mismatch",
            f"case 材料 {case_material!r} 与 binding 材料 {binding_material!r} 不一致",
            "确认实际材料后同步更新 case 与 binding，并重新计算 binding_digest。",
        )


def build_floefd_handoff(
    case: dict,
    binding: dict,
    model_identity: dict | None = None,
    *,
    release: str = DEFAULT_RELEASE,
) -> dict:
    """Build an engineer-ready PERF-01 handoff without running a solver."""
    _validate_case_and_binding(case, binding)
    capability = capability_for(release, "PERF-01")
    if capability.get("status") == "not_done":
        _fail(
            "capability_not_available",
            "；".join(error.get("message", "") for error in capability.get("errors") or []),
            "为 FloEFD handoff 提供具有精确 PERF-01 映射的 NX release；禁止邻近版本回退。",
        )

    geometry = copy.deepcopy(binding.get("source_geometry") or {})
    roles = copy.deepcopy(binding.get("face_roles") or {})
    loads = binding.get("load_values") or {}
    library = load_material_library()
    # Start with the audited library record, then retain confirmed binding
    # provenance/overrides.  No material property is inferred from geometry.
    material = {**material_for(case, library), **copy.deepcopy(binding.get("material") or {})}
    reference_temperature_c = library.get("reference_temperature_c")
    resistivity = {
        "temperature_dependent": True,
        "reference_temperature_c": reference_temperature_c,
        "electrical_resistivity_ohm_m": material.get("electrical_resistivity_ohm_m"),
        "temperature_coefficient_1_k": material.get("temperature_coefficient_1_k"),
        "expression": "rho_ref_ohm_m * (1 + temperature_coefficient_1_k * (temperature_c - reference_temperature_c))",
        "provenance": material.get("provenance"),
    }

    mesh_request = case.get("mesh") if isinstance(case.get("mesh"), dict) else {}
    element_size = mesh_request.get("element_size_mm")
    local_refinement = [
        {
            "region_id": "electrical_inlet",
            "face_role": "electrical_inlet",
            "face_ids": _face_ids(binding, "electrical_inlet"),
            "reason": "resolve current entry and local Joule-heating gradients",
        },
        {
            "region_id": "electrical_ground",
            "face_role": "electrical_outlet",
            "face_ids": _face_ids(binding, "electrical_outlet"),
            "reason": "resolve ground/current-return and local Joule-heating gradients",
        },
        {
            "region_id": "minimum_cross_section",
            "face_role": None,
            "face_ids": [],
            "selection_status": "engineer_to_bind",
            "reason": "refine the confirmed current bottleneck; do not infer it from a bounding box",
        },
    ]

    required_outputs = [
        {
            "output_key": name,
            "unit": unit,
            "definition": definition,
            "native_key": capability.get("native_result_mapping", {}).get(name),
        }
        for name, unit, definition in REQUIRED_OUTPUTS
    ]
    goals = [
        {
            "goal_id": name,
            "output_key": name,
            "unit": unit,
            "selection": "whole_model" if name in {"maximum_temperature_c", "joule_power_w"} else "electrical_inlet_to_ground",
            "native_key": capability.get("native_result_mapping", {}).get(name),
        }
        for name, unit, _definition in REQUIRED_OUTPUTS
    ]
    probes = [
        {
            "probe_id": "electrical_inlet_probe",
            "face_role": "electrical_inlet",
            "face_ids": _face_ids(binding, "electrical_inlet"),
            "quantities": ["temperature_c", "electric_potential_v"],
        },
        {
            "probe_id": "electrical_ground_probe",
            "face_role": "electrical_outlet",
            "face_ids": _face_ids(binding, "electrical_outlet"),
            "quantities": ["temperature_c", "electric_potential_v"],
        },
        {
            "probe_id": "hottest_region_probe",
            "face_role": None,
            "face_ids": [],
            "selection_status": "resolve_after_solution",
            "quantities": ["maximum_temperature_c"],
        },
    ]

    handoff = {
        "schema_version": "1.0.0",
        "case_id": case["case_id"],
        "check_item_id": "PERF-01",
        "model_identity": _model_identity(model_identity, case, geometry),
        "source_geometry": geometry,
        "face_roles": roles,
        "material": material,
        "temperature_dependent_resistivity": resistivity,
        "electrical": {
            "current_a": loads.get("current_a"),
            "current_face_role": "electrical_inlet",
            "current_face_ids": _face_ids(binding, "electrical_inlet"),
            "ground_face_role": "electrical_outlet",
            "ground_face_ids": _face_ids(binding, "electrical_outlet"),
            "ground_potential_v": 0.0,
        },
        "convection": {
            "face_role": "convection",
            "face_ids": _face_ids(binding, "convection"),
            "ambient_temperature_c": loads.get("ambient_temperature_c"),
            "heat_transfer_coefficient_w_m2k": loads.get("convection_h_w_m2k"),
        },
        "radiation": {
            "face_role": "radiation",
            "face_ids": _face_ids(binding, "radiation"),
            "emissivity": loads.get("radiation_emissivity"),
            "ambient_temperature_c": loads.get("ambient_temperature_c"),
        },
        "mesh": {
            "global": {
                "type": "3d_conformal",
                "element_size_mm": element_size,
                "status": "requested" if element_size is not None else "engineer_to_define",
            },
            "local_refinement": local_refinement,
            "medium_and_fine_study_required": True,
        },
        "goals": goals,
        "probes": probes,
        "required_outputs": required_outputs,
        "quality_requirements": {
            "convergence_status": "converged",
            "residual_required": True,
            "mesh_sensitivity_relative_change_pct_max": 2.0,
            "energy_balance_relative_error_max": 0.02,
            "medium_and_fine_mesh_comparison_required": True,
            "native_result_keys_must_be_confirmed": True,
        },
        "capability": capability,
        "binding_digest": binding["binding_digest"],
        "status": "ready_for_engineer",
        "solver_run_performed": False,
        "automation_supported": False,
        "result_contract": RESULT_CONTRACT,
        "not_done": [
            "Engineer must configure FloEFD and confirm native goal/result keys for the exact release.",
            "Engineer must define global mesh size and bind the minimum-cross-section refinement region.",
            "Solve, convergence review, mesh study, energy balance, and result-contract ingestion have not been performed.",
        ],
        "provenance": {
            "generator": "nxdrp.checkers.performance.floefd_handoff",
            "offline_only": True,
            "case_id": case["case_id"],
            "binding_digest": binding["binding_digest"],
            "capability_catalog_id": capability.get("catalog_id", ""),
            "native_result_mapping_status": "unverified",
        },
    }
    encoded = json.dumps(
        handoff, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    handoff["handoff_id"] = hashlib.sha256(encoded).hexdigest()
    return handoff


def write_floefd_handoff(path: str, handoff: dict) -> str:
    """Write a deterministic handoff document; this does not execute anything."""
    destination = os.path.abspath(path)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    with open(destination, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(handoff, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return destination


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 顶层必须是对象：{path}")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成 PERF-01 FloEFD 离线工程师 handoff（不求解）")
    parser.add_argument("--case", required=True, help="PERF-01 case JSON")
    parser.add_argument("--binding", required=True, help="confirmed bindings JSON")
    parser.add_argument("--out", required=True, help="handoff 输出 JSON")
    parser.add_argument("--model", help="可选 ModelBundle 或 model identity JSON")
    parser.add_argument("--release", default=DEFAULT_RELEASE, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        model = _load_json(args.model) if args.model else None
        if model and isinstance(model.get("model_identity"), dict):
            model = model["model_identity"]
        handoff = build_floefd_handoff(
            _load_json(args.case),
            _load_json(args.binding),
            model,
            release=args.release,
        )
        destination = write_floefd_handoff(args.out, handoff)
    except (FloEFDHandoffError, OSError, ValueError, json.JSONDecodeError) as exc:
        if isinstance(exc, FloEFDHandoffError):
            detail = json.dumps(exc.as_dict(), ensure_ascii=False)
        else:
            detail = json.dumps({
                "ok": False,
                "status": "not_done",
                "error": {"code": "invalid_input", "message": str(exc)},
            }, ensure_ascii=False)
        parser.exit(2, detail + "\n")
    print(destination)
    print("status=ready_for_engineer solver_run_performed=false automation_supported=false")
    return 0


if __name__ == "__main__":
    main()


__all__ = [
    "DEFAULT_RELEASE",
    "FloEFDHandoffError",
    "REQUIRED_OUTPUTS",
    "RESULT_CONTRACT",
    "build_floefd_handoff",
    "main",
    "write_floefd_handoff",
]
