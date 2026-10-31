# -*- coding: utf-8 -*-
"""PERF CAE 工况绑定：面角色、材料、载荷、接触和结果查询。

这些绑定必须由真实 CAD/网格拓扑和工程材料数据填充。模块只做格式校验与
可追溯摘要，不从包围盒或名称猜测边界面。
"""

from __future__ import annotations

import hashlib
import json
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


def create_binding_draft(case: dict) -> dict:
    templates = load_binding_templates()["items"]
    item_id = case["check_item_id"]
    if item_id not in templates:
        raise ValueError(f"没有 {item_id} 的 CAE 绑定模板")
    template = templates[item_id]
    face_roles = {
        role: {"face_ids": [], "body_ids": [], "status": "pending"}
        for role in template["required_face_roles"]
    }
    result_queries = {
        name: {"query": name, "selection": "whole_model", "status": "pending"}
        for name in template["required_result_queries"]
    }
    formula_inputs = dict(case.get("formula_inputs") or {})
    load_values = {}
    if item_id == "PERF-01":
        load_values = {
            "current_a": formula_inputs.get("current_a"),
            "ambient_temperature_c": formula_inputs.get("ambient_temp_c"),
            "convection_h_w_m2k": formula_inputs.get("h_w_m2k"),
            "radiation_emissivity": formula_inputs.get("emissivity"),
        }
    else:
        load_values = {
            "insertion_displacement_mm": formula_inputs.get("overlap_mm"),
        }
    contacts = []
    if item_id == "PERF-02":
        contacts.append({
            "source_face_ids": [],
            "target_face_ids": [],
            "method": "penalty",
            "friction_coefficient": formula_inputs.get("friction_coeff"),
            "penalty_stiffness": None,
            "search_distance_mm": None,
            "status": "pending",
        })
    binding = {
        "schema_version": "1.0.0",
        "case_id": case["case_id"],
        "check_item_id": item_id,
        "material": material_for(case),
        "source_geometry": {
            "source_part": "",
            "model_digest": "",
            "body_tags": [],
            "status": "pending",
        },
        "face_roles": face_roles,
        "load_values": load_values,
        "contact_pairs": contacts,
        "result_queries": result_queries,
        "solver": {
            "product": "NX THERMAL / FLOW" if item_id == "PERF-01" else "NX NASTRAN",
            "analysis_type": "Coupled Thermal-Flow" if item_id == "PERF-01" else "Structural",
            "solution_type": "Thermal" if item_id == "PERF-01" else "Nonlinear Statics",
        },
        "status": "pending",
    }
    binding["binding_digest"] = binding_digest(binding)
    return binding


def binding_digest(binding: dict) -> str:
    payload = dict(binding)
    payload.pop("binding_digest", None)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_bindings(
    binding: dict,
    *,
    material_library: dict | None = None,
    templates: dict | None = None,
) -> dict:
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
            value = library_material.get(field)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
                errors.append(f"材料 {material_name} 缺少有效字段 {field}")
        if library.get("status") != "released":
            warnings.append("材料库仍为 provisional，正式认证前必须用供应商 TDS 替换")

    geometry = binding.get("source_geometry") or {}
    if not geometry.get("source_part"):
        errors.append("缺少 source_geometry.source_part")
    if not geometry.get("body_tags"):
        errors.append("缺少 source_geometry.body_tags")
    if not geometry.get("model_digest"):
        errors.append("缺少 source_geometry.model_digest")

    for role in template["required_face_roles"]:
        item = (binding.get("face_roles") or {}).get(role) or {}
        if not item.get("face_ids"):
            errors.append(f"面角色 {role} 尚未绑定 face_ids")
        elif item.get("status") != "confirmed":
            errors.append(f"面角色 {role} 尚未确认")

    for name in template["required_loads"]:
        value = (binding.get("load_values") or {}).get(name)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            errors.append(f"载荷/边界值 {name} 缺失或不是数值")

    if item_id == "PERF-02":
        pairs = binding.get("contact_pairs") or []
        if not pairs:
            errors.append("PERF-02 缺少 contact_pairs")
        for index, pair in enumerate(pairs, 1):
            for key in template["required_contact_parameters"]:
                value = pair.get(key)
                if value in (None, "", []):
                    errors.append(f"接触对 {index} 缺少 {key}")
            if pair.get("status") != "confirmed":
                errors.append(f"接触对 {index} 尚未确认")

    for name in template["required_result_queries"]:
        query = (binding.get("result_queries") or {}).get(name)
        if not query:
            errors.append(f"结果查询 {name} 未定义")
        elif query.get("status") != "confirmed":
            errors.append(f"结果查询 {name} 尚未确认")

    expected_digest = binding.get("binding_digest")
    if expected_digest and expected_digest != binding_digest(binding):
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
