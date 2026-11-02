# -*- coding: utf-8 -*-
"""PERF-02 插拔力。

簧片尺寸和接触参数优先从 ``model.meta.performance.PERF-02`` 读取。没有明确
接触特征时跳过，不用包围盒冒充簧片几何。力和 PASS/FAIL 都来自公式库。
"""

from __future__ import annotations

import math

from ...checkers.base import BaseChecker, CheckContext
from ...contracts import Finding, ModelBundle, Part
from .force_model import MODEL_PATH as FORCE_MODEL_PATH
from .force_model import load as load_force_model
from .force_physics import RULE_PARAMS, canonical_material
from .rule_engine import FormulaProgram, FormulaResult, load_formula
from .solver_evidence import SolverEvidence, SolverEvidenceError, load_solver_evidence
from .tree_model import apply_interval

_MODEL = None


def model_path() -> str:
    return FORCE_MODEL_PATH


def load_model():
    global _MODEL
    if _MODEL is None:
        _MODEL = load_force_model(FORCE_MODEL_PATH)
    return _MODEL


def default_formula() -> FormulaProgram:
    return load_formula("PERF-02")


def _solver_evidence(model: ModelBundle, params: dict) -> SolverEvidence | None:
    path = str(params.get("solver_result_path") or "").strip()
    if not path:
        return None
    evidence = load_solver_evidence(
        path,
        expected_item="PERF-02",
        expected_model_id=model.model_id,
        expected_digest=model.content_digest(),
        require_authorized=True,
    )
    evidence.value("insertion_force_n", "N")
    evidence.value("withdrawal_force_n", "N")
    return evidence


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
        return f"PERF-02 公式无法读取：{exc}"
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
    for key in ("contacts", "lead_angle_deg", "friction_coeff", "overlap_mm"):
        if key not in params:
            return f"规则缺少 {key}"
    return _span(params, "friction_min", "friction_max", float(params["friction_coeff"]), "摩擦系数") or _span(
        params, "overlap_mm_min", "overlap_mm_max", float(params["overlap_mm"]), "过盈量 mm"
    )


def _metadata_spring(model: ModelBundle, part_id: str) -> dict | None:
    perf = model.meta.get("performance") or {}
    perf02 = perf.get("PERF-02") or {}
    items = perf02.get("contact_springs") or model.meta.get("contact_springs") or []
    for item in items:
        if isinstance(item, dict) and item.get("part_id") == part_id:
            return dict(item)
    return None


def spring_spec(model: ModelBundle, part: Part, params: dict) -> tuple[dict | None, str]:
    """读取显式接触簧片几何；旧规则可显式选择包围盒兼容模式。"""
    item = _metadata_spring(model, part.part_id)
    source = "contact_metadata"
    if item is None:
        if str(params.get("geometry_source") or "contact_metadata") != "part_bbox":
            return None, "缺少 PERF-02 contact_springs 元数据，不能从包围盒猜测接触几何"
        bbox = part.bbox
        if bbox is None:
            return None, "零件没有包围盒，无法估计簧片尺寸"
        dims = sorted([bbox.xmax - bbox.xmin, bbox.ymax - bbox.ymin, bbox.zmax - bbox.zmin])
        if dims[0] <= 0 or dims[2] <= 0:
            return None, "零件包围盒退化，无法估计簧片尺寸"
        thickness, width, length = dims[0], dims[1], dims[2]
        item = {
            "part_id": part.part_id,
            "thickness_mm": thickness,
            "width_mm": width,
            "length_mm": length,
        }
        source = "part_bbox_legacy"
    try:
        thickness = float(item["thickness_mm"])
        width = float(item["width_mm"])
        length = float(item["length_mm"])
        overlap = float(item.get("overlap_mm", params["overlap_mm"]))
        contacts = float(item.get("contacts", params["contacts"]))
        lead_angle = float(item.get("lead_angle_deg", params["lead_angle_deg"]))
        friction = float(item.get("friction_coeff", params["friction_coeff"]))
    except (KeyError, TypeError, ValueError) as exc:
        return None, f"contact_springs 元数据不完整：{exc}"
    problem = (
        _span(params, "thickness_mm_min", "thickness_mm_max", thickness, "簧片厚度 mm")
        or _span(params, "width_mm_min", "width_mm_max", width, "簧片宽度 mm")
        or _span(params, "length_mm_min", "length_mm_max", length, "簧片长度 mm")
        or _span(params, "overlap_mm_min", "overlap_mm_max", overlap, "过盈量 mm")
        or _span(params, "friction_min", "friction_max", friction, "摩擦系数")
    )
    if problem:
        return None, problem
    if contacts <= 0:
        return None, "接触点数必须为正"
    if 1.0 - friction * math.tan(math.radians(lead_angle)) <= 1e-6:
        return None, "1 - μ·tanθ ≤ 0，接触力公式无有限解"
    return {
        "part_id": part.part_id,
        "thickness_mm": thickness,
        "width_mm": width,
        "length_mm": length,
        "overlap_mm": overlap,
        "contacts": contacts,
        "lead_angle_deg": lead_angle,
        "friction_coeff": friction,
        "face_ids": list(item.get("face_ids") or []),
        "bbox": part.bbox,
        "geometry_source": source,
    }, ""


def conductor_parts(model: ModelBundle, params: dict) -> list[Part]:
    materials = params.get("materials") or {}
    return [p for p in model.parts if canonical_material(p.material, materials)]


def _anchor_face(model: ModelBundle, part: Part) -> str | None:
    """给 Finding 一个可点回 3D 的定位面。尺寸仍来自包围盒。"""
    planes = model.faces_of(part.part_id, "planar")
    if not planes:
        return None
    best = max(planes, key=lambda f: f.area or 0.0)
    return best.face_id


def predict_insertion(
    length_mm: float,
    width_mm: float,
    thickness_mm: float,
    material: str,
    params: dict | None = None,
) -> dict:
    """给簧片尺寸和材料，返回插拔力区间。不经过 3D 模型。"""
    merged = dict(RULE_PARAMS)
    if params:
        merged.update(params)
    problem = condition_problem(merged)
    if problem:
        return {"ok": False, "reason": problem}
    canon = canonical_material(material, merged.get("materials") or {})
    if canon is None:
        return {"ok": False, "reason": f"材料 {material} 不是已知簧片材料（CuSn6、CuBe2、CuZn37）"}
    problem = (
        _span(merged, "length_mm_min", "length_mm_max", float(length_mm), "簧片长度 mm")
        or _span(merged, "width_mm_min", "width_mm_max", float(width_mm), "簧片宽度 mm")
        or _span(merged, "thickness_mm_min", "thickness_mm_max", float(thickness_mm), "簧片厚度 mm")
    )
    if problem:
        return {"ok": False, "reason": problem}

    e_gpa = float(merged["materials"][canon]["e_gpa"])
    overlap = float(merged["overlap_mm"])
    friction = float(merged["friction_coeff"])
    spec = {
        "length_mm": float(length_mm),
        "width_mm": float(width_mm),
        "thickness_mm": float(thickness_mm),
        "overlap_mm": overlap,
        "contacts": float(merged["contacts"]),
        "lead_angle_deg": float(merged["lead_angle_deg"]),
        "friction_coeff": friction,
    }
    result = evaluate_contact(spec, e_gpa, merged)
    insertion = float(result.values["insertion_force_n"])
    withdrawal = float(result.values["withdrawal_force_n"])
    try:
        model = load_model()
        low, high = apply_interval(insertion, model["q_low"], model["q_high"])
    except (OSError, ValueError, KeyError):
        low, high = insertion, insertion
    max_n = float(merged["insertion_force_max_n"])
    min_n = float(merged["withdrawal_force_min_n"])
    decisions = [item.to_dict() for item in result.decisions]
    return {
        "ok": True,
        "reason": "",
        "material": canon,
        "insertion_force_n": insertion,
        "insertion_force_low_n": low,
        "insertion_force_high_n": high,
        "withdrawal_force_n": withdrawal,
        "interval_confidence": float(merged["interval_confidence"]),
        "insertion_force_max_n": max_n,
        "withdrawal_force_min_n": min_n,
        "alarm": any(item["triggered"] for item in decisions),
        "formula_id": result.formula_id,
        "formula_values": result.values,
        "decisions": decisions,
        "length_mm": float(length_mm),
        "width_mm": float(width_mm),
        "thickness_mm": float(thickness_mm),
        "overlap_mm": overlap,
        "contacts": float(merged["contacts"]),
    }


def _contact_inputs(spec: dict, e_gpa: float, params: dict) -> dict:
    return {
        "length_mm": float(spec["length_mm"]),
        "width_mm": float(spec["width_mm"]),
        "thickness_mm": float(spec["thickness_mm"]),
        "overlap_mm": float(spec["overlap_mm"]),
        "e_gpa": float(e_gpa),
        "contacts": float(spec["contacts"]),
        "lead_angle_deg": float(spec["lead_angle_deg"]),
        "friction_coeff": float(spec["friction_coeff"]),
        "insertion_force_max_n": float(params["insertion_force_max_n"]),
        "withdrawal_force_min_n": float(params["withdrawal_force_min_n"]),
    }


def evaluate_contact(
    spec: dict,
    e_gpa: float,
    params: dict,
    *,
    formula: FormulaProgram | None = None,
    **overrides,
) -> FormulaResult:
    program = formula or default_formula()
    inputs = _contact_inputs(spec, e_gpa, params)
    inputs.update({key: float(value) for key, value in overrides.items() if value is not None})
    return program.evaluate(inputs)


def _limit_overlap(
    formula: FormulaProgram,
    spec: dict,
    e_gpa: float,
    params: dict,
    max_n: float,
    lo: float,
    hi: float,
) -> float | None:
    """把过盈量从当前值往小调，找仍然不超限的最大过盈量。"""
    if evaluate_contact(spec, e_gpa, params, formula=formula, overlap_mm=hi).values["insertion_force_n"] < max_n:
        return hi
    if evaluate_contact(spec, e_gpa, params, formula=formula, overlap_mm=lo).values["insertion_force_n"] >= max_n:
        return None
    a, b = lo, hi
    for _ in range(24):
        mid = 0.5 * (a + b)
        if evaluate_contact(spec, e_gpa, params, formula=formula, overlap_mm=mid).values["insertion_force_n"] >= max_n:
            b = mid
        else:
            a = mid
    return a


def _needed_length(
    formula: FormulaProgram,
    spec: dict,
    e_gpa: float,
    params: dict,
    max_n: float,
    start: float,
    hi: float,
) -> float | None:
    """簧片加长会变软。找能把插入力压到上限以下的最短长度。"""
    if evaluate_contact(spec, e_gpa, params, formula=formula, length_mm=hi).values["insertion_force_n"] >= max_n:
        return None
    a, b = start, hi
    for _ in range(24):
        mid = 0.5 * (a + b)
        if evaluate_contact(spec, e_gpa, params, formula=formula, length_mm=mid).values["insertion_force_n"] >= max_n:
            a = mid
        else:
            b = mid
    return b


class InsertionForceChecker(BaseChecker):
    check_item_id = "PERF-02"
    name = "插拔力预测"
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
            return False, "模型中没有已知簧片材料（CuSn6、CuBe2、CuZn37），缺少材料就不能预测插拔力"
        reasons = []
        for part in parts:
            spec, why = spring_spec(model, part, params)
            if spec is not None:
                return True, ""
            reasons.append(f"{part.part_id} {why}")
        return False, "导体零件无法当作簧片：" + "；".join(reasons)

    def check(self, ctx: CheckContext) -> list[Finding]:
        params = ctx.params
        materials = params.get("materials") or {}
        max_n = float(params["insertion_force_max_n"])
        min_n = float(params["withdrawal_force_min_n"])
        confidence = float(params["interval_confidence"])
        formula = default_formula()
        solver = _solver_evidence(ctx.model, params)
        findings = []
        for part in conductor_parts(ctx.model, params):
            material = canonical_material(part.material, materials)
            spec, _why = spring_spec(ctx.model, part, params)
            if material is None or spec is None:
                continue
            e_gpa = float(materials[material]["e_gpa"])
            result = evaluate_contact(spec, e_gpa, params, formula=formula)
            formula_result = result
            if solver is not None:
                insertion = solver.value("insertion_force_n", "N")
                withdrawal = solver.value("withdrawal_force_n", "N")
                result = formula.apply_solver_overrides(
                    _contact_inputs(spec, e_gpa, params),
                    {
                        "insertion_force_n": insertion,
                        "withdrawal_force_n": withdrawal,
                    },
                )
            else:
                insertion = float(result.values["insertion_force_n"])
                withdrawal = float(result.values["withdrawal_force_n"])
            try:
                interval_model = load_model()
                low, high = apply_interval(insertion, interval_model["q_low"], interval_model["q_high"])
            except (OSError, ValueError, KeyError):
                interval_model = {}
                low, high = insertion, insertion
            decision_map = {d["condition"]: d for d in (item.to_dict() for item in result.decisions)}
            insertion_decision = next(
                (item for item in decision_map.values() if item["condition"].startswith("insertion_force_n")),
                None,
            )
            withdrawal_decision = next(
                (item for item in decision_map.values() if item["condition"].startswith("withdrawal_force_n")),
                None,
            )
            anchor = spec.get("face_ids") or ([_anchor_face(ctx.model, part)] if _anchor_face(ctx.model, part) else [])
            geometry_label = (
                "明确接触簧片元数据"
                if spec["geometry_source"] == "contact_metadata"
                else "兼容模式：零件包围盒估计"
            )
            common = {
                "part_id": part.part_id,
                "material": material,
                "length_mm": round(spec["length_mm"], 4),
                "width_mm": round(spec["width_mm"], 4),
                "thickness_mm": round(spec["thickness_mm"], 4),
                "overlap_mm": spec["overlap_mm"],
                "friction_coeff": spec["friction_coeff"],
                "contacts": spec["contacts"],
                "insertion_force_n": round(insertion, 4),
                "insertion_force_low_n": round(low, 4),
                "insertion_force_high_n": round(high, 4),
                "withdrawal_force_n": round(withdrawal, 4),
                "interval_confidence": confidence,
                "geometry_source": spec["geometry_source"],
                "lead_angle_deg": spec["lead_angle_deg"],
                "formula_id": result.formula_id,
                "formula_values": result.values,
                "decisions": list(decision_map.values()),
                "calculation_method": "formula",
                "rule_reference": ctx.rule.reference,
                "solver_evidence": solver.as_dict() if solver else None,
                "formula_crosscheck_values": formula_result.values,
                "formula_solver_insertion_difference_n": (
                    insertion - float(formula_result.values["insertion_force_n"]) if solver else None
                ),
            }
            common["calculation_method"] = "cae_solver" if solver else "formula"
            if insertion_decision and insertion_decision["triggered"]:
                actions = []
                delta = {}
                overlap_fix = _limit_overlap(
                    formula, spec, e_gpa, params, max_n,
                    float(params["overlap_mm_min"]), spec["overlap_mm"],
                )
                if overlap_fix is not None:
                    actions.append(f"把过盈量从 {spec['overlap_mm']:.2f} mm 减到 {overlap_fix:.3f} mm")
                    delta["overlap_mm"] = round(overlap_fix, 4)
                length_fix = _needed_length(
                    formula, spec, e_gpa, params, max_n,
                    spec["length_mm"], float(params["length_mm_max"]),
                )
                if length_fix is not None:
                    actions.append(f"把簧片长度加到 {length_fix:.2f} mm（加长会变软）")
                    delta["length_mm"] = round(length_fix, 4)
                if not actions:
                    actions.append("当前尺寸范围内减不下来，需要换簧片截面或减少接触点数")
                findings.append(
                    ctx.finding(
                        severity=insertion_decision["severity"] or "P2",
                        message=(
                            f"零件 {part.part_id}（{material}）按{geometry_label} "
                            f"{spec['length_mm']:.1f}×{spec['width_mm']:.1f}×{spec['thickness_mm']:.2f} mm、"
                            f"过盈量 {spec['overlap_mm']:.2f} mm、{spec['contacts']:.0f} 个接触点，"
                            f"{'NX 求解结果' if solver else '公式 ' + result.formula_id}得到插入力 {insertion:.2f} N"
                            f"（标定区间 {low:.2f}–{high:.2f} N）；"
                            f"判定式 {insertion_decision['condition']} 成立。" + "，".join(actions) + "。"
                        ),
                        part_refs=[part.part_id],
                        location=None,
                        bbox=part.bbox,
                        measured_value=insertion,
                        threshold_value=max_n,
                        unit="N",
                        confidence=confidence,
                        suggestion_text="，".join(actions) + "。",
                        suggestion_delta=delta,
                        face_ids=anchor,
                        note="插拔力由 formula_ref=PERF-02 的降阶接触公式计算；区间不参与判定",
                        extra={**common, "decision": insertion_decision},
                    )
                )
            elif withdrawal_decision and withdrawal_decision["triggered"]:
                findings.append(
                    ctx.finding(
                        severity=withdrawal_decision["severity"] or "P3",
                        message=(
                            f"零件 {part.part_id}（{material}）预测拔出力 {withdrawal:.2f} N，"
                            f"公式判定式 {withdrawal_decision['condition']} 成立，"
                            f"接触压力可能不足。"
                            f"可在规则范围内加大过盈量（当前 {spec['overlap_mm']:.2f} mm）或更换弹性模量更高的材料。"
                        ),
                        part_refs=[part.part_id],
                        bbox=part.bbox,
                        measured_value=withdrawal,
                        threshold_value=min_n,
                        unit="N",
                        confidence=confidence,
                        suggestion_text="加大过盈量或换更高弹性模量的簧片材料。",
                        suggestion_delta={"overlap_mm_min": float(params["overlap_mm_min"])},
                        face_ids=anchor,
                        note="插拔力由 formula_ref=PERF-02 的降阶接触公式计算；区间不参与判定",
                        extra={**common, "decision": withdrawal_decision},
                    )
                )
        return findings


CHECKERS = [InsertionForceChecker()]
