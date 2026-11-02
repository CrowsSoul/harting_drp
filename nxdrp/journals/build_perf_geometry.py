# -*- coding: utf-8 -*-
"""在 NX 内创建 PERF 参数化实体并返回可追溯的几何绑定提议。

坐标约定：X 为长度/插拔方向，Y 为宽度，Z 为厚度和法向过盈方向。
本 journal 只创建 CAD 几何，不设置材料、网格、接触、载荷或求解。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import traceback


REQ = os.environ.get("NXDRP_NX_REQUEST", "")
RESP = os.environ.get("NXDRP_NX_RESPONSE", "")


def _emit(payload: dict) -> None:
    if not RESP:
        return
    parent = os.path.dirname(os.path.abspath(RESP))
    os.makedirs(parent, exist_ok=True)
    with open(RESP, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, default=str, indent=2)


def _positive(request: dict, name: str) -> float:
    value = request.get(name)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)) or float(value) <= 0:
        raise ValueError(f"{name} 必须是大于 0 的有限数值")
    return float(value)


def _lead_angle(request: dict) -> float:
    value = request.get("lead_angle_deg")
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)) or not 0 < float(value) < 90:
        raise ValueError("lead_angle_deg 必须在 0 到 90 度之间")
    return float(value)


def _set_expression(expression, value: float) -> None:
    expression.Value = float(value)


def _single_body(feature, name: str):
    bodies = list(feature.GetBodies())
    if len(bodies) != 1:
        raise RuntimeError(f"特征 {name} 应生成一个实体，实际为 {len(bodies)}")
    body = bodies[0]
    body.SetName(name)
    return body


def _create_cylinder(part, request: dict, features):
    import NXOpen

    diameter = _positive(request, "diameter_mm")
    length = _positive(request, "length_mm")
    builder = part.Features.CreateCylinderBuilder(None)
    try:
        builder.Type = features.CylinderBuilder.Types.AxisDiameterAndHeight
        builder.Origin = NXOpen.Point3d(0.0, 0.0, 0.0)
        builder.Direction = NXOpen.Vector3d(1.0, 0.0, 0.0)
        _set_expression(builder.Diameter, diameter)
        _set_expression(builder.Height, length)
        return _single_body(builder.Commit(), "CONDUCTOR")
    finally:
        builder.Destroy()


def _create_block(part, features, name: str, origin, length: float, width: float, thickness: float):
    import NXOpen

    builder = part.Features.CreateBlockFeatureBuilder(None)
    try:
        builder.Type = features.BlockFeatureBuilder.Types.OriginAndEdgeLengths
        builder.SetOriginAndLengths(
            NXOpen.Point3d(*origin),
            str(length),
            str(width),
            str(thickness),
        )
        return _single_body(builder.Commit(), name)
    finally:
        builder.Destroy()


def _target_definition(request: dict) -> dict:
    """返回初始非穿透位置的目标几何及插入行程参数。

    目标从簧片自由端右侧开始，插入时沿 -X 移动。负斜率先接触簧片，
    随后在同一行程内形成 Z 向过盈；初始几何不与簧片实体相交。
    """
    length = _positive(request, "length_mm")
    thickness = _positive(request, "thickness_mm")
    overlap = _positive(request, "normal_overlap_mm")
    stroke = _positive(request, "insertion_stroke_mm")
    slope = math.tan(math.radians(_lead_angle(request)))
    tail = max(0.25 * length, thickness)
    x0 = length
    x1 = x0 + stroke + tail
    z0 = thickness - overlap + slope * stroke
    if z0 <= thickness:
        raise ValueError("insertion_stroke_mm 太短，无法在初始位置避免目标与簧片穿透")
    z1 = thickness - overlap - slope * tail
    return {
        "x0": x0,
        "x1": x1,
        "z0": z0,
        "z1": z1,
        "slope": slope,
        "contact_travel_mm": stroke - overlap / slope,
        "deflection_travel_mm": overlap / slope,
        "points_xz": [(x0, z0), (x1, z1), (x1, z1 + thickness), (x0, z0 + thickness)],
    }


def _create_sloped_target(part, request: dict, features):
    """创建初始非穿透的 XZ 梯形目标并沿 Y 拉伸。"""
    import NXOpen

    width = _positive(request, "width_mm")
    definition = _target_definition(request)
    points = [NXOpen.Point3d(x, 0.0, z) for x, z in definition["points_xz"]]
    lines = [
        part.Curves.CreateLine(points[index], points[(index + 1) % len(points)])
        for index in range(len(points))
    ]
    section = part.Sections.CreateSection(0.0001, 0.001, 0.5)
    section.SetAllowedEntityTypes(NXOpen.Section.AllowTypes.OnlyCurves)
    for index, line in enumerate(lines):
        section.AddToSection(
            [line],
            line,
            None,
            None,
            [points[index]],
            NXOpen.Section.Mode.Create,
            False,
        )
    builder = part.Features.CreateExtrudeBuilder(None)
    try:
        builder.Section = section
        builder.Direction = NXOpen.Vector3d(0.0, 1.0, 0.0)
        builder.Limits.StartExtend.Value.RightHandSide = "0.0"
        builder.Limits.EndExtend.Value.RightHandSide = str(width)
        return _single_body(builder.Commit(), "CONTACT_TARGET")
    finally:
        builder.Destroy()


def _body_id(body) -> str:
    return f"B{int(body.Tag)}"


def _face_records(session, bodies: list) -> dict[str, list[dict]]:
    """读取真实 NX 面标签、面积、形心和平面法向；测量失败会明确中止。"""
    import NXOpen

    ufs = NXOpen.UF.UFSession.GetUFSession()
    records = {}
    for body in sorted(bodies, key=lambda value: (value.Name, int(value.Tag))):
        body_records = []
        faces = sorted(body.GetFaces(), key=lambda value: int(value.Tag))
        if not faces:
            raise RuntimeError(f"实体 {body.Name} 没有面")
        for face in faces:
            tag = int(face.Tag)
            try:
                data = ufs.Modeling.AskFaceData(tag)
                properties = session.Measurement.GetFaceProperties([face], 0.99, False, False)
                area = float(properties[0])
                centroid = [float(value) for value in properties[3]]
            except Exception as exc:
                raise RuntimeError(f"无法读取 {body.Name} 的面 F{tag} 几何属性：{exc}") from exc
            face_type = int(data[0])
            is_planar = face_type == 16 or "planar" in str(face.SolidFaceType).casefold()
            body_records.append({
                "face_id": f"F{tag}",
                "tag": tag,
                "body_id": _body_id(body),
                "body_name": body.Name,
                "area_mm2": area,
                "centroid_mm": centroid,
                "normal": [float(value) for value in data[2]] if is_planar else None,
                "axis": None if is_planar else [float(value) for value in data[2]],
                "uf_face_type": face_type,
            })
        records[body.Name] = body_records
    return records


def _pick(records: dict[str, list[dict]], body_name: str, role: str, predicate) -> dict:
    matches = [item for item in records[body_name] if predicate(item)]
    if len(matches) != 1:
        candidates = [item["face_id"] for item in matches]
        raise RuntimeError(f"{body_name} 的 {role} 应匹配一个面，实际匹配 {candidates}")
    return matches[0]


def _near(value: float, target: float, scale: float) -> bool:
    return abs(value - target) <= 1e-6 * max(1.0, scale)


def _role_payload(face: dict) -> dict:
    return {
        "face_ids": [face["face_id"]],
        "body_ids": [face["body_id"]],
        "faces": [dict(face)],
        "status": "proposed",
    }


def _proposed_roles(kind: str, request: dict, records: dict[str, list[dict]]) -> dict:
    if kind == "cylinder":
        length = _positive(request, "length_mm")
        inlet = _pick(records, "CONDUCTOR", "electrical_inlet", lambda item: _near(item["centroid_mm"][0], 0.0, length))
        outlet = _pick(records, "CONDUCTOR", "electrical_outlet", lambda item: _near(item["centroid_mm"][0], length, length))
        lateral = _pick(records, "CONDUCTOR", "convection/radiation", lambda item: item["normal"] is None)
        return {
            "electrical_inlet": _role_payload(inlet),
            "electrical_outlet": _role_payload(outlet),
            "convection": _role_payload(lateral),
            "radiation": _role_payload(lateral),
        }

    length = _positive(request, "length_mm")
    thickness = _positive(request, "thickness_mm")
    target_definition = _target_definition(request)
    fixed = _pick(records, "CONTACT_SPRING", "fixed_root", lambda item: _near(item["centroid_mm"][0], 0.0, length))
    driven = _pick(
        records,
        "CONTACT_TARGET",
        "driven_face",
        lambda item: _near(item["centroid_mm"][0], target_definition["x1"], target_definition["x1"]),
    )
    source = _pick(
        records,
        "CONTACT_SPRING",
        "contact_source",
        lambda item: _near(item["centroid_mm"][2], thickness, thickness) and item["normal"] is not None and item["normal"][2] > 0.9,
    )
    target = _pick(
        records,
        "CONTACT_TARGET",
        "contact_target",
        lambda item: item["normal"] is not None and item["normal"][2] < -0.01 and abs(item["normal"][0]) > 0.001,
    )
    return {
        "fixed_root": _role_payload(fixed),
        "driven_face": _role_payload(driven),
        "contact_source": _role_payload(source),
        "contact_target": _role_payload(target),
    }


def _part_digest(path: str) -> str:
    if not os.path.isfile(path):
        raise RuntimeError(f"NX 保存后找不到零件：{path}")
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    import NXOpen

    if not REQ or not RESP:
        raise ValueError("必须设置 NXDRP_NX_REQUEST 和 NXDRP_NX_RESPONSE")
    with open(REQ, "r", encoding="utf-8") as fh:
        request = json.load(fh)
    out_path = os.path.abspath(request["out_path"])
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    if os.path.exists(out_path):
        os.remove(out_path)

    session = NXOpen.Session.GetSession()
    part = session.Parts.NewDisplay(out_path, NXOpen.PartUnits.Millimeters)
    if isinstance(part, (tuple, list)):
        part = part[0]
    session.Parts.SetWork(part)
    features = NXOpen.Features

    kind = request["kind"]
    if kind == "cylinder":
        bodies = [_create_cylinder(part, request, features)]
        body_roles = {"conductor": "CONDUCTOR"}
    elif kind == "cantilever_contact_pair":
        if request.get("modeled_contact_count", 1) != 1:
            raise ValueError("PERF-02 只能创建一个接触对")
        spring = _create_block(
            part,
            features,
            "CONTACT_SPRING",
            (0.0, 0.0, 0.0),
            _positive(request, "length_mm"),
            _positive(request, "width_mm"),
            _positive(request, "thickness_mm"),
        )
        target = _create_sloped_target(part, request, features)
        bodies = [spring, target]
        body_roles = {"contact_spring": "CONTACT_SPRING", "contact_target": "CONTACT_TARGET"}
    else:
        raise ValueError(f"不支持的 PERF 几何类型：{kind}")

    part.Save(
        NXOpen.BasePart.SaveComponents.FalseValue,
        NXOpen.BasePart.CloseAfterSave.FalseValue,
    )
    actual_bodies = list(part.Bodies)
    if len(actual_bodies) != len(bodies):
        raise RuntimeError(f"预期 {len(bodies)} 个实体，实际 {len(actual_bodies)} 个")
    records = _face_records(session, bodies)
    roles = _proposed_roles(kind, request, records)
    part_digest = _part_digest(out_path)
    body_payload = [
        {
            "name": body.Name,
            "tag": int(body.Tag),
            "body_id": _body_id(body),
            "role": next(role for role, name in body_roles.items() if name == body.Name),
        }
        for body in sorted(bodies, key=lambda value: (value.Name, int(value.Tag)))
    ]
    _emit({
        "ok": True,
        "state": "geometry_created",
        "case_id": request.get("case_id", ""),
        "model_id": request.get("case_id", ""),
        "kind": kind,
        "part_path": out_path,
        "part_digest": part_digest,
        "model_digest": part_digest,
        "feature_count": len(bodies),
        "body_count": len(actual_bodies),
        "body_tags": [int(body.Tag) for body in sorted(bodies, key=lambda value: (value.Name, int(value.Tag)))],
        "bodies": body_payload,
        "body_roles": {
            role: next(item["body_id"] for item in body_payload if item["name"] == name)
            for role, name in body_roles.items()
        },
        "face_roles": roles,
        "target_motion": ({
            "direction": "-X",
            "insertion_stroke_mm": _positive(request, "insertion_stroke_mm"),
            "contact_travel_mm": _target_definition(request)["contact_travel_mm"],
            "deflection_travel_mm": _target_definition(request)["deflection_travel_mm"],
            "driven_body": "CONTACT_TARGET",
        } if kind == "cantilever_contact_pair" else None),
        "not_done": [
            "binding reviewer confirmation",
            "material",
            "mesh",
            "contact definition",
            "loads",
            "boundary conditions",
            "solve",
        ],
    })


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        _emit({
            "ok": False,
            "state": "failed",
            "error": repr(exc),
            "traceback": traceback.format_exc()[-4000:],
        })
        raise
