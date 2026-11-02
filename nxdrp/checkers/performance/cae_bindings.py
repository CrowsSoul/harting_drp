# -*- coding: utf-8 -*-
"""PERF CAE 工况绑定：几何提议、人工确认、摘要和严格设置校验。

几何 journal 只能提出真实 NX 拓扑标签；只有明确的人工确认才能把角色、接触和
结果查询用于求解设置。模块不会从包围盒或名称猜测边界面。
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os

from .rule_engine import PROJECT_ROOT


BINDINGS_TEMPLATE_PATH = os.path.join(PROJECT_ROOT, "rules", "perf_cae_bindings_v1.json")
MATERIAL_LIBRARY_PATH = os.path.join(PROJECT_ROOT, "rules", "perf_material_library_v1.json")


def _load(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_binding_templates(path: str = BINDINGS_TEMPLATE_PATH) -> dict:
    payload = _load(path)
    if payload.get("schema_version") != "1.0.0":
        raise ValueError("PERF CAE bindings schema_version 必须为 1.0.0")
    return payload


def load_material_library(path: str = MATERIAL_LIBRARY_PATH) -> dict:
    payload = _load(path)
    if payload.get("schema_version") != "1.0.0":
        raise ValueError("PERF material library schema_version 必须为 1.0.0")
    return payload


def material_for(case: dict, library: dict | None = None) -> dict:
    payload = library or load_material_library()
    name = str(case.get("material") or "")
    materials = payload.get("materials") or {}
    if name not in materials:
        raise ValueError(f"材料库中不存在 {name!r}")
    return {"material": name, **materials[name]}


def _finite_number(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def create_binding_draft(case: dict) -> dict:
    templates = load_binding_templates()["items"]
    item_id = case["check_item_id"]
    if item_id not in templates:
        raise ValueError(f"没有 {item_id} 的 CAE 绑定模板")
    template = templates[item_id]
    units = template.get("required_result_units") or {}
    face_roles = {
        role: {"face_ids": [], "body_ids": [], "status": "pending"}
        for role in template["required_face_roles"]
    }
    result_queries = {
        name: {
            "query": name,
            "selection": "whole_model",
            "unit": units.get(name, "status" if name == "convergence_status" else "1"),
            "status": "pending",
        }
        for name in template["required_result_queries"]
    }
    formula_inputs = dict(case.get("formula_inputs") or {})
    geometry = dict(case.get("geometry_request") or {})
    conditions = dict(case.get("contact_conditions") or {})
    if item_id == "PERF-01":
        load_values = {
            "current_a": formula_inputs.get("current_a"),
            "outlet_voltage_v": 0.0,
            "ambient_temperature_c": formula_inputs.get("ambient_temp_c"),
            "convection_h_w_m2k": formula_inputs.get("h_w_m2k"),
            "radiation_emissivity": formula_inputs.get("emissivity"),
        }
        solver = {
            "product": "NX THERMAL",
            "analysis_type": "thermal_with_joule",
            "solution_type": "Steady State Solid Thermal",
            "analysis_mode": "steady",
            "physics_domain": "solid",
            "joule_heating": True,
        }
    else:
        normal_overlap = float(
            geometry.get("normal_overlap_mm", formula_inputs.get("overlap_mm", 0.0))
        )
        stroke = float(
            geometry.get(
                "insertion_stroke_mm",
                conditions.get("insertion_stroke_mm", 0.5 * float(geometry.get("length_mm", 0.0))),
            )
        )
        load_values = {
            "normal_overlap_mm": normal_overlap,
            "insertion_stroke_mm": stroke,
        }
        solver = {
            "product": "NX NASTRAN",
            "analysis_type": "Structural",
            "solution_type": "SOL 401 Multi-Step Nonlinear",
            "solution_card": "SOL 401",
            "large_displacement": True,
        }
    contacts = []
    if item_id == "PERF-02":
        contacts.append({
            "source_face_ids": [],
            "target_face_ids": [],
            "method": "penalty",
            "friction_model": "coulomb",
            "friction_coefficient": formula_inputs.get("friction_coeff"),
            "penalty_stiffness": conditions.get("penalty_stiffness_n_mm3"),
            "search_distance_mm": conditions.get("search_distance_mm"),
            "normal_overlap_mm": load_values["normal_overlap_mm"],
            "insertion_stroke_mm": load_values["insertion_stroke_mm"],
            "large_displacement": True,
            "status": "pending",
        })
    binding = {
        "schema_version": "1.0.0",
        "case_id": case["case_id"],
        "check_item_id": item_id,
        "material": material_for(case),
        "source_geometry": {
            "source_part": "",
            "model_id": case["case_id"],
            "model_digest": "",
            "body_tags": [],
            "status": "pending",
        },
        "face_roles": face_roles,
        "load_values": load_values,
        "contact_pairs": contacts,
        "result_queries": result_queries,
        "solver": solver,
        "status": "pending",
    }
    binding["binding_digest"] = binding_digest(binding)
    return binding


def binding_digest(binding: dict) -> str:
    payload = dict(binding)
    payload.pop("binding_digest", None)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _same_path(left: str, right: str) -> bool:
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


def _geometry_response_parts(response: dict) -> tuple[str, str, list[int]]:
    if response.get("ok") is not True:
        raise ValueError("几何响应尚未成功完成")
    digest = str(response.get("part_digest") or response.get("model_digest") or "")
    part_path = str(response.get("part_path") or response.get("source_part") or "")
    if not digest or not part_path:
        raise ValueError("几何响应缺少 part_path/part_digest")
    raw_tags = response.get("body_tags")
    if raw_tags is None:
        raw_tags = [item.get("tag") for item in response.get("bodies") or []]
    if not isinstance(raw_tags, list) or not raw_tags:
        raise ValueError("几何响应缺少 body_tags")
    tags = []
    for value in raw_tags:
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError("几何响应包含无效 body tag")
        tags.append(value)
    if len(set(tags)) != len(tags):
        raise ValueError("几何响应 body_tags 不唯一")
    return part_path, digest, tags


def apply_geometry_response(binding: dict, response: dict) -> dict:
    """应用 NX 几何响应；所有拓扑角色只标为 ``proposed``，不代替人工确认。"""
    if str(response.get("case_id") or "") != str(binding.get("case_id") or ""):
        raise ValueError("几何响应 case_id 与绑定不一致")
    expected_digest = binding.get("binding_digest")
    if not expected_digest or expected_digest != binding_digest(binding):
        raise ValueError("binding_digest 不一致；请先恢复或重新生成绑定")
    part_path, part_digest, body_tags = _geometry_response_parts(response)
    geometry = binding.get("source_geometry") or {}
    source_part = str(geometry.get("source_part") or "")
    if not source_part or not _same_path(source_part, part_path):
        raise ValueError("几何响应 source part 与绑定不一致")

    template = load_binding_templates()["items"][binding["check_item_id"]]
    response_roles = response.get("face_roles") or {}
    proposed_roles = {}
    for role in template["required_face_roles"]:
        value = response_roles.get(role) or {}
        face_ids = [str(item) for item in value.get("face_ids") or [] if str(item)]
        body_ids = [str(item) for item in value.get("body_ids") or [] if str(item)]
        if not face_ids or not body_ids:
            raise ValueError(f"几何响应缺少完整面角色 {role}")
        proposed_roles[role] = {
            "face_ids": face_ids,
            "body_ids": body_ids,
            "faces": copy.deepcopy(value.get("faces") or []),
            "status": "proposed",
        }

    binding["source_geometry"] = {
        **geometry,
        "source_part": os.path.abspath(part_path),
        "model_id": str(response.get("model_id") or geometry.get("model_id") or binding["case_id"]),
        "model_digest": part_digest,
        "body_tags": body_tags,
        "body_roles": copy.deepcopy(response.get("body_roles") or {}),
        "status": "proposed",
    }
    binding["face_roles"] = proposed_roles
    if binding.get("confirmation"):
        binding.pop("confirmation")
    for pair in binding.get("contact_pairs") or []:
        pair["source_face_ids"] = list(proposed_roles["contact_source"]["face_ids"])
        pair["target_face_ids"] = list(proposed_roles["contact_target"]["face_ids"])
        pair["status"] = "proposed"
    for query in (binding.get("result_queries") or {}).values():
        query["status"] = "pending"
    binding["status"] = "proposed"
    binding["binding_digest"] = binding_digest(binding)
    return binding


def confirm_bindings(
    binding: dict,
    reviewer: str,
    geometry_response: dict,
    confirmed_at: str | None = None,
) -> dict:
    """确认完整几何、接触和结果查询；任一项不完整则保持原绑定并抛错。"""
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("绑定确认必须提供 reviewer")
    if confirmed_at is not None and (not isinstance(confirmed_at, str) or not confirmed_at.strip()):
        raise ValueError("confirmed_at 必须是非空 ISO 时间字符串")
    original = copy.deepcopy(binding)
    try:
        apply_geometry_response(binding, geometry_response)
        part_digest = str(geometry_response.get("part_digest") or geometry_response.get("model_digest") or "")
        if not part_digest or binding["source_geometry"]["model_digest"] != part_digest:
            raise ValueError("几何响应 digest 与绑定不一致")
        binding["source_geometry"]["status"] = "confirmed"
        for role in binding["face_roles"].values():
            role["status"] = "confirmed"
        for pair in binding.get("contact_pairs") or []:
            pair["status"] = "confirmed"
        for query in binding["result_queries"].values():
            query["status"] = "confirmed"
        binding["confirmation"] = {
            "reviewer": reviewer.strip(),
            "confirmed_at": confirmed_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "geometry_digest": part_digest,
        }
        binding["status"] = "confirmed"
        binding["binding_digest"] = binding_digest(binding)
        validation = validate_bindings(binding, strict=True)
        if not validation["valid"]:
            raise ValueError("绑定不完整：" + "；".join(validation["errors"]))
        return binding
    except Exception:
        binding.clear()
        binding.update(original)
        raise


def validate_bindings(
    binding: dict,
    *,
    material_library: dict | None = None,
    templates: dict | None = None,
    strict: bool = True,
) -> dict:
    """校验求解设置；``strict=True`` 要求人工确认、有效摘要和完整单位。"""
    errors: list[str] = []
    warnings: list[str] = []
    item_id = str(binding.get("check_item_id") or "")
    template_payload = templates or load_binding_templates()
    template = template_payload.get("items", {}).get(item_id)
    if template is None:
        return {"valid": False, "errors": [f"未知 PERF 项 {item_id!r}"], "warnings": []}

    material = binding.get("material") or {}
    material_name = str(material.get("material") or "")
    library = material_library or load_material_library()
    library_material = (library.get("materials") or {}).get(material_name)
    if library_material is None:
        errors.append(f"材料 {material_name!r} 不在 {library.get('library_id', '')}")
    else:
        for field in template["required_material_fields"]:
            # Engineer-reviewed bindings may override the library, so validate the
            # values that will actually reach the solver, not only the library row.
            value = material.get(field, library_material.get(field))
            if not _finite_number(value) or float(value) <= 0:
                errors.append(f"材料 {material_name} 缺少有效字段 {field}")
        if library.get("status") != "released":
            warnings.append("材料库仍为 provisional，正式认证前必须用供应商 TDS 替换")

    geometry = binding.get("source_geometry") or {}
    if not geometry.get("source_part"):
        errors.append("缺少 source_geometry.source_part")
    if not geometry.get("model_id"):
        errors.append("缺少 source_geometry.model_id")
    if not geometry.get("body_tags"):
        errors.append("缺少 source_geometry.body_tags")
    if not geometry.get("model_digest"):
        errors.append("缺少 source_geometry.model_digest")
    if strict and geometry.get("status") != "confirmed":
        errors.append("source_geometry 尚未确认")

    for role in template["required_face_roles"]:
        item = (binding.get("face_roles") or {}).get(role) or {}
        if not item.get("face_ids") or not item.get("body_ids"):
            errors.append(f"面角色 {role} 尚未绑定完整 face_ids/body_ids")
        elif item.get("status") != "confirmed":
            errors.append(f"面角色 {role} 尚未确认")

    for name in template["required_loads"]:
        value = (binding.get("load_values") or {}).get(name)
        if not _finite_number(value):
            errors.append(f"载荷/边界值 {name} 缺失或不是有限数值")
    if item_id == "PERF-02":
        for name in ("normal_overlap_mm", "insertion_stroke_mm"):
            value = (binding.get("load_values") or {}).get(name)
            if _finite_number(value) and float(value) <= 0:
                errors.append(f"{name} 必须大于 0")
        pairs = binding.get("contact_pairs") or []
        if len(pairs) != 1:
            errors.append("PERF-02 必须且只能建模一个 contact_pairs")
        for index, pair in enumerate(pairs, 1):
            for key in template["required_contact_parameters"]:
                value = pair.get(key)
                if value is None or value == "" or value == []:
                    errors.append(f"接触对 {index} 缺少 {key}")
            for key in ("friction_coefficient", "penalty_stiffness", "search_distance_mm", "normal_overlap_mm", "insertion_stroke_mm"):
                if key in pair and not _finite_number(pair[key]):
                    errors.append(f"接触对 {index} 的 {key} 不是有限数值")
            for key in ("penalty_stiffness", "search_distance_mm", "normal_overlap_mm", "insertion_stroke_mm"):
                if _finite_number(pair.get(key)) and float(pair[key]) <= 0:
                    errors.append(f"接触对 {index} 的 {key} 必须大于 0")
            if pair.get("method") != "penalty" or pair.get("friction_model") != "coulomb":
                errors.append(f"接触对 {index} 必须为 penalty/Coulomb")
            if pair.get("status") != "confirmed":
                errors.append(f"接触对 {index} 尚未确认")

    required_units = template.get("required_result_units") or {}
    queries = binding.get("result_queries") or {}
    if set(queries) != set(template["required_result_queries"]):
        errors.append("结果查询必须精确覆盖模板要求的输出，不能缺少或额外添加")
    for name in template["required_result_queries"]:
        query = (binding.get("result_queries") or {}).get(name)
        if not query or not query.get("query") or not query.get("selection"):
            errors.append(f"结果查询 {name} 未完整定义")
            continue
        if query.get("status") != "confirmed":
            errors.append(f"结果查询 {name} 尚未确认")
        if name in required_units and query.get("unit") != required_units[name]:
            errors.append(f"结果查询 {name} 单位必须为 {required_units[name]}")

    solver = binding.get("solver") or {}
    if item_id == "PERF-01":
        if (
            solver.get("analysis_type") != "thermal_with_joule"
            or solver.get("analysis_mode") != "steady"
            or solver.get("physics_domain") != "solid"
            or solver.get("joule_heating") is not True
        ):
            errors.append("PERF-01 必须为 steady solid thermal_with_joule")
    elif (
        solver.get("solution_card") != "SOL 401"
        or solver.get("solution_type") != "SOL 401 Multi-Step Nonlinear"
        or solver.get("large_displacement") is not True
    ):
        errors.append("PERF-02 必须为 SOL 401 Multi-Step Nonlinear 且启用大位移")

    confirmation = binding.get("confirmation") or {}
    if strict:
        if binding.get("status") != "confirmed":
            errors.append("绑定状态尚未确认")
        if not str(confirmation.get("reviewer") or "").strip() or not confirmation.get("confirmed_at"):
            errors.append("缺少 reviewer/confirmed_at 确认记录")
        if confirmation.get("geometry_digest") != geometry.get("model_digest"):
            errors.append("确认记录与当前几何 digest 不一致")
    expected_digest = binding.get("binding_digest")
    if not expected_digest:
        if strict:
            errors.append("缺少 binding_digest")
    elif expected_digest != binding_digest(binding):
        errors.append("binding_digest 与绑定内容不一致；文件已被修改")
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "binding_digest": binding_digest(binding),
    }


def write_binding_draft(case: dict, path: str) -> str:
    payload = create_binding_draft(case)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return path
