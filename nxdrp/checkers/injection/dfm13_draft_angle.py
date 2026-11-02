# -*- coding: utf-8 -*-
"""DFM-13 拔模角。"""

from __future__ import annotations

from typing import Iterable

from ...checkers.base import BaseChecker, CheckContext
from ...contracts import Finding
from ...expr import ExprMissingSymbol
from ...geom import draft_angle_deg
from ._rules import injection_default_params
from ._common import pull_direction, solid_parts


class DraftAngleChecker(BaseChecker):
    check_item_id = "DFM-13"
    name = "拔模角"
    version = "0.1.0"
    owner = "注塑 代世航"
    process_types = ("injection", "casting")
    requires = ("faces", "normals")
    default_params = injection_default_params("DFM-13")

    def applies(self, model, params) -> tuple[bool, str]:
        if not any(f.normal is not None for f in model.faces if f.solid_face_type == "planar"):
            return False, "模型没有可判定拔模方向的平面法向"
        return True, ""

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        if ctx.rule.has_expression:
            return self._check_expression(ctx)
        return self._check_legacy(ctx)

    # ---------------- 规则模型 v2：最小拔模角判定在 R-DFM-13 的 expression 里 ----------------
    def _check_expression(self, ctx: CheckContext) -> list[Finding]:
        minimum = float(ctx.param("min_draft_angle_deg"))
        pull = pull_direction(ctx)
        findings: list[Finding] = []
        for part in solid_parts(ctx):
            for face in ctx.faces(part.part_id, "planar"):
                angle = draft_angle_deg(face, pull)
                if angle is None:
                    continue
                try:
                    verdicts = ctx.evaluate({"angle_deg": angle})
                except ExprMissingSymbol:
                    continue
                for verdict in verdicts:
                    findings.append(
                        ctx.finding(
                            severity=verdict.severity,
                            part_refs=[part.part_id],
                            location=face.cog,
                            bbox=face.bbox or part.bbox,
                            measured_value=verdict.measured,
                            threshold_value=verdict.threshold,
                            unit=verdict.unit or "deg",
                            confidence=0.86,
                            face_ids=[face.face_id],
                            message=(
                                f"面 {face.face_id} 沿开模方向 {tuple(round(x, 3) for x in pull)} "
                                f"的拔模角 {float(verdict.measured):.2f}° < {minimum:.2f}°"
                            ),
                            suggestion_text=(
                                f"将该面拔模角增加到至少 {minimum + 0.5:.2f}°，"
                                f"深腔或纹理面建议提高到 1.0° 以上。"
                            ),
                            suggestion_delta={"target_draft_angle_deg": round(minimum + 0.5, 3)},
                            note="按平面外法向与统一开模方向计算；分型方向需人工确认",
                            extra={
                                "pull_direction": [round(x, 6) for x in pull],
                                "method": "planar_normal",
                            },
                        )
                    )
        return findings

    # ---------------- 旧路径：规则没有 expression 时照旧跑（兼容期保留） ----------------
    def _check_legacy(self, ctx: CheckContext) -> Iterable[Finding]:
        minimum = float(ctx.param("min_draft_angle_deg"))
        tolerance = float(ctx.param("angle_tolerance_deg"))
        pull = pull_direction(ctx)
        findings: list[Finding] = []
        for part in solid_parts(ctx):
            for face in ctx.faces(part.part_id, "planar"):
                angle = draft_angle_deg(face, pull)
                if angle is None or angle >= minimum - tolerance:
                    continue
                findings.append(
                    ctx.finding(
                        part_refs=[part.part_id],
                        location=face.cog,
                        bbox=face.bbox or part.bbox,
                        measured_value=round(angle, 4),
                        threshold_value=minimum,
                        unit="deg",
                        confidence=0.86,
                        face_ids=[face.face_id],
                        message=(
                            f"面 {face.face_id} 沿开模方向 {tuple(round(x, 3) for x in pull)} "
                            f"的拔模角 {angle:.2f}° < {minimum:.2f}°"
                        ),
                        suggestion_text=(
                            f"将该面拔模角增加到至少 {minimum + 0.5:.2f}°，"
                            f"深腔或纹理面建议提高到 1.0° 以上。"
                        ),
                        suggestion_delta={"target_draft_angle_deg": round(minimum + 0.5, 3)},
                        note="按平面外法向与统一开模方向计算；分型方向需人工确认",
                        extra={
                            "pull_direction": [round(x, 6) for x in pull],
                            "method": "planar_normal",
                        },
                    )
                )
        return findings


CHECKERS = [DraftAngleChecker()]
