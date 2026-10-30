# -*- coding: utf-8 -*-
"""DFM-08 最小壁厚。"""

from __future__ import annotations

from typing import Iterable

from ...checkers.base import BaseChecker, CheckContext
from ...contracts import Finding
from ...expr import ExprMissingSymbol
from ._rules import injection_default_params
from ._common import (
    material_for_part,
    material_min_wall,
    solid_parts,
    wall_samples,
)


class MinWallThicknessChecker(BaseChecker):
    check_item_id = "DFM-08"
    name = "最小壁厚"
    version = "0.1.0"
    owner = "注塑 代世航"
    process_types = ("injection", "casting")
    requires = ("faces", "face_area")
    default_params = injection_default_params("DFM-08")

    def applies(self, model, params) -> tuple[bool, str]:
        return True, ""

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        if ctx.rule.has_expression:
            return self._check_expression(ctx)
        return self._check_legacy(ctx)

    # ---------------- 规则模型 v2：材料阈值查表 + 临界倍率升级在 R-DFM-08 里 ----------------
    def _check_expression(self, ctx: CheckContext) -> list[Finding]:
        samples = wall_samples(ctx)
        findings: list[Finding] = []
        for part in solid_parts(ctx):
            material = material_for_part(ctx, part)
            candidates = [
                s
                for s in samples
                if s.part_id == part.part_id
                and s.area_mm2 >= float(ctx.param("min_inspect_area_mm2"))
            ]
            if not candidates:
                continue
            worst = min(candidates, key=lambda s: s.thickness_mm)
            try:
                verdicts = ctx.evaluate(
                    {"thickness": worst.thickness_mm, "material": material or ""}
                )
            except ExprMissingSymbol:
                continue  # 材料不在表内 = 缺数据，跳过
            for verdict in verdicts:
                minimum = float(verdict.threshold)
                confidence = 0.92 if worst.origin == "upstream_feature" else 0.76
                findings.append(
                    ctx.finding(
                        severity=verdict.severity,
                        part_refs=[part.part_id],
                        location=worst.location,
                        bbox=part.bbox,
                        measured_value=verdict.measured,
                        threshold_value=verdict.threshold,
                        unit=verdict.unit or "mm",
                        confidence=confidence,
                        face_ids=worst.face_ids,
                        message=(
                            f"{part.name or part.part_id}（{material}）局部壁厚 "
                            f"{float(verdict.measured):.3f} mm < 材料下限 {minimum:.3f} mm"
                        ),
                        suggestion_text=(
                            f"将该区域壁厚增加到至少 {minimum:.2f} mm，并优先均匀加厚同一片区域，"
                            f"避免用局部凸起补强。"
                        ),
                        suggestion_delta={
                            "minimum_wall_thickness_mm": round(minimum, 3),
                            "delta_mm": round(minimum - float(verdict.measured), 3),
                        },
                        note=(
                            "上游特征壁厚测量"
                            if worst.origin == "upstream_feature"
                            else "由投影重叠的平行平面估算壁厚，建议用截面测量复核"
                        ),
                        extra={
                            "material": material,
                            "sample_count": len(candidates),
                            "method": worst.origin,
                            "needs_precise_check": worst.origin != "upstream_feature",
                        },
                    )
                )
        return findings

    # ---------------- 旧路径：规则没有 expression 时照旧跑（兼容期保留） ----------------
    def _check_legacy(self, ctx: CheckContext) -> Iterable[Finding]:
        samples = wall_samples(ctx)
        findings: list[Finding] = []
        for part in solid_parts(ctx):
            material = material_for_part(ctx, part)
            minimum = material_min_wall(ctx, material)
            if minimum is None:
                continue
            candidates = [
                s
                for s in samples
                if s.part_id == part.part_id
                and s.area_mm2 >= float(ctx.param("min_inspect_area_mm2"))
            ]
            if not candidates:
                continue
            worst = min(candidates, key=lambda s: s.thickness_mm)
            # 与项目其他阈值检查一致：恰好等于阈值视为合格。
            if worst.thickness_mm >= minimum:
                continue
            confidence = 0.92 if worst.origin == "upstream_feature" else 0.76
            findings.append(
                ctx.finding(
                    severity=(
                        "P1"
                        if worst.thickness_mm
                        < minimum * float(ctx.param("critical_wall_ratio"))
                        else ctx.rule.severity
                    ),
                    part_refs=[part.part_id],
                    location=worst.location,
                    bbox=part.bbox,
                    measured_value=round(worst.thickness_mm, 4),
                    threshold_value=round(minimum, 4),
                    confidence=confidence,
                    face_ids=worst.face_ids,
                    message=(
                        f"{part.name or part.part_id}（{material}）局部壁厚 "
                        f"{worst.thickness_mm:.3f} mm < 材料下限 {minimum:.3f} mm"
                    ),
                    suggestion_text=(
                        f"将该区域壁厚增加到至少 {minimum:.2f} mm，并优先均匀加厚同一片区域，"
                        f"避免用局部凸起补强。"
                    ),
                    suggestion_delta={
                        "minimum_wall_thickness_mm": round(minimum, 3),
                        "delta_mm": round(minimum - worst.thickness_mm, 3),
                    },
                    note=(
                        "上游特征壁厚测量"
                        if worst.origin == "upstream_feature"
                        else "由投影重叠的平行平面估算壁厚，建议用截面测量复核"
                    ),
                    extra={
                        "material": material,
                        "sample_count": len(candidates),
                        "method": worst.origin,
                        "needs_precise_check": worst.origin != "upstream_feature",
                    },
                )
            )
        return findings


CHECKERS = [MinWallThicknessChecker()]
