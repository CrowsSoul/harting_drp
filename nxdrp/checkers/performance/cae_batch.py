# -*- coding: utf-8 -*-
"""PERF CAE 参数化批量、结果回填与公式校准。

该模块不启动求解器。它负责生成可交给 NX/Simcenter/FloEFD 的确定性参数
矩阵，并在求解完成后读取符合 ``perf_solver_result.schema.json`` 的结果，
计算公式误差、分位误差、通过率和规则判定一致率。

    python -m nxdrp.checkers.performance.cae_batch generate --out runtime/perf_batch.json
    python -m nxdrp.checkers.performance.cae_batch ingest --batch runtime/perf_batch.json --results runtime/results --out runtime/perf_records.json
    python -m nxdrp.checkers.performance.cae_batch report --batch runtime/perf_batch.json --records runtime/perf_records.json --out runtime/perf_calibration.md
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import math
import os
import random
import statistics
from datetime import datetime, timezone
from ...contracts import RuleBook
from .cae_bindings import (
    binding_digest,
    create_binding_draft,
    load_material_library,
    validate_bindings,
)
from .perf01_current_temp import evaluate_formula as evaluate_perf01_formula
from .perf01_current_temp import _formula_inputs as perf01_inputs
from .perf02_insertion_force import _contact_inputs, evaluate_contact
from .rule_engine import PROJECT_ROOT, load_formula
from .solver_evidence import SolverEvidence, load_solver_evidence


RULEBOOK_PATH = os.path.join(PROJECT_ROOT, "rules", "dfm_default.json")
CASES_PATH = os.path.join(PROJECT_ROOT, "rules", "perf_cae_cases.json")
ACTIONS_PATH = os.path.join(PROJECT_ROOT, "rules", "perf_simcenter_actions_v1.json")
DEFAULT_COUNT = 20
DEFAULT_SEED = 20261030
SUPPORTED_ITEMS = ("PERF-01", "PERF-02")
AUTHORIZED_LICENSE_MODES = {
    "authorized",
    "commercial",
    "floating",
    "node_locked",
    "evaluation",
}
PRODUCTION_LICENSE_MODES = AUTHORIZED_LICENSE_MODES - {"evaluation"}
COMPLETED_STAGE_STATUSES = {"complete", "completed", "done", "ok", "success", "succeeded"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_write(path: str, payload: dict) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return path


def _lhs(rng: random.Random, low: float, high: float, count: int, log_scale: bool = False) -> list[float]:
    """一维分层拉丁超立方；避免随机样本全挤在范围一端。"""
    if not low < high:
        return [float(low)] * count
    order = list(range(count))
    rng.shuffle(order)
    values = []
    for i in range(count):
        u = (order[i] + rng.random()) / count
        if log_scale:
            values.append(math.exp(math.log(low) + u * (math.log(high) - math.log(low))))
        else:
            values.append(low + u * (high - low))
    return values


def _case_definitions() -> dict[str, dict]:
    with open(CASES_PATH, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    return {item["check_item_id"]: item for item in payload["cases"]}


def _case_catalog() -> dict[str, str]:
    return {item: definition["case_id"] for item, definition in _case_definitions().items()}


def _mesh_sensitivity_limits() -> dict[str, float]:
    return {
        item: float(definition["acceptance"]["mesh_sensitivity_max_pct"])
        for item, definition in _case_definitions().items()
    }


def _action_templates() -> dict[str, dict]:
    with open(ACTIONS_PATH, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if payload.get("schema_version") != "1.0.0":
        raise ValueError("PERF Simcenter actions schema_version 必须为 1.0.0")
    return dict(payload.get("items") or {})


def _decision_payload(result) -> list[dict]:
    return [item.to_dict() for item in result.decisions]


def _perf01_case(index: int, values: dict[str, list[float]], materials: list[str], params: dict, case_id: str) -> dict:
    material = materials[index % len(materials)]
    material_data = params["materials"][material]
    inputs = perf01_inputs(
        values["area_mm2"][index],
        values["length_mm"][index],
        material_data["rho_ohm_m"],
        values["current_a"][index],
        values["h_w_m2k"][index],
        temp_coeff_per_c=material_data["temp_coeff_per_c"],
        ambient_temp_c=values["ambient_temp_c"][index],
        emissivity=params["emissivity"],
        contact_resistance_ohm_mm2=params["contact_resistance_ohm_mm2"],
        reference_temp_c=params["reference_temp_c"],
        max_solver_rise_c=params["max_solver_rise_c"],
        max_rise_c=params["max_rise_c"],
        max_temperature_c=params["max_temperature_c"],
    )
    result = evaluate_perf01_formula(
        inputs["area_mm2"],
        inputs["length_mm"],
        inputs["rho_ohm_m"],
        inputs["current_a"],
        inputs["h_w_m2k"],
        formula=load_formula("PERF-01"),
        **{
            key: value
            for key, value in inputs.items()
            if key not in {"area_mm2", "length_mm", "rho_ohm_m", "current_a", "h_w_m2k"}
        },
    )
    expected = {
        "maximum_temperature_c": result.values["absolute_temperature_c"],
        "delta_t_c": result.values["delta_t_c"],
        "total_resistance_ohm": result.values["total_resistance_ohm"],
        "joule_power_w": result.values["power_w"],
        "voltage_drop_v": result.values["voltage_drop_v"],
    }
    required_outputs = {
        "maximum_temperature_c": "degC",
        "delta_t_c": "degC",
        "total_resistance_ohm": "ohm",
        "joule_power_w": "W",
        "voltage_drop_v": "V",
    }
    return {
        "case_id": f"PERF01-ET-{index + 1:04d}",
        "solver_case_id": case_id,
        "check_item_id": "PERF-01",
        "material": material,
        "solver_setup": {
            "analysis_type": "thermal_with_joule",
            "analysis_mode": "steady",
            "physics_domain": "solid",
            "joule_heating": True,
        },
        "formula_inputs": inputs,
        "geometry_request": {
            "type": "cylinder",
            "diameter_mm": 2.0 * math.sqrt(inputs["area_mm2"] / math.pi),
            "length_mm": inputs["length_mm"],
            "axis": "X",
        },
        "boundary_conditions": {
            "current_a": inputs["current_a"],
            "outlet_voltage_v": 0.0,
            "ambient_temperature_c": inputs["ambient_temp_c"],
            "convection_h_w_m2k": inputs["h_w_m2k"],
            "radiation_emissivity": inputs["emissivity"],
            "contact_resistance_ohm_mm2": inputs["contact_resistance_ohm_mm2"],
            "electrical_inlet": {"role": "electrical_inlet", "current_a": inputs["current_a"]},
            "electrical_outlet": {"role": "electrical_outlet", "voltage_v": 0.0},
            "convection": {
                "role": "convection",
                "ambient_temperature_c": inputs["ambient_temp_c"],
                "h_w_m2k": inputs["h_w_m2k"],
            },
            "radiation": {"role": "radiation", "emissivity": inputs["emissivity"]},
        },
        "required_outputs": required_outputs,
        "required_output_units": dict(required_outputs),
        "expected_units": dict(required_outputs),
        "expected_values": expected,
        "formula_outputs": dict(expected),
        "formula_decisions": _decision_payload(result),
    }


def _perf02_case(index: int, values: dict[str, list[float]], materials: list[str], params: dict, case_id: str) -> dict:
    material = materials[index % len(materials)]
    e_gpa = params["materials"][material]["e_gpa"]
    rule_spec = {
        "length_mm": values["length_mm"][index],
        "width_mm": values["width_mm"][index],
        "thickness_mm": values["thickness_mm"][index],
        "overlap_mm": values["overlap_mm"][index],
        "contacts": params["contacts"],
        "lead_angle_deg": params["lead_angle_deg"],
        "friction_coeff": values["friction_coeff"][index],
    }
    modeled_spec = {**rule_spec, "contacts": 1.0}
    inputs = _contact_inputs(modeled_spec, e_gpa, params)
    formula = load_formula("PERF-02")
    result = evaluate_contact(modeled_spec, e_gpa, params, formula=formula)
    rule_result = evaluate_contact(rule_spec, e_gpa, params, formula=formula)
    expected = {
        "insertion_force_n": result.values["insertion_force_n"],
        "withdrawal_force_n": result.values["withdrawal_force_n"],
        "maximum_normal_contact_force_n": result.values["normal_force_n"],
    }
    expected_rule_values = {
        "insertion_force_n": rule_result.values["insertion_force_n"],
        "withdrawal_force_n": rule_result.values["withdrawal_force_n"],
        "maximum_normal_contact_force_n": rule_result.values["normal_force_n"],
    }
    expected_units = {name: "N" for name in expected}
    required_outputs = {
        **expected_units,
        "maximum_penetration_mm": "mm",
        "maximum_equivalent_stress_mpa": "MPa",
    }
    stroke = 0.5 * rule_spec["length_mm"]
    search_distance = max(rule_spec["overlap_mm"], rule_spec["thickness_mm"])
    slope = math.tan(math.radians(rule_spec["lead_angle_deg"]))
    contact_travel = stroke - rule_spec["overlap_mm"] / slope
    deflection_travel = rule_spec["overlap_mm"] / slope
    if contact_travel <= 0:
        raise ValueError("插入行程必须先建立接触，再形成法向过盈")
    return {
        "case_id": f"PERF02-CONTACT-{index + 1:04d}",
        "solver_case_id": case_id,
        "check_item_id": "PERF-02",
        "material": material,
        "solver_setup": {
            "solution_card": "SOL 401",
            "solution_type": "SOL 401 Multi-Step Nonlinear",
            "large_displacement": True,
        },
        "formula_inputs": inputs,
        "rule_formula_inputs": _contact_inputs(rule_spec, e_gpa, params),
        "geometry_request": {
            "type": "cantilever_contact_pair",
            "length_mm": rule_spec["length_mm"],
            "width_mm": rule_spec["width_mm"],
            "thickness_mm": rule_spec["thickness_mm"],
            "normal_overlap_mm": rule_spec["overlap_mm"],
            "insertion_stroke_mm": stroke,
            "lead_angle_deg": rule_spec["lead_angle_deg"],
            "target_slope_deg": rule_spec["lead_angle_deg"],
            "modeled_contact_count": 1,
            "axis_convention": {"length": "X", "width": "Y", "thickness_and_normal_overlap": "Z"},
        },
        "contact_conditions": {
            "method": "penalty",
            "friction_model": "coulomb",
            "friction_coefficient": rule_spec["friction_coeff"],
            "contact_count": 1,
            "modeled_contact_count": 1,
            "rule_contact_count": rule_spec["contacts"],
            "lead_angle_deg": rule_spec["lead_angle_deg"],
            "normal_overlap_mm": rule_spec["overlap_mm"],
            "insertion_stroke_mm": stroke,
            "insertion_direction": "-X",
            "contact_travel_mm": contact_travel,
            "deflection_travel_mm": deflection_travel,
            "penalty_stiffness_n_mm3": 1000.0 * e_gpa / rule_spec["thickness_mm"],
            "search_distance_mm": search_distance,
            "large_displacement": True,
            "load_steps": ["establish_contact", "insert", "withdraw"],
        },
        "mesh": {
            "element_type": "structural solid",
            "element_size_mm": min(rule_spec["thickness_mm"] * 0.5, rule_spec["length_mm"] / 20.0),
            "contact_refinement": True,
        },
        "constraints": {
            "fixed_root": "all_degrees_of_freedom",
            "driven_displacement": {
                "axis": "X",
                "direction": "-X",
                "stroke_mm": stroke,
                "target_role": "driven_face",
            },
        },
        "load_steps": [
            {
                "step": 1,
                "action": "establish_contact",
                "axis": "X",
                "displacement_mm": -contact_travel,
                "output": "initial_contact",
            },
            {
                "step": 2,
                "action": "insert",
                "axis": "X",
                "displacement_mm": -deflection_travel,
                "normal_overlap_mm": rule_spec["overlap_mm"],
                "output": "insertion_force_n",
            },
            {
                "step": 3,
                "action": "withdraw",
                "axis": "X",
                "displacement_mm": stroke,
                "output": "withdrawal_force_n",
            },
        ],
        "required_outputs": required_outputs,
        "required_output_units": dict(required_outputs),
        "expected_units": expected_units,
        "expected_values": expected,
        "expected_rule_values": expected_rule_values,
        "formula_scaling": {
            "modeled_contact_count": 1.0,
            "rule_contact_count": float(rule_spec["contacts"]),
            "method": "linear_contact_count_for_total_forces",
            "output_factors": {
                "insertion_force_n": float(rule_spec["contacts"]),
                "withdrawal_force_n": float(rule_spec["contacts"]),
                "maximum_normal_contact_force_n": 1.0,
            },
            "quantities": ["insertion_force_n", "withdrawal_force_n"],
        },
        "formula_outputs": dict(result.values),
        "formula_decisions": _decision_payload(result),
        "rule_formula_decisions": _decision_payload(rule_result),
    }


def generate_batch(
    count: int = DEFAULT_COUNT,
    seed: int = DEFAULT_SEED,
    items: tuple[str, ...] = SUPPORTED_ITEMS,
) -> dict:
    if count < 3:
        raise ValueError("样本数至少为 3")
    unknown = set(items) - set(SUPPORTED_ITEMS)
    if unknown:
        raise ValueError(f"不支持的 PERF 项：{sorted(unknown)}")
    book = RuleBook.load(RULEBOOK_PATH)
    catalog = _case_catalog()
    rng = random.Random(seed)
    cases = []

    if "PERF-01" in items:
        params = book.get("PERF-01").params
        values = {
            "area_mm2": _lhs(rng, params["area_mm2_min"], params["area_mm2_max"], count, True),
            "length_mm": _lhs(rng, params["length_mm_min"], params["length_mm_max"], count, True),
            "current_a": _lhs(rng, params["current_a_min"], params["current_a_max"], count, True),
            "ambient_temp_c": _lhs(rng, params["ambient_temp_c_min"], params["ambient_temp_c_max"], count),
            "h_w_m2k": _lhs(rng, params["h_w_m2k_min"], params["h_w_m2k_max"], count, True),
        }
        cases.extend(
            _perf01_case(i, values, list(params["materials"]), params, catalog["PERF-01"])
            for i in range(count)
        )

    if "PERF-02" in items:
        params = book.get("PERF-02").params
        values = {
            "length_mm": _lhs(rng, params["length_mm_min"], params["length_mm_max"], count),
            "width_mm": _lhs(rng, params["width_mm_min"], params["width_mm_max"], count),
            "thickness_mm": _lhs(rng, params["thickness_mm_min"], params["thickness_mm_max"], count),
            "overlap_mm": _lhs(rng, params["overlap_mm_min"], params["overlap_mm_max"], count),
            "friction_coeff": _lhs(rng, params["friction_min"], params["friction_max"], count),
        }
        cases.extend(
            _perf02_case(i, values, list(params["materials"]), params, catalog["PERF-02"])
            for i in range(count)
        )

    return {
        "schema_version": "1.0.0",
        "batch_id": f"PERF-CAE-{seed}-{count}",
        "created_at": _utc_now(),
        "status": "ready_for_solver",
        "solver_run_performed": False,
        "seed": seed,
        "count_per_item": count,
        "items": list(items),
        "authorization": {
            "required_for_calibration": True,
            "accepted_license_modes": sorted(PRODUCTION_LICENSE_MODES),
            "note": "求解结果必须声明正式授权，否则只允许做接口联调，不进入认证报告。",
        },
        "cases": cases,
    }


def _positive_geometry_value(geometry: dict, name: str) -> float:
    value = geometry.get(name)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)) or float(value) <= 0:
        raise ValueError(f"几何参数 {name} 必须是大于 0 的有限数值")
    return float(value)


def build_geometry_request(case: dict, out_path: str) -> dict:
    if not str(out_path or "").strip():
        raise ValueError("out_path 不能为空")
    geometry = case.get("geometry_request") or {}
    kind = geometry.get("type")
    if kind == "cylinder":
        return {
            "case_id": case["case_id"],
            "kind": "cylinder",
            "out_path": os.path.abspath(out_path),
            "diameter_mm": _positive_geometry_value(geometry, "diameter_mm"),
            "length_mm": _positive_geometry_value(geometry, "length_mm"),
        }
    if kind == "cantilever_contact_pair":
        conditions = case.get("contact_conditions") or {}
        normalized = dict(geometry)
        if "normal_overlap_mm" not in normalized and "interference_mm" in normalized:
            normalized["normal_overlap_mm"] = normalized["interference_mm"]
        if "insertion_stroke_mm" not in normalized:
            normalized["insertion_stroke_mm"] = conditions.get(
                "insertion_stroke_mm", 0.5 * _positive_geometry_value(normalized, "length_mm")
            )
        if "lead_angle_deg" not in normalized:
            normalized["lead_angle_deg"] = conditions.get("lead_angle_deg")
        raw_angle = normalized.get("lead_angle_deg")
        if not isinstance(raw_angle, (int, float)) or isinstance(raw_angle, bool) or not math.isfinite(float(raw_angle)):
            raise ValueError("lead_angle_deg 必须是有限数值")
        request = {
            "case_id": case["case_id"],
            "kind": "cantilever_contact_pair",
            "out_path": os.path.abspath(out_path),
            "length_mm": _positive_geometry_value(normalized, "length_mm"),
            "width_mm": _positive_geometry_value(normalized, "width_mm"),
            "thickness_mm": _positive_geometry_value(normalized, "thickness_mm"),
            "normal_overlap_mm": _positive_geometry_value(normalized, "normal_overlap_mm"),
            "insertion_stroke_mm": _positive_geometry_value(normalized, "insertion_stroke_mm"),
            "lead_angle_deg": float(normalized["lead_angle_deg"]),
            "target_slope_deg": float(normalized["lead_angle_deg"]),
            "modeled_contact_count": 1,
            "axis_convention": {"length": "X", "width": "Y", "thickness_and_normal_overlap": "Z"},
        }
        angle = request["lead_angle_deg"]
        if not math.isfinite(angle) or not 0.0 < angle < 90.0:
            raise ValueError("lead_angle_deg 必须在 0 到 90 度之间")
        slope = math.tan(math.radians(angle))
        contact_travel = request["insertion_stroke_mm"] - request["normal_overlap_mm"] / slope
        if contact_travel <= 0:
            raise ValueError("插入行程必须先建立接触，再形成法向过盈，且初始几何不得穿透")
        request["insertion_direction"] = "-X"
        request["contact_travel_mm"] = contact_travel
        request["deflection_travel_mm"] = request["normal_overlap_mm"] / slope
        if geometry.get("modeled_contact_count", 1) != 1:
            raise ValueError("PERF-02 参数化工况只能建模一个接触对")
        return request
    raise ValueError(f"不支持的几何类型：{kind}")


def materialize_batch(batch_path: str, out_dir: str) -> dict:
    """为每个参数工况建立独立目录和运行清单，不执行 NX。"""
    with open(batch_path, "r", encoding="utf-8") as fh:
        batch = json.load(fh)
    root = os.path.abspath(out_dir)
    os.makedirs(root, exist_ok=True)
    actions = _action_templates()
    entries = []
    for case in batch.get("cases", []):
        case_dir = os.path.join(root, case["case_id"])
        os.makedirs(case_dir, exist_ok=True)
        case_path = os.path.join(case_dir, "case.json")
        _json_write(case_path, case)
        geometry = build_geometry_request(case, os.path.join(case_dir, "source.prt"))
        geometry_path = os.path.join(case_dir, "geometry_request.json")
        _json_write(geometry_path, geometry)
        actions_path = os.path.join(case_dir, "simcenter_actions.json")
        _json_write(actions_path, {
            "case_id": case["case_id"],
            "check_item_id": case["check_item_id"],
            "required_inputs": case.get("formula_inputs") or {},
            "simcenter": actions[case["check_item_id"]],
        })
        binding = create_binding_draft(case)
        binding["source_geometry"]["source_part"] = geometry["out_path"]
        binding["binding_digest"] = binding_digest(binding)
        bindings_path = os.path.join(case_dir, "bindings.json")
        _json_write(bindings_path, binding)
        entries.append({
            "case_id": case["case_id"],
            "check_item_id": case["check_item_id"],
            "directory": case_dir,
            "case_path": case_path,
            "geometry_request_path": geometry_path,
            "simcenter_actions_path": actions_path,
            "bindings_path": bindings_path,
            "model_id": binding["source_geometry"]["model_id"],
            "source_part": geometry["out_path"],
            "status": "ready_for_geometry",
        })
    index = {
        "schema_version": "1.0.0",
        "batch_id": batch.get("batch_id", ""),
        "created_at": _utc_now(),
        "root": root,
        "cases": entries,
        "status": "ready_for_geometry",
    }
    _json_write(os.path.join(root, "index.json"), index)
    return index


def _run_state_stages(root: str, item: dict) -> dict | None:
    case_dir = os.path.abspath(item["directory"])
    path = os.path.join(case_dir, "run_state.json")
    if not os.path.isfile(path):
        path = os.path.join(root, "run_state.json")
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        state = json.load(fh)
    if path == os.path.join(root, "run_state.json"):
        cases = state.get("cases")
        if isinstance(cases, dict):
            state = cases.get(item["case_id"]) or {}
        elif isinstance(cases, list):
            state = next((value for value in cases if value.get("case_id") == item["case_id"]), {})
    stages = state.get("stages")
    if stages is None and isinstance(state.get(item["case_id"]), dict):
        stages = state[item["case_id"]].get("stages")
    if stages is None:
        return None
    if not isinstance(stages, dict):
        raise ValueError(f"{path}: stages 必须是对象")
    return stages


def _stage_status(stages: dict, *names: str) -> str:
    for name in names:
        record = stages.get(name)
        if isinstance(record, str):
            return record.casefold()
        if isinstance(record, dict):
            return str(record.get("status") or "").casefold()
    return ""


def _stage_done(stages: dict, *names: str) -> bool:
    return _stage_status(stages, *names) in COMPLETED_STAGE_STATUSES


def refresh_workspace_status(workspace: str) -> dict:
    """刷新工况状态；有 run_state 时以求解/导出阶段记录为准。"""
    root = os.path.abspath(workspace)
    index_path = os.path.join(root, "index.json")
    if not os.path.isfile(index_path):
        raise FileNotFoundError(index_path)
    with open(index_path, "r", encoding="utf-8") as fh:
        index = json.load(fh)
    counts: dict[str, int] = {}
    for item in index.get("cases", []):
        case_dir = item["directory"]
        prt_path = item["source_part"]
        fem_files = glob.glob(os.path.join(case_dir, "*.fem"))
        sim_files = glob.glob(os.path.join(case_dir, "*.sim"))
        # Result files are versioned by setup_id so re-prepare can coexist with
        # earlier evidence files.
        result_files = glob.glob(os.path.join(case_dir, "solver_result*.json"))
        action_files = glob.glob(os.path.join(case_dir, "simcenter_actions.json"))
        bindings_files = glob.glob(os.path.join(case_dir, "bindings.json"))
        binding_validation = {"valid": False, "errors": ["缺少 bindings.json"], "warnings": []}
        if bindings_files:
            with open(bindings_files[0], "r", encoding="utf-8") as fh:
                binding = json.load(fh)
            binding_validation = validate_bindings(binding)
        stages = _run_state_stages(root, item)
        has_geometry = os.path.isfile(prt_path)
        if stages is not None:
            failed = next(
                (name for name, record in stages.items() if _stage_status(stages, name) in {"failed", "error"}),
                "",
            )
            solved = _stage_done(stages, "solve", "solved")
            exported = _stage_done(stages, "export", "exported")
            fem_ready = _stage_done(stages, "fem", "mesh", "setup")
            sim_ready = _stage_done(stages, "sim", "setup")
            geometry_ready = _stage_done(stages, "geometry", "cad", "prepare")
            if failed:
                status = f"{failed}_failed"
            elif exported:
                status = "solver_exported"
            elif solved:
                status = "solved_result_available"
            elif fem_ready and sim_ready:
                status = "simcenter_container_ready"
            elif geometry_ready:
                status = "ready_for_simcenter" if binding_validation["valid"] else "bindings_incomplete"
            elif action_files:
                status = "ready_for_geometry"
            else:
                status = "incomplete_workspace"
        else:
            # Legacy artifact names are informational only. Without a signed stage
            # record, FEM/SIM/result files cannot prove a solve or export occurred.
            solved = False
            exported = False
            if sim_files and fem_files:
                status = "simcenter_container_ready"
            elif has_geometry:
                status = "ready_for_simcenter" if binding_validation["valid"] else "bindings_incomplete"
            elif action_files:
                status = "ready_for_geometry"
            else:
                status = "incomplete_workspace"
        item.update({
            "status": status,
            "has_geometry": has_geometry,
            "has_fem": bool(fem_files),
            "has_sim": bool(sim_files),
            "has_solver_result": bool(result_files),
            "solved": solved,
            "exported": exported,
            "run_state_stages": stages,
            "bindings_valid": bool(binding_validation["valid"]),
            "binding_errors": list(binding_validation["errors"]),
        })
        counts[status] = counts.get(status, 0) + 1
    index["status_counts"] = dict(sorted(counts.items()))
    index["refreshed_at"] = _utc_now()
    _json_write(index_path, index)
    return index


def _iter_result_files(path: str) -> list[str]:
    if os.path.isfile(path):
        return [path]
    if not os.path.isdir(path):
        raise FileNotFoundError(path)
    return sorted(glob.glob(os.path.join(path, "**", "*.json"), recursive=True))


def _evidence_output(evidence: SolverEvidence, names: tuple[str, ...], unit: str | None = None) -> tuple[str, float] | None:
    for name in names:
        if name in evidence.outputs:
            return name, evidence.value(name, unit)
    return None


def _license_mode(evidence: SolverEvidence, allow_unverified_for_smoke: bool = False) -> str:
    mode = str(evidence.license_mode or "").strip().casefold().replace("-", "_")
    if mode in AUTHORIZED_LICENSE_MODES:
        return mode
    if allow_unverified_for_smoke:
        return mode or "unverified"
    raise ValueError(
        f"{evidence.path}: 结果没有声明正式授权 license_mode，只能联调，不能进入 CAE 认证"
    )


def _payload_digest(payload: dict) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _case_manifest(payload: dict, case_id: str) -> dict:
    if payload.get("case_id") == case_id:
        return payload
    cases = payload.get("cases")
    if isinstance(cases, dict):
        value = cases.get(case_id)
        if isinstance(value, dict):
            return value
    elif isinstance(cases, list):
        value = next((item for item in cases if item.get("case_id") == case_id), None)
        if isinstance(value, dict):
            return value
    raise ValueError(f"受信任清单中没有 {case_id}")


def _manifest_model_identity(manifest: dict, case_id: str) -> dict:
    identity = dict(manifest.get("model_identity") or {})
    for name in ("model_id", "content_digest", "input_digest"):
        if manifest.get(name) and not identity.get(name):
            identity[name] = manifest[name]
    identity.setdefault("model_id", case_id)
    if manifest.get("case") and not identity.get("input_digest"):
        identity["input_digest"] = _payload_digest(manifest["case"])
    return identity


def _manifest_setup_identity(manifest: dict) -> dict:
    identity = dict(manifest.get("setup_identity") or {})
    binding = manifest.get("binding") or {}
    if binding.get("digest") and not identity.get("binding_digest"):
        identity["binding_digest"] = binding["digest"]
    for name in ("setup_id", "setup_digest", "binding_digest", "capability_id", "fem_path", "sim_path"):
        if manifest.get(name) and not identity.get(name):
            identity[name] = manifest[name]
    capability = manifest.get("capability") or {}
    if capability.get("capability_id") and not identity.get("capability_id"):
        identity["capability_id"] = capability["capability_id"]
    identity.setdefault(
        "material_library_status", str(load_material_library().get("status") or "unknown"),
    )
    return identity


def _workspace_identity(workspace: str, case_id: str) -> dict:
    index_path = os.path.abspath(workspace)
    if os.path.isdir(index_path):
        index_path = os.path.join(index_path, "index.json")
    root = os.path.dirname(index_path)
    with open(index_path, "r", encoding="utf-8") as fh:
        index = json.load(fh)
    entry = _case_manifest(index, case_id)
    binding_path = entry.get("bindings_path") or os.path.join(
        entry.get("directory") or os.path.join(root, case_id), "bindings.json"
    )
    if not os.path.isabs(binding_path):
        binding_path = os.path.join(root, binding_path)
    with open(binding_path, "r", encoding="utf-8") as fh:
        binding = json.load(fh)
    if binding.get("case_id") != case_id:
        raise ValueError(f"工作区绑定不属于 {case_id}")
    validation = validate_bindings(binding, strict=True)
    if not validation["valid"]:
        raise ValueError("工作区绑定未通过严格校验：" + "；".join(validation["errors"]))
    geometry = binding["source_geometry"]
    if entry.get("source_part") and not os.path.normcase(os.path.abspath(entry["source_part"])) == os.path.normcase(
        os.path.abspath(geometry["source_part"])
    ):
        raise ValueError("工作区 index 与绑定的 source_part 不一致")
    binding_digest_value = binding["binding_digest"]
    if entry.get("binding_digest") and entry["binding_digest"] != binding_digest_value:
        raise ValueError("工作区 index 的 binding_digest 已过期")
    case_path = entry.get("case_path") or os.path.join(entry.get("directory") or root, "case.json")
    if not os.path.isabs(case_path):
        case_path = os.path.join(root, case_path)
    with open(case_path, "r", encoding="utf-8") as fh:
        case_payload = json.load(fh)
    if case_payload.get("case_id") != case_id:
        raise ValueError("工作区 case.json 与结果 case_id 不一致")
    return {
        "model_identity": {
            "model_id": str(entry.get("model_id") or geometry.get("model_id") or case_id),
            "content_digest": geometry["model_digest"],
            "input_digest": _payload_digest(case_payload),
        },
        "setup_identity": {
            "binding_digest": binding_digest_value,
            "material_library_status": str(load_material_library().get("status") or "unknown"),
        },
    }


def _merge_trusted_identity(base: dict, extra: dict) -> dict:
    merged = {key: dict(value) for key, value in base.items()}
    for section in ("model_identity", "setup_identity"):
        target = merged.setdefault(section, {})
        for key, value in (extra.get(section) or {}).items():
            if value in (None, ""):
                continue
            if target.get(key) not in (None, "") and target[key] != value:
                raise ValueError(f"受信任清单的 {section}.{key} 不一致")
            target[key] = value
    return merged


def _trusted_identity(
    case_id: str,
    workspace: str | None,
    setup_manifest: str | dict | None,
) -> dict | None:
    identity = _workspace_identity(workspace, case_id) if workspace else {}
    if setup_manifest:
        if isinstance(setup_manifest, dict):
            manifest = setup_manifest
        else:
            manifest_path = os.path.abspath(setup_manifest)
            if os.path.isdir(manifest_path):
                manifest_path = os.path.join(manifest_path, "setup_manifest.json")
            with open(manifest_path, "r", encoding="utf-8") as fh:
                manifest = json.load(fh)
        stored_setup_digest = str(manifest.get("setup_digest") or "")
        if stored_setup_digest:
            unsigned = dict(manifest)
            unsigned.pop("setup_digest", None)
            if _payload_digest(unsigned) != stored_setup_digest:
                raise ValueError("setup manifest 内容与 setup_digest 不一致")
        manifest = _case_manifest(manifest, case_id)
        embedded = (manifest.get("binding") or {}).get("payload")
        if embedded is not None:
            if embedded.get("case_id") != case_id or embedded.get("binding_digest") != (manifest.get("binding") or {}).get("digest"):
                raise ValueError("setup manifest 内嵌 binding 身份不一致")
            if binding_digest(embedded) != embedded["binding_digest"]:
                raise ValueError("setup manifest 内嵌 binding_digest 无效")
            validation = validate_bindings(embedded, strict=True)
            if not validation["valid"]:
                raise ValueError("setup manifest 内嵌 binding 未通过严格校验")
        extra = {
            "model_identity": _manifest_model_identity(manifest, case_id),
            "setup_identity": _manifest_setup_identity(manifest),
        }
        identity = _merge_trusted_identity(identity, extra)
    if not identity:
        return None
    model = identity.get("model_identity") or {}
    setup = identity.get("setup_identity") or {}
    if not model.get("model_id") or not model.get("content_digest"):
        raise ValueError("受信任清单缺少 model_id/content_digest")
    if not model.get("input_digest") and not setup.get("binding_digest"):
        raise ValueError("受信任清单缺少 binding/input digest")
    model.setdefault("input_digest", setup["binding_digest"])
    setup.setdefault("binding_digest", model["input_digest"])
    return identity


def _verify_setup_identity(payload: dict, evidence: SolverEvidence, trusted: dict) -> None:
    setup = payload.get("setup_identity") or {}
    if not isinstance(setup, dict):
        raise ValueError("setup_identity 必须是对象")
    expected_setup = trusted.get("setup_identity") or {}
    expected_binding = expected_setup.get("binding_digest")
    actual_binding = (
        setup.get("binding_digest")
        or payload.get("binding_digest")
        or getattr(evidence, "binding_digest", "")
        or evidence.input_digest
    )
    if expected_binding and actual_binding != expected_binding:
        raise ValueError("结果 binding_digest 与受信任绑定不一致")
    expected_input = (trusted.get("model_identity") or {}).get("input_digest")
    if expected_input and evidence.input_digest != expected_input:
        raise ValueError("结果 input_digest 与受信任 case 输入不一致")
    expected_setup_digest = expected_setup.get("setup_digest")
    actual_setup_digest = setup.get("setup_digest") or payload.get("setup_digest") or getattr(evidence, "setup_digest", "")
    if expected_setup_digest and actual_setup_digest != expected_setup_digest:
        raise ValueError("结果 setup_digest 与受信任 setup manifest 不一致")


def ingest_results(
    batch_path: str,
    results_path: str,
    *,
    allow_unverified_for_smoke: bool = False,
    workspace: str | None = None,
    setup_manifest: str | dict | None = None,
) -> dict:
    """读取结果；只有受信任工作区/设置清单验证的生产结果可进入认证。"""
    with open(batch_path, "r", encoding="utf-8") as fh:
        batch = json.load(fh)
    case_map = {item["case_id"]: item for item in batch.get("cases", [])}
    records = []
    rejected = []
    seen_case_ids = set()
    for path in _iter_result_files(results_path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
            case_id = str(payload.get("case_id") or "")
            case = case_map.get(case_id)
            if case is None:
                raise ValueError("case_id 不在当前 batch 中")
            if case_id in seen_case_ids:
                raise ValueError(f"重复 case_id={case_id}；网格研究或重跑结果必须显式版本化")
            trusted = _trusted_identity(case_id, workspace, setup_manifest)
            model = (trusted or {}).get("model_identity") or {}
            setup = (trusted or {}).get("setup_identity") or {}
            evidence = load_solver_evidence(
                path,
                expected_item=case["check_item_id"],
                expected_case_id=case_id,
                expected_batch_id=str(batch.get("batch_id") or "") if trusted else "",
                expected_model_id=str(model.get("model_id") or ""),
                expected_digest=str(model.get("content_digest") or ""),
                expected_input_digest=str(model.get("input_digest") or "") if trusted else "",
                expected_setup_digest=str(setup.get("setup_digest") or ""),
                expected_binding_digest=str(setup.get("binding_digest") or ""),
                expected_capability_id=str(setup.get("capability_id") or ""),
                required_outputs=case.get("required_output_units") or case["expected_units"],
                require_converged=True,
                require_native_evidence=bool(trusted),
            )
            for name, unit in (case.get("required_output_units") or case["expected_units"]).items():
                evidence.value(name, unit)
            warnings = []
            if trusted:
                _verify_setup_identity(payload, evidence, trusted)
            else:
                if not evidence.model_id:
                    raise ValueError("standalone 结果必须提供非空 model_identity.model_id")
                warnings.append("standalone 结果未由受信任工作区验证，不能用于认证")
            license_mode = _license_mode(evidence, allow_unverified_for_smoke)
            evidence_source = str(getattr(evidence, "evidence_source", "cae_solver") or "cae_solver")
            smoke = bool(
                allow_unverified_for_smoke
                or license_mode not in PRODUCTION_LICENSE_MODES
                or evidence_source != "cae_solver"
            )
            if license_mode == "evaluation":
                warnings.append("evaluation 许可证结果不能用于生产认证")
            if smoke and license_mode != "evaluation":
                warnings.append("smoke 结果不能用于生产认证")
            material_status = str(setup.get("material_library_status") or "unknown")
            if trusted and material_status != "released":
                warnings.append("材料库不是 released 状态，不能用于生产认证")
            eligible = bool(
                trusted
                and not smoke
                and license_mode in PRODUCTION_LICENSE_MODES
                and material_status == "released"
            )
            source = "cae_smoke" if smoke else "cae_solver"
            solver = evidence.as_dict()
            solver["source"] = source
            seen_case_ids.add(case_id)
            records.append({
                "case_id": case_id,
                "check_item_id": case["check_item_id"],
                "solver_case_id": evidence.case_id,
                "license_mode": license_mode,
                "source": source,
                "smoke": smoke,
                "identity_verified": bool(trusted),
                "material_library_status": material_status,
                "certification_eligible": eligible,
                "warnings": warnings,
                "solver": solver,
                "outputs": evidence.outputs,
                "quality": payload.get("quality") or {},
            })
        except Exception as exc:
            rejected.append({"path": path, "reason": str(exc)})
    return {
        "schema_version": "1.0.0",
        "batch_id": batch.get("batch_id", ""),
        "created_at": _utc_now(),
        "allow_unverified_for_smoke": bool(allow_unverified_for_smoke),
        "accepted": records,
        "rejected": rejected,
        "accepted_count": len(records),
        "rejected_count": len(rejected),
        "contains_smoke_results": any(record["smoke"] for record in records),
        "certification_eligible": bool(records) and all(record["certification_eligible"] for record in records),
    }


def _metric_summary(errors: list[float], rel_pct: list[float], bias: list[float]) -> dict:
    if not errors:
        return {"n": 0}
    return {
        "n": len(errors),
        "median_abs_error": statistics.median(errors),
        "mean_abs_error": statistics.fmean(errors),
        "rmse": math.sqrt(statistics.fmean(error * error for error in errors)),
        "max_abs_error": max(errors),
        "median_relative_error_pct": statistics.median(rel_pct) if rel_pct else None,
        "within_5pct": sum(v <= 5.0 for v in rel_pct) / len(rel_pct) if rel_pct else None,
        "within_10pct": sum(v <= 10.0 for v in rel_pct) / len(rel_pct) if rel_pct else None,
        "mean_bias": statistics.fmean(bias),
    }


def calibration_report(batch_path: str, records_path: str) -> dict:
    with open(batch_path, "r", encoding="utf-8") as fh:
        batch = json.load(fh)
    with open(records_path, "r", encoding="utf-8") as fh:
        record_payload = json.load(fh)
    case_map = {item["case_id"]: item for item in batch.get("cases", [])}
    record_map = {item["case_id"]: item for item in record_payload.get("accepted", [])}
    comparisons = []
    errors_by_quantity: dict[str, list[float]] = {}
    rel_by_quantity: dict[str, list[float]] = {}
    bias_by_quantity: dict[str, list[float]] = {}
    decisions = []

    for case_id, case in case_map.items():
        record = record_map.get(case_id)
        if record is None:
            continue
        formula = load_formula(case["check_item_id"])
        outputs = record["outputs"]
        decision_inputs = case.get("rule_formula_inputs") or case["formula_inputs"]
        for name, expected in case["expected_values"].items():
            if name not in outputs:
                continue
            solved = float(outputs[name]["value"])
            error = abs(solved - float(expected))
            denom = max(abs(solved), abs(float(expected)), 1e-12)
            relative = error / denom * 100.0
            quantity_key = f"{case['check_item_id']}:{name}"
            errors_by_quantity.setdefault(quantity_key, []).append(error)
            rel_by_quantity.setdefault(quantity_key, []).append(relative)
            bias_by_quantity.setdefault(quantity_key, []).append(float(expected) - solved)
            comparisons.append({
                "case_id": case_id,
                "quantity": name,
                "formula": float(expected),
                "solver": solved,
                "abs_error": error,
                "relative_error_pct": relative,
                "unit": case["expected_units"][name],
            })

        overrides: dict[str, float] = {}
        if case["check_item_id"] == "PERF-01":
            delta = _evidence_output_value(outputs, ("delta_t_c",))
            absolute = _evidence_output_value(outputs, ("maximum_temperature_c", "absolute_temperature_c", "temperature_c"))
            if absolute is None and delta is not None:
                absolute = float(case["formula_inputs"]["ambient_temp_c"]) + delta
            if delta is not None:
                overrides["delta_t_c"] = delta
            if absolute is not None:
                overrides["temperature_c"] = absolute
                overrides["absolute_temperature_c"] = absolute
        else:
            insertion = _evidence_output_value(outputs, ("insertion_force_n",))
            withdrawal = _evidence_output_value(outputs, ("withdrawal_force_n",))
            factors = (case.get("formula_scaling") or {}).get("output_factors") or {}
            if insertion is not None:
                overrides["insertion_force_n"] = insertion * float(factors.get("insertion_force_n", 1.0))
            if withdrawal is not None:
                overrides["withdrawal_force_n"] = withdrawal * float(factors.get("withdrawal_force_n", 1.0))
        if overrides:
            solver_rules = formula.apply_solver_overrides(decision_inputs, overrides)
            formula_rules = formula.evaluate(decision_inputs)
            for f_item, s_item in zip(formula_rules.decisions, solver_rules.decisions):
                decisions.append({
                    "case_id": case_id,
                    "condition": s_item.condition,
                    "formula_triggered": f_item.triggered,
                    "solver_triggered": s_item.triggered,
                    "agreement": f_item.triggered == s_item.triggered,
                })

    summary = {
        quantity: _metric_summary(errors_by_quantity[quantity], rel_by_quantity[quantity], bias_by_quantity[quantity])
        for quantity in errors_by_quantity
    }
    by_item: dict[str, list[bool]] = {}
    for item in decisions:
        check_item_id = case_map[item["case_id"]]["check_item_id"]
        by_item.setdefault(check_item_id, []).append(item["agreement"])
    decision_agreement = {
        item: sum(values) / len(values) if values else None
        for item, values in by_item.items()
    }
    return {
        "schema_version": "1.0.0",
        "batch_id": batch.get("batch_id", ""),
        "created_at": _utc_now(),
        "accepted_result_count": len(record_map),
        "rejected_result_count": len(record_payload.get("rejected", [])),
        "calibration_status": "complete" if record_map else "no_results",
        "summary": summary,
        "decision_agreement": decision_agreement,
        "comparisons": comparisons,
        "decisions": decisions,
        "rejected": record_payload.get("rejected", []),
    }


def _evidence_output_value(outputs: dict, names: tuple[str, ...]) -> float | None:
    for name in names:
        if name in outputs:
            return float(outputs[name]["value"])
    return None


def render_markdown(report: dict) -> str:
    lines = [
        "# PERF CAE 校准报告",
        "",
        f"- Batch：`{report.get('batch_id', '')}`",
        f"- 状态：`{report.get('calibration_status')}`",
        f"- 已接收结果：{report.get('accepted_result_count', 0)}",
        f"- 已拒绝结果：{report.get('rejected_result_count', 0)}",
        "",
        "## 误差汇总",
        "",
        "| 指标 | n | 中位绝对误差 | 平均绝对误差 | RMSE | ≤5% | ≤10% |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, item in sorted(report.get("summary", {}).items()):
        if not item.get("n"):
            continue
        def pct(value):
            return "—" if value is None else f"{100.0 * value:.1f}%"
        lines.append(
            f"| {name} | {item['n']} | {item['median_abs_error']:.6g} | "
            f"{item['mean_abs_error']:.6g} | {item['rmse']:.6g} | "
            f"{pct(item['within_5pct'])} | {pct(item['within_10pct'])} |"
        )
    lines.extend(["", "## 判定一致率", ""])
    if report.get("decision_agreement"):
        for item, value in sorted(report["decision_agreement"].items()):
            lines.append(f"- {item}：{100.0 * value:.1f}%" if value is not None else f"- {item}：无数据")
    else:
        lines.append("没有可对比的判定结果。")
    if report.get("rejected"):
        lines.extend(["", "## 被拒绝的结果", ""])
        for item in report["rejected"]:
            lines.append(f"- `{os.path.basename(item['path'])}`：{item['reason']}")
    return "\n".join(lines) + "\n"


def certification_report(
    batch_path: str,
    records_path: str,
    *,
    min_samples_per_item: int = 20,
    max_median_relative_error_pct: float = 5.0,
    min_decision_agreement: float = 0.95,
    max_mesh_sensitivity_pct: float | None = None,
) -> dict:
    calibration = calibration_report(batch_path, records_path)
    with open(batch_path, "r", encoding="utf-8") as fh:
        batch = json.load(fh)
    with open(records_path, "r", encoding="utf-8") as fh:
        records = json.load(fh)
    items = list(batch.get("items") or SUPPORTED_ITEMS)
    case_map = {case["case_id"]: case for case in batch.get("cases") or []}
    raw_accepted = list(records.get("accepted") or [])
    accepted = [
        record for record in raw_accepted
        if record.get("case_id") in case_map
        and record.get("check_item_id") == case_map[record["case_id"]].get("check_item_id")
    ]
    blockers = []
    checks = []
    mesh_limits = _mesh_sensitivity_limits()
    if records.get("batch_id") and records.get("batch_id") != batch.get("batch_id"):
        blockers.append("records 文件属于其他 batch，不能合并认证")
    if len(accepted) != len(raw_accepted):
        blockers.append("结果集包含不属于当前 batch 或 check_item 不匹配的记录")
    case_ids = [record.get("case_id") for record in accepted]
    if len(set(case_ids)) != len(case_ids):
        blockers.append("结果集包含重复 case_id，不能重复计入样本数")
    if any(record.get("smoke") or record.get("source") in {"cae_smoke", "smoke_fixture", "smoke_solver"} for record in accepted) or records.get(
        "contains_smoke_results"
    ):
        blockers.append("结果集包含 smoke/evaluation 记录，不能认证")
    if any(not record.get("certification_eligible", False) for record in accepted):
        blockers.append("结果集包含未通过受信任工作区验证或不具备生产资格的记录")

    for item in items:
        item_records = [record for record in accepted if record.get("check_item_id") == item]
        mesh_limit = float(max_mesh_sensitivity_pct) if max_mesh_sensitivity_pct is not None else mesh_limits[item]
        if len(item_records) < min_samples_per_item:
            blockers.append(
                f"{item} 认证样本只有 {len(item_records)} 条，至少需要 {min_samples_per_item} 条"
            )
        if any(record.get("license_mode") not in PRODUCTION_LICENSE_MODES for record in item_records):
            blockers.append(f"{item} 含非生产授权的结果")
        acceptance = _case_definitions()[item].get("acceptance") or {}
        for record in item_records:
            quality = record.get("quality") or {}
            mesh_change = quality.get("mesh_sensitivity_relative_change_pct")
            if mesh_change is None:
                blockers.append(f"{item} 的 {record['case_id']} 缺少网格敏感性证据")
            elif not isinstance(mesh_change, (int, float)) or isinstance(mesh_change, bool) or not math.isfinite(float(mesh_change)) or float(mesh_change) < 0:
                blockers.append(f"{item} 的 {record['case_id']} 网格敏感性不是有效的非负有限数值")
            elif float(mesh_change) > mesh_limit:
                blockers.append(
                    f"{item} 的 {record['case_id']} 网格敏感性 "
                    f"{float(mesh_change):.2f}% 超过 {mesh_limit:.2f}%"
                )
            quality_name = (
                "energy_balance_relative_error" if item == "PERF-01" else "penetration_max_mm"
            )
            quality_value = quality.get(quality_name)
            quality_limit = float(
                0.02 if item == "PERF-01" else acceptance.get("penetration_limit_mm", 0.01)
            )
            if quality_value is None:
                blockers.append(f"{item} 的 {record['case_id']} 缺少 {quality_name} 质量证据")
            elif (
                not isinstance(quality_value, (int, float))
                or isinstance(quality_value, bool)
                or not math.isfinite(float(quality_value))
                or float(quality_value) < 0
            ):
                blockers.append(f"{item} 的 {record['case_id']} {quality_name} 不是有效的非负有限数值")
            elif float(quality_value) > quality_limit:
                blockers.append(
                    f"{item} 的 {record['case_id']} {quality_name}={float(quality_value):.6g} "
                    f"超过 {quality_limit:.6g}"
                )

        quantity_names = (
            ("delta_t_c",)
            if item == "PERF-01"
            else ("insertion_force_n", "withdrawal_force_n")
        )
        for quantity in quantity_names:
            metric = calibration.get("summary", {}).get(f"{item}:{quantity}")
            if not metric or metric.get("n", 0) == 0:
                blockers.append(f"{item}:{quantity} 没有可比较结果")
                continue
            median_relative = metric.get("median_relative_error_pct")
            if median_relative is None or float(median_relative) > max_median_relative_error_pct:
                blockers.append(
                    f"{item}:{quantity} 中位相对误差 {median_relative}% "
                    f"超过 {max_median_relative_error_pct:.2f}%"
                )
        agreement = calibration.get("decision_agreement", {}).get(item)
        if agreement is None or float(agreement) < min_decision_agreement:
            blockers.append(
                f"{item} 判定一致率 {agreement} 低于 {100.0 * min_decision_agreement:.1f}%"
            )
        checks.append({
            "check_item_id": item,
            "sample_count": len(item_records),
            "minimum_sample_count": min_samples_per_item,
            "decision_agreement": agreement,
            "max_mesh_sensitivity_pct": mesh_limit,
        })

    return {
        "schema_version": "1.0.0",
        "batch_id": batch.get("batch_id", ""),
        "created_at": _utc_now(),
        "status": "certified" if not blockers else "not_ready",
        "blockers": sorted(set(blockers)),
        "checks": checks,
        "requirements": {
            "min_samples_per_item": min_samples_per_item,
            "max_median_relative_error_pct": max_median_relative_error_pct,
            "min_decision_agreement": min_decision_agreement,
            "max_mesh_sensitivity_pct": max_mesh_sensitivity_pct,
            "max_mesh_sensitivity_pct_by_item": {
                item: float(max_mesh_sensitivity_pct) if max_mesh_sensitivity_pct is not None else mesh_limits[item]
                for item in items
            },
            "authorized_license_required": True,
            "trusted_identity_required": True,
            "evaluation_and_smoke_eligible": False,
        },
        "calibration": calibration,
    }


def render_certification_markdown(report: dict) -> str:
    lines = [
        "# PERF CAE 认证检查",
        "",
        f"- Batch：`{report.get('batch_id', '')}`",
        f"- 状态：`{report.get('status')}`",
        "",
        "## 项目进度",
        "",
        "| 检查项 | 已接收样本 | 最低要求 | 判定一致率 |",
        "|---|---:|---:|---:|",
    ]
    for item in report.get("checks", []):
        agreement = item.get("decision_agreement")
        agreement_text = "—" if agreement is None else f"{100.0 * agreement:.1f}%"
        lines.append(
            f"| {item['check_item_id']} | {item['sample_count']} | "
            f"{item['minimum_sample_count']} | {agreement_text} |"
        )
    lines.extend(["", "## 阻断项", ""])
    if report.get("blockers"):
        lines.extend(f"- {blocker}" for blocker in report["blockers"])
    else:
        lines.append("无。")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="PERF CAE 批量、回填与校准")
    sub = parser.add_subparsers(dest="command", required=True)

    generate = sub.add_parser("generate")
    generate.add_argument("--count", type=int, default=DEFAULT_COUNT)
    generate.add_argument("--seed", type=int, default=DEFAULT_SEED)
    generate.add_argument("--item", action="append", choices=SUPPORTED_ITEMS)
    generate.add_argument("--out", required=True)

    geometry = sub.add_parser("geometry-request")
    geometry.add_argument("--batch", required=True)
    geometry.add_argument("--case-id", required=True)
    geometry.add_argument("--prt", required=True)
    geometry.add_argument("--out", required=True)

    materialize = sub.add_parser("materialize")
    materialize.add_argument("--batch", required=True)
    materialize.add_argument("--out-dir", required=True)

    status = sub.add_parser("status")
    status.add_argument("--workspace", required=True)

    binding_validate = sub.add_parser("validate-bindings")
    binding_validate.add_argument("--binding", required=True)
    binding_validate.add_argument("--out")

    ingest = sub.add_parser("ingest")
    ingest.add_argument("--batch", required=True)
    ingest.add_argument("--results", required=True)
    ingest.add_argument("--out", required=True)
    ingest.add_argument("--allow-unverified-for-smoke", action="store_true")
    ingest.add_argument("--workspace", help="受信任 materialize 工作区或 index.json")
    ingest.add_argument("--setup-manifest", help="受信任 setup manifest JSON")

    report = sub.add_parser("report")
    report.add_argument("--batch", required=True)
    report.add_argument("--records", required=True)
    report.add_argument("--out", required=True)

    certify = sub.add_parser("certify")
    certify.add_argument("--batch", required=True)
    certify.add_argument("--records", required=True)
    certify.add_argument("--out", required=True)
    certify.add_argument("--min-samples", type=int, default=20)
    certify.add_argument("--max-median-relative-error-pct", type=float, default=5.0)
    certify.add_argument("--min-decision-agreement", type=float, default=0.95)
    certify.add_argument("--max-mesh-sensitivity-pct", type=float)

    args = parser.parse_args()
    if args.command == "generate":
        payload = generate_batch(args.count, args.seed, tuple(args.item or SUPPORTED_ITEMS))
        path = _json_write(args.out, payload)
        print(path)
        print(f"cases={len(payload['cases'])} status={payload['status']}")
    elif args.command == "geometry-request":
        with open(args.batch, "r", encoding="utf-8") as fh:
            batch = json.load(fh)
        case = next((item for item in batch["cases"] if item["case_id"] == args.case_id), None)
        if case is None:
            raise SystemExit(f"batch 中不存在 {args.case_id}")
        request = build_geometry_request(case, args.prt)
        path = _json_write(args.out, request)
        print(path)
        print(f"geometry={request['kind']} prt={request['out_path']}")
    elif args.command == "materialize":
        payload = materialize_batch(args.batch, args.out_dir)
        print(os.path.join(payload["root"], "index.json"))
        print(f"cases={len(payload['cases'])} status={payload['status']}")
    elif args.command == "status":
        payload = refresh_workspace_status(args.workspace)
        print(os.path.join(payload["root"], "index.json"))
        print(json.dumps(payload.get("status_counts") or {}, ensure_ascii=False))
    elif args.command == "validate-bindings":
        with open(args.binding, "r", encoding="utf-8") as fh:
            binding = json.load(fh)
        payload = validate_bindings(binding)
        if args.out:
            _json_write(args.out, payload)
            print(args.out)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        if not payload["valid"]:
            raise SystemExit(1)
    elif args.command == "ingest":
        payload = ingest_results(
            args.batch,
            args.results,
            allow_unverified_for_smoke=args.allow_unverified_for_smoke,
            workspace=args.workspace,
            setup_manifest=args.setup_manifest,
        )
        path = _json_write(args.out, payload)
        print(path)
        print(
            f"accepted={payload['accepted_count']} rejected={payload['rejected_count']}"
        )
    elif args.command == "report":
        payload = calibration_report(args.batch, args.records)
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(render_markdown(payload))
        print(args.out)
        print(f"status={payload['calibration_status']}")
    else:
        payload = certification_report(
            args.batch,
            args.records,
            min_samples_per_item=args.min_samples,
            max_median_relative_error_pct=args.max_median_relative_error_pct,
            min_decision_agreement=args.min_decision_agreement,
            max_mesh_sensitivity_pct=args.max_mesh_sensitivity_pct,
        )
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(render_certification_markdown(payload))
        print(args.out)
        print(f"status={payload['status']} blockers={len(payload['blockers'])}")


if __name__ == "__main__":
    main()
