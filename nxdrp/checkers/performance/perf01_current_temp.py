# -*- coding: utf-8 -*-
"""PERF-01 载流–温升。

计算由 ``rules/perf_formula_v2.json`` 的稳态电热公式完成，是否失败由同一
规则里的 NX 风格比较式决定。回归树只保留为区间标定，不再决定 Finding。
"""

from __future__ import annotations

import math
import os

from ...checkers.base import BaseChecker, CheckContext
from ...contracts import Finding, ModelBundle, Part
from .physics import RULE_PARAMS, canonical_material
from .rule_engine import FormulaProgram, FormulaResult, load_formula
from .solver_evidence import SolverEvidence, SolverEvidenceError, load_solver_evidence
from .tree_model import apply_interval, load

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(HERE, "data", "model.json")

_MODEL = None


def model_path() -> str:
    return MODEL_PATH


def load_model():
    global _MODEL
    if _MODEL is None:
        _MODEL = load(MODEL_PATH)
    return _MODEL


def default_formula() -> FormulaProgram:
    return load_formula("PERF-01")


def _formula_inputs(
    area_mm2: float,
    length_mm: float,
    rho_ohm_m: float,
    current_a: float,
    h_w_m2k: float,
    **overrides,
) -> dict:
    inferred_temp_coeff = RULE_PARAMS["materials"]["Cu"]["temp_coeff_per_c"]
    for material in RULE_PARAMS["materials"].values():
        if math.isclose(float(rho_ohm_m), float(material["rho_ohm_m"]), rel_tol=1e-12):
            inferred_temp_coeff = float(material["temp_coeff_per_c"])
            break
    values = {
        "area_mm2": float(area_mm2),
        "length_mm": float(length_mm),
        "rho_ohm_m": float(rho_ohm_m),
        "temp_coeff_per_c": inferred_temp_coeff,
        "current_a": float(current_a),
        "ambient_temp_c": float(RULE_PARAMS["ambient_temp_c"]),
        "h_w_m2k": float(h_w_m2k),
        "emissivity": float(RULE_PARAMS["emissivity"]),
        "contact_resistance_ohm_mm2": float(RULE_PARAMS["contact_resistance_ohm_mm2"]),
        "reference_temp_c": float(RULE_PARAMS["reference_temp_c"]),
        "max_solver_rise_c": float(RULE_PARAMS["max_solver_rise_c"]),
        "max_rise_c": float(RULE_PARAMS["max_rise_c"]),
        "max_temperature_c": float(RULE_PARAMS["max_temperature_c"]),
    }
    values.update({key: float(value) for key, value in overrides.items() if value is not None})
    return values


def evaluate_formula(
    area_mm2: float,
    length_mm: float,
    rho_ohm_m: float,
    current_a: float,
    h_w_m2k: float,
    *,
    formula: FormulaProgram | None = None,
    **overrides,
) -> FormulaResult:
    program = formula or default_formula()
    return program.evaluate(_formula_inputs(area_mm2, length_mm, rho_ohm_m, current_a, h_w_m2k, **overrides))


def _solver_evidence(model: ModelBundle, params: dict) -> SolverEvidence | None:
    path = str(params.get("solver_result_path") or "").strip()
    if not path:
        return None
    evidence = load_solver_evidence(
        path,
        expected_item="PERF-01",
        expected_model_id=model.model_id,
        expected_digest=model.content_digest(),
        require_authorized=True,
    )
    evidence.value("delta_t_c", "degC")
    evidence.value("maximum_temperature_c", "degC")
    return evidence


def predict_raw(
    area_mm2: float,
    length_mm: float,
    rho_ohm_m: float,
    current_a: float,
    h_w_m2k: float,
    *,
    formula: FormulaProgram | None = None,
    **overrides,
) -> dict:
    """给一组工况，返回公式点值、标定区间和规则判定。

    ``delta_t_low_c``/``delta_t_high_c`` 只表达标定误差，不参与 PASS/FAIL。
    """
    result = evaluate_formula(
        area_mm2, length_mm, rho_ohm_m, current_a, h_w_m2k,
        formula=formula, **overrides,
    )
    point = max(0.0, float(result.values["delta_t_c"]))
    try:
        model = load_model()
        low, high = apply_interval(point, model["q_low"], model["q_high"])
    except (OSError, ValueError, KeyError):
        low, high = point, point
    return {
        "delta_t_c": point,
        "delta_t_low_c": low,
        "delta_t_high_c": high,
        "absolute_temperature_c": float(result.values["absolute_temperature_c"]),
        "total_resistance_ohm": float(result.values["total_resistance_ohm"]),
        "power_w": float(result.values["power_w"]),
        "voltage_drop_v": float(result.values["voltage_drop_v"]),
        "formula_id": result.formula_id,
        "formula_values": result.values,
        "decisions": [item.to_dict() for item in result.decisions],
        "alarm": any(item.triggered for item in result.decisions),
        "solver_iterations": result.iterations,
        "solver_residual_w": result.residual,
    }


def _span(params: dict, lo_key: str, hi_key: str, value: float, label: str) -> str:
    lo = float(params[lo_key])
    hi = float(params[hi_key])
    if value < lo or value > hi:
        return f"{label} {value:.4g} 超出适用范围 {lo:.4g}–{hi:.4g}"
    return ""


def condition_problem(params: dict) -> str:
    """工况或模型文件不满足时返回原因，满足则返回空串。"""
    try:
        formula = default_formula()
        formula.validate()
    except Exception as exc:
        return f"PERF-01 公式无法读取：{exc}"
    trained = float(RULE_PARAMS["interval_confidence"])
    try:
        model = load_model()
    except Exception:
        model = None
    if model is not None:
        trained = float(model.get("interval_confidence", trained))
    asked = float(params.get("interval_confidence", trained))
    if abs(asked - trained) > 0.02:
        return f"规则要求区间置信度 {asked:.2f}，当前模型只标定了 {trained:.2f}"
    for key, label in (
        ("current_a", "电流"),
        ("ambient_temp_c", "环境温度"),
        ("convection_h_w_m2k", "对流换热系数"),
    ):
        if key not in params:
            return f"规则缺少 {key}"
    return (
        _span(params, "current_a_min", "current_a_max", float(params["current_a"]), "电流 A")
        or _span(params, "ambient_temp_c_min", "ambient_temp_c_max", float(params["ambient_temp_c"]), "环境温度 °C")
        or _span(params, "h_w_m2k_min", "h_w_m2k_max", float(params["convection_h_w_m2k"]), "对流换热系数")
    )


def cylinder_spec(face) -> dict | None:
    if face.solid_face_type != "cylindrical":
        return None
    if face.radius_diameter is None or float(face.radius_diameter) <= 0:
        return None
    if face.area is None or float(face.area) <= 0:
        return None
    radius = float(face.radius_diameter)
    if not face.is_radius:
        radius = radius / 2.0
    length = float(face.area) / (2.0 * math.pi * radius)
    return {
        "face_id": face.face_id,
        "radius_mm": radius,
        "length_mm": length,
        "area_mm2": math.pi * radius * radius,
        "cog": face.cog or face.point,
    }


def bottleneck(model: ModelBundle, part: Part, params: dict) -> tuple[dict | None, str]:
    specs = []
    for face in model.faces_of(part.part_id, "cylindrical"):
        spec = cylinder_spec(face)
        if spec is not None:
            specs.append(spec)
    if not specs:
        return None, "没有带半径和面积的圆柱面，无法估计载流截面积"
    spec = min(specs, key=lambda s: s["area_mm2"])
    area_problem = _span(params, "area_mm2_min", "area_mm2_max", spec["area_mm2"], "截面积 mm²")
    length_problem = _span(params, "length_mm_min", "length_mm_max", spec["length_mm"], "导体长度 mm")
    if area_problem or length_problem:
        return None, area_problem or length_problem
    return spec, ""


def conductor_parts(model: ModelBundle, params: dict) -> list[Part]:
    materials = params.get("materials") or {}
    found = []
    for part in model.parts:
        if canonical_material(part.material, materials):
            found.append(part)
    return found


def predict_working_condition(
    area_mm2: float,
    length_mm: float,
    material: str,
    params: dict | None = None,
) -> dict:
    """给截面积、长度、材料和工况，返回温升区间。不经过 3D 模型。

    检查项在温升低于允许值时不产出 Finding。要看这个数，调用这里。
    """
    merged = dict(RULE_PARAMS)
    if params:
        merged.update(params)
    problem = condition_problem(merged)
    if problem:
        return {"ok": False, "reason": problem}
    canon = canonical_material(material, merged.get("materials") or {})
    if canon is None:
        return {"ok": False, "reason": f"材料 {material} 不是已知导体（Cu、CuSn6、CuZn37、CuBe2）"}
    area_problem = _span(merged, "area_mm2_min", "area_mm2_max", float(area_mm2), "截面积 mm²")
    length_problem = _span(merged, "length_mm_min", "length_mm_max", float(length_mm), "导体长度 mm")
    if area_problem or length_problem:
        return {"ok": False, "reason": area_problem or length_problem}
    rho = float(merged["materials"][canon]["rho_ohm_m"])
    temp_coeff = float(merged["materials"][canon]["temp_coeff_per_c"])
    current = float(merged["current_a"])
    h = float(merged["convection_h_w_m2k"])
    max_rise = float(merged["max_rise_c"])
    raw = {
        "area_mm2": float(area_mm2),
        "length_mm": float(length_mm),
        "rho_ohm_m": rho,
        "temp_coeff_per_c": temp_coeff,
        "current_a": current,
        "h_w_m2k": h,
        "ambient_temp_c": float(merged["ambient_temp_c"]),
        "emissivity": float(merged["emissivity"]),
        "contact_resistance_ohm_mm2": float(merged["contact_resistance_ohm_mm2"]),
        "reference_temp_c": float(merged["reference_temp_c"]),
        "max_solver_rise_c": float(merged["max_solver_rise_c"]),
        "max_rise_c": max_rise,
        "max_temperature_c": float(merged["max_temperature_c"]),
    }
    pred = predict_raw(**raw)
    rise = pred["delta_t_c"]
    return {
        "ok": True,
        "reason": "",
        "material": canon,
        "delta_t_c": rise,
        "delta_t_low_c": pred["delta_t_low_c"],
        "delta_t_high_c": pred["delta_t_high_c"],
        "absolute_temperature_c": pred["absolute_temperature_c"],
        "total_resistance_ohm": pred["total_resistance_ohm"],
        "joule_power_w": pred["power_w"],
        "voltage_drop_v": pred["voltage_drop_v"],
        "allowable_current_a": _allowable_current(
            raw,
            min(max_rise, float(merged["max_temperature_c"]) - float(merged["ambient_temp_c"])),
            float(merged["current_a_min"]),
            float(merged["current_a_max"]),
        ),
        "alarm": pred["alarm"],
        "formula_id": pred["formula_id"],
        "decisions": pred["decisions"],
        "solver_iterations": pred["solver_iterations"],
        "solver_residual_w": pred["solver_residual_w"],
        "max_rise_c": max_rise,
        "current_a": current,
        "ambient_temp_c": float(merged["ambient_temp_c"]),
    }


def _allowable_current(raw: dict, max_rise: float, current_min: float, current_max: float) -> float:
    """在规则的电流范围内，找温升仍低于允许值的最大电流。"""
    lo = float(current_min)
    hi = float(current_max)
    probe = dict(raw)
    probe["current_a"] = lo
    if predict_raw(**probe)["delta_t_c"] >= max_rise:
        return lo
    probe["current_a"] = hi
    if predict_raw(**probe)["delta_t_c"] < max_rise:
        return hi
    for _ in range(24):
        mid = 0.5 * (lo + hi)
        probe["current_a"] = mid
        if predict_raw(**probe)["delta_t_c"] >= max_rise:
            hi = mid
        else:
            lo = mid
    return lo


def _search_area(raw: dict, max_rise: float, area_max: float) -> float | None:
    lo = float(raw["area_mm2"])
    hi = float(area_max)
    if hi <= lo:
        return None
    probe = dict(raw)
    probe["area_mm2"] = hi
    if predict_raw(**probe)["delta_t_c"] >= max_rise:
        return None
    for _ in range(24):
        mid = 0.5 * (lo + hi)
        probe["area_mm2"] = mid
        rise = predict_raw(**probe)["delta_t_c"]
        if rise >= max_rise:
            lo = mid
        else:
            hi = mid
    return hi


class CurrentTempChecker(BaseChecker):
    check_item_id = "PERF-01"
    name = "载流-温升预测"
    version = "2.0.0"
    owner = "性能预测 杜滨芳"
    process_types = ("performance",)
    default_params = dict(RULE_PARAMS)

    def applies(self, model: ModelBundle, params: dict) -> tuple[bool, str]:
        problem = condition_problem(params)
        if problem:
            return False, problem
        try:
            _solver_evidence(model, params)
        except SolverEvidenceError as exc:
            return False, str(exc)
        parts = conductor_parts(model, params)
        if not parts:
            return False, "模型中没有已知导体材料（Cu、CuSn6、CuZn37、CuBe2），缺少材料就不能预测温升"
        reasons = []
        for part in parts:
            spec, why = bottleneck(model, part, params)
            if spec is None:
                reasons.append(f"{part.part_id} {why}")
            else:
                return True, ""
        return False, "导体零件无法估计载流截面：" + "；".join(reasons)

    def check(self, ctx: CheckContext) -> list[Finding]:
        params = ctx.params
        materials = params.get("materials") or {}
        current = float(params["current_a"])
        ambient = float(params["ambient_temp_c"])
        h = float(params["convection_h_w_m2k"])
        max_rise = float(params["max_rise_c"])
        max_temperature = float(params["max_temperature_c"])
        confidence = float(params["interval_confidence"])
        formula = default_formula()
        solver = _solver_evidence(ctx.model, params)
        findings = []
        for part in conductor_parts(ctx.model, params):
            material = canonical_material(part.material, materials)
            spec, _why = bottleneck(ctx.model, part, params)
            if material is None or spec is None:
                continue
            rho = float(materials[material]["rho_ohm_m"])
            temp_coeff = float(materials[material]["temp_coeff_per_c"])
            raw = {
                "area_mm2": spec["area_mm2"],
                "length_mm": spec["length_mm"],
                "rho_ohm_m": rho,
                "temp_coeff_per_c": temp_coeff,
                "current_a": current,
                "h_w_m2k": h,
                "ambient_temp_c": ambient,
                "emissivity": float(params["emissivity"]),
                "contact_resistance_ohm_mm2": float(params["contact_resistance_ohm_mm2"]),
                "reference_temp_c": float(params["reference_temp_c"]),
                "max_solver_rise_c": float(params["max_solver_rise_c"]),
                "max_rise_c": max_rise,
                "max_temperature_c": max_temperature,
            }
            formula_pred = predict_raw(**raw)
            pred = dict(formula_pred)
            rule_result = None
            if solver is not None:
                solver_delta = solver.value("delta_t_c", "degC")
                solver_absolute = solver.value("maximum_temperature_c", "degC")
                inputs = _formula_inputs(
                    raw["area_mm2"], raw["length_mm"], raw["rho_ohm_m"],
                    raw["current_a"], raw["h_w_m2k"],
                    temp_coeff_per_c=raw["temp_coeff_per_c"],
                    ambient_temp_c=raw["ambient_temp_c"],
                    emissivity=raw["emissivity"],
                    contact_resistance_ohm_mm2=raw["contact_resistance_ohm_mm2"],
                    reference_temp_c=raw["reference_temp_c"],
                    max_solver_rise_c=raw["max_solver_rise_c"],
                    max_rise_c=raw["max_rise_c"],
                    max_temperature_c=raw["max_temperature_c"],
                )
                rule_result = formula.apply_solver_overrides(
                    inputs,
                    {
                        "temperature_c": solver_absolute,
                        "delta_t_c": solver_delta,
                        "absolute_temperature_c": solver_absolute,
                    },
                )
                pred.update({
                    "delta_t_c": solver_delta,
                    "absolute_temperature_c": solver_absolute,
                    "decisions": [item.to_dict() for item in rule_result.decisions],
                    "alarm": any(item.triggered for item in rule_result.decisions),
                })
            rise = pred["delta_t_c"]
            triggered = [d for d in pred["decisions"] if d["triggered"]]
            if not triggered:
                continue
            primary = next((d for d in triggered if d["condition"].startswith("delta_t_c")), triggered[0])
            measured = float(primary["measured"] if primary["measured"] is not None else rise)
            threshold = float(primary["threshold"] if primary["threshold"] is not None else max_rise)
            rise_budget = max(0.0, min(max_rise, max_temperature - ambient))
            target_area = _search_area(raw, rise_budget, float(params["area_mm2_max"]))
            # 只在「当前电流及以下」找不报警的最大电流，和推理接口里的允许电流同一套搜索。
            allow_current = _allowable_current(
                raw, rise_budget, float(params["current_a_min"]), min(float(params["current_a_max"]), current)
            )
            actions = []
            delta = {"current_a": round(allow_current, 3)}
            if target_area is not None:
                actions.append(f"把载流截面积加大到 {target_area:.2f} mm²")
                delta["area_mm2"] = round(target_area, 3)
            else:
                actions.append(
                    f"截面积加到上限 {float(params['area_mm2_max']):.1f} mm² 仍然超限"
                )
            actions.append(f"或把电流降到 {allow_current:.2f} A")
            low = pred["delta_t_low_c"]
            high = pred["delta_t_high_c"]
            findings.append(
                ctx.finding(
                    message=(
                        f"零件 {part.part_id}（{material}）在 {current:.1f} A、环境 {ambient:.0f} °C 下，"
                        f"{'NX 求解结果' if solver else '公式 ' + pred['formula_id']}求得稳态温升 {rise:.1f} °C（标定区间 "
                        f"{low:.1f}–{high:.1f} °C），绝对温度 {pred['absolute_temperature_c']:.1f} °C；"
                        f"判定式 {primary['condition']} 成立。"
                        + "，".join(actions)
                        + "。"
                    ),
                    part_refs=[part.part_id],
                    location=spec["cog"],
                    bbox=part.bbox,
                    severity=primary["severity"] or ctx.rule.severity,
                    measured_value=measured,
                    threshold_value=threshold,
                    unit="°C",
                    confidence=confidence,
                    suggestion_text="，".join(actions) + "。",
                    suggestion_delta=delta,
                    face_ids=[spec["face_id"]],
                    note=(
                        "采用稳态电热公式；判定来自 formula_ref=PERF-01 的比较式。"
                        "区间只用于不确定性展示。"
                    ),
                    extra={
                        "delta_t_c": rise,
                        "delta_t_low_c": low,
                        "delta_t_high_c": high,
                        "interval_confidence": confidence,
                        "allowable_current_a": allow_current,
                        "current_a": current,
                        "ambient_temp_c": ambient,
                        "area_mm2": spec["area_mm2"],
                        "length_mm": spec["length_mm"],
                        "material": material,
                        "absolute_temp_c": ambient + rise,
                        "absolute_temperature_c": pred["absolute_temperature_c"],
                        "max_temperature_c": max_temperature,
                        "total_resistance_ohm": pred["total_resistance_ohm"],
                        "joule_power_w": pred["power_w"],
                        "voltage_drop_v": pred["voltage_drop_v"],
                        "formula_id": pred["formula_id"],
                        "formula_values": pred["formula_values"],
                        "decision": primary,
                        "decisions": pred["decisions"],
                        "calculation_method": "cae_solver" if solver else "formula",
                        "solver_evidence": solver.as_dict() if solver else None,
                        "formula_crosscheck_values": formula_pred["formula_values"],
                        "formula_solver_delta_difference_c": (
                            rise - formula_pred["delta_t_c"] if solver else None
                        ),
                        "rule_reference": ctx.rule.reference,
                        "solver_iterations": pred["solver_iterations"],
                        "solver_residual_w": pred["solver_residual_w"],
                    },
                )
            )
        return findings


CHECKERS = [CurrentTempChecker()]
