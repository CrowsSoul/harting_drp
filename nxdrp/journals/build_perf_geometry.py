# -*- coding: utf-8 -*-
"""在 NX 内按 PERF 参数生成参数化试验件。

输入由 ``NXDRP_PERF_GEOMETRY_REQUEST`` 指向的 JSON 提供，输出写到
``NXDRP_PERF_GEOMETRY_RESPONSE``。当前支持：

- ``cylinder``：PERF-01 导体圆柱；
- ``cantilever_contact_pair``：PERF-02 悬臂簧片 + 刚性接触板。

这里只生成几何，不设置材料、网格、接触或边界条件。
"""

from __future__ import annotations

import json
import os
import traceback


REQ = os.environ.get("NXDRP_PERF_GEOMETRY_REQUEST", "")
RESP = os.environ.get("NXDRP_PERF_GEOMETRY_RESPONSE", "")


def _emit(payload: dict) -> None:
    if not RESP:
        return
    with open(RESP, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, default=str, indent=2)


def _set_expression(expression, value: float) -> None:
    expression.Value = float(value)


def _create_cylinder(part, request: dict, features):
    builder = part.Features.CreateCylinderBuilder(None)
    builder.Type = features.CylinderBuilder.Types.AxisDiameterAndHeight
    builder.Origin = __import__("NXOpen").Point3d(0.0, 0.0, 0.0)
    builder.Direction = __import__("NXOpen").Vector3d(1.0, 0.0, 0.0)
    _set_expression(builder.Diameter, request["diameter_mm"])
    _set_expression(builder.Height, request["length_mm"])
    feature = builder.Commit()
    builder.Destroy()
    return feature


def _create_block(part, request: dict, features, body_name: str):
    builder = part.Features.CreateBlockFeatureBuilder(None)
    builder.Type = features.BlockFeatureBuilder.Types.OriginAndEdgeLengths
    origin = __import__("NXOpen").Point3d(*request.get("origin_mm", [0.0, 0.0, 0.0]))
    builder.SetOriginAndLengths(
        origin,
        str(request["length_mm"]),
        str(request["width_mm"]),
        str(request["thickness_mm"]),
    )
    feature = builder.Commit()
    builder.Destroy()
    try:
        body = list(feature.GetBodies())[0]
        body.SetName(body_name)
    except Exception:
        pass
    return feature


def main() -> None:
    import NXOpen

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
    created = []
    if kind == "cylinder":
        created.append(_create_cylinder(part, request, features))
    elif kind == "cantilever_contact_pair":
        created.append(_create_block(part, request, features, "CONTACT_SPRING"))
        plate = dict(request)
        plate.update({
            "origin_mm": [
                float(request.get("plate_gap_mm", 0.0)),
                -float(request["width_mm"]),
                0.0,
            ],
            "length_mm": float(request["length_mm"]),
            "width_mm": 2.0 * float(request["width_mm"]),
            "thickness_mm": float(request["thickness_mm"]),
        })
        created.append(_create_block(part, plate, features, "CONTACT_PLATE"))
    else:
        raise ValueError(f"不支持的 PERF 几何类型：{kind}")

    part.Save(
        NXOpen.BasePart.SaveComponents.FalseValue,
        NXOpen.BasePart.CloseAfterSave.FalseValue,
    )
    _emit({
        "ok": True,
        "state": "geometry_created",
        "case_id": request.get("case_id", ""),
        "kind": kind,
        "part_path": out_path,
        "feature_count": len(created),
        "body_count": len(list(part.Bodies)),
        "not_done": ["material", "mesh", "contact definition", "loads", "boundary conditions", "solve"],
    })


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        _emit({
            "ok": False,
            "state": "failed",
            "error": repr(exc),
            "traceback": traceback.format_exc()[-2000:],
        })
        raise
