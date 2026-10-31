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
import json
import math
import os
import random
import statistics
from datetime import datetime, timezone
from ...contracts import RuleBook
from .cae_bindings import binding_digest, create_binding_draft, validate_bindings
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


def _case_catalog() -> dict[str, str]:
    with open(CASES_PATH, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    return {item["check_item_id"]: item["case_id"] for item in payload["cases"]}


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
    output_names = (
        "delta_t_c",
        "maximum_temperature_c",
        "total_resistance_ohm",
        "joule_power_w",
        "voltage_drop_v",
    )
    expected = {
        "delta_t_c": result.values["delta_t_c"],
        "maximum_temperature_c": result.values["absolute_temperature_c"],
        "total_resistance_ohm": result.values["total_resistance_ohm"],
        "joule_power_w": result.values["power_w"],
        "voltage_drop_v": result.values["voltage_drop_v"],
    }
    return {
        "case_id": f"PERF01-ET-{index + 1:04d}",
        "solver_case_id": case_id,
        "check_item_id": "PERF-01",
        "material": material,
        "formula_inputs": inputs,
        "geometry_request": {
            "type": "cylinder",
            "diameter_mm": 2.0 * math.sqrt(inputs["area_mm2"] / math.pi),
            "length_mm": inputs["length_mm"],
        },
        "boundary_conditions": {
            "current_a": inputs["current_a"],
            "ambient_temperature_c": inputs["ambient_temp_c"],
            "convection_h_w_m2k": inputs["h_w_m2k"],
            "radiation_emissivity": inputs["emissivity"],
            "contact_resistance_ohm_mm2": inputs["contact_resistance_ohm_mm2"],
        },
        "formula_outputs": dict(zip(output_names, expected.values())),
        "expected_values": expected,
        "expected_units": {
            "delta_t_c": "degC",
            "maximum_temperature_c": "degC",
            "total_resistance_ohm": "ohm",
            "joule_power_w": "W",
            "voltage_drop_v": "V",
        },
        "formula_decisions": _decision_payload(result),
    }


def _perf02_case(index: int, values: dict[str, list[float]], materials: list[str], params: dict, case_id: str) -> dict:
    material = materials[index % len(materials)]
    e_gpa = params["materials"][material]["e_gpa"]
    spec = {
        "length_mm": values["length_mm"][index],
        "width_mm": values["width_mm"][index],
        "thickness_mm": values["thickness_mm"][index],
        "overlap_mm": values["overlap_mm"][index],
        "contacts": params["contacts"],
        "lead_angle_deg": params["lead_angle_deg"],
        "friction_coeff": values["friction_coeff"][index],
    }
    inputs = _contact_inputs(spec, e_gpa, params)
    result = evaluate_contact(spec, e_gpa, params, formula=load_formula("PERF-02"))
    expected = {
        "insertion_force_n": result.values["insertion_force_n"],
        "withdrawal_force_n": result.values["withdrawal_force_n"],
        "maximum_normal_contact_force_n": result.values["normal_force_n"],
    }
    return {
        "case_id": f"PERF02-CONTACT-{index + 1:04d}",
        "solver_case_id": case_id,
        "check_item_id": "PERF-02",
        "material": material,
        "formula_inputs": inputs,
        "geometry_request": {
            "type": "cantilever_contact_pair",
            "length_mm": spec["length_mm"],
            "width_mm": spec["width_mm"],
            "thickness_mm": spec["thickness_mm"],
            "interference_mm": spec["overlap_mm"],
        },
        "contact_conditions": {
            "method": "penalty",
            "friction_model": "coulomb",
            "friction_coefficient": spec["friction_coeff"],
            "contact_count": spec["contacts"],
            "lead_angle_deg": spec["lead_angle_deg"],
        },
        "expected_values": expected,
        "expected_units": {
            "insertion_force_n": "N",
            "withdrawal_force_n": "N",
            "maximum_normal_contact_force_n": "N",
        },
        "formula_outputs": result.values,
        "formula_decisions": _decision_payload(result),
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
            "accepted_license_modes": sorted(AUTHORIZED_LICENSE_MODES),
            "note": "求解结果必须声明正式授权，否则只允许做接口联调，不进入认证报告。",
        },
        "cases": cases,
    }


def build_geometry_request(case: dict, out_path: str) -> dict:
    geometry = case.get("geometry_request") or {}
    kind = geometry.get("type")
    if kind == "cylinder":
        return {
            "case_id": case["case_id"],
            "kind": "cylinder",
            "out_path": os.path.abspath(out_path),
            "diameter_mm": float(geometry["diameter_mm"]),
            "length_mm": float(geometry["length_mm"]),
        }
    if kind == "cantilever_contact_pair":
        return {
            "case_id": case["case_id"],
            "kind": "cantilever_contact_pair",
            "out_path": os.path.abspath(out_path),
            "length_mm": float(geometry["length_mm"]),
            "width_mm": float(geometry["width_mm"]),
            "thickness_mm": float(geometry["thickness_mm"]),
            "plate_gap_mm": float(geometry["interference_mm"]) * 0.5,
        }
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


def refresh_workspace_status(workspace: str) -> dict:
    """根据工作目录中实际存在的产物刷新每个工况的状态。"""
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
        result_files = glob.glob(os.path.join(case_dir, "solver_result.json"))
        action_files = glob.glob(os.path.join(case_dir, "simcenter_actions.json"))
        bindings_files = glob.glob(os.path.join(case_dir, "bindings.json"))
        binding_validation = {"valid": False, "errors": ["缺少 bindings.json"], "warnings": []}
        if bindings_files:
            with open(bindings_files[0], "r", encoding="utf-8") as fh:
                binding = json.load(fh)
            binding_validation = validate_bindings(binding)
        if result_files and fem_files and sim_files:
            status = "solved_result_available"
        elif sim_files and fem_files:
            status = "simcenter_container_ready"
        elif prt_path and os.path.isfile(prt_path) and not binding_validation["valid"]:
            status = "bindings_incomplete"
        elif prt_path and os.path.isfile(prt_path) and binding_validation["valid"]:
            status = "ready_for_simcenter"
        elif prt_path and os.path.isfile(prt_path):
            status = "geometry_ready"
        elif action_files:
            status = "ready_for_geometry"
        else:
            status = "incomplete_workspace"
        item.update({
            "status": status,
            "has_geometry": os.path.isfile(prt_path),
            "has_fem": bool(fem_files),
            "has_sim": bool(sim_files),
            "has_solver_result": bool(result_files),
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


def ingest_results(
    batch_path: str,
    results_path: str,
    *,
    allow_unverified_for_smoke: bool = False,
) -> dict:
    with open(batch_path, "r", encoding="utf-8") as fh:
        batch = json.load(fh)
    case_map = {item["case_id"]: item for item in batch.get("cases", [])}
    records = []
    rejected = []
    for path in _iter_result_files(results_path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
            case_id = str(payload.get("case_id") or "")
            case = case_map.get(case_id)
            if case is None:
                rejected.append({"path": path, "reason": "case_id 不在当前 batch 中"})
                continue
            evidence = load_solver_evidence(
                path,
                expected_item=case["check_item_id"],
                expected_model_id=str((payload.get("model_identity") or {}).get("model_id") or ""),
                require_converged=True,
            )
            for name, unit in case["expected_units"].items():
                if name in evidence.outputs:
                    evidence.value(name, unit)
            records.append({
                "case_id": case_id,
                "check_item_id": case["check_item_id"],
                "solver_case_id": evidence.case_id,
                "license_mode": _license_mode(evidence, allow_unverified_for_smoke),
                "solver": evidence.as_dict(),
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
            if insertion is not None:
                overrides["insertion_force_n"] = insertion
            if withdrawal is not None:
                overrides["withdrawal_force_n"] = withdrawal
        if overrides:
            solver_rules = formula.apply_solver_overrides(case["formula_inputs"], overrides)
            formula_rules = formula.evaluate(case["formula_inputs"])
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
    max_mesh_sensitivity_pct: float = 3.0,
) -> dict:
    calibration = calibration_report(batch_path, records_path)
    with open(batch_path, "r", encoding="utf-8") as fh:
        batch = json.load(fh)
    with open(records_path, "r", encoding="utf-8") as fh:
        records = json.load(fh)
    items = list(batch.get("items") or SUPPORTED_ITEMS)
    accepted = list(records.get("accepted") or [])
    blockers = []
    checks = []

    for item in items:
        item_records = [record for record in accepted if record.get("check_item_id") == item]
        if len(item_records) < min_samples_per_item:
            blockers.append(
                f"{item} 认证样本只有 {len(item_records)} 条，至少需要 {min_samples_per_item} 条"
            )
        if any(record.get("license_mode") not in AUTHORIZED_LICENSE_MODES for record in item_records):
            blockers.append(f"{item} 含未声明正式授权的结果")
        for record in item_records:
            mesh_change = (
                (record.get("quality") or {}).get("mesh_sensitivity_relative_change_pct")
            )
            if mesh_change is None:
                blockers.append(f"{item} 的 {record['case_id']} 缺少网格敏感性证据")
            elif float(mesh_change) > max_mesh_sensitivity_pct:
                blockers.append(
                    f"{item} 的 {record['case_id']} 网格敏感性 "
                    f"{float(mesh_change):.2f}% 超过 {max_mesh_sensitivity_pct:.2f}%"
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
            "authorized_license_required": True,
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
    certify.add_argument("--max-mesh-sensitivity-pct", type=float, default=3.0)

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
