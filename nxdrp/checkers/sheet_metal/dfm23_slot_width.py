# -*- coding: utf-8 -*-
"""DFM-23 槽的最小宽度（粗筛）。

识别两块互相对置、位于零件内部的平面壁，用平面间距离作为槽宽。
只支持直槽 + 平面槽底；圆角槽、异形槽不在识别范围内。
"""

from __future__ import annotations

from typing import Iterable

from nxdrp.checkers.base import CheckContext
from nxdrp.contracts import Finding
from nxdrp.expr import ExprMissingSymbol

from ._sheet_metal_dfm_common import (
    SheetMetalChecker,
    emit_finding,
    positive_number,
    thickness_text,
)


class SlotWidthChecker(SheetMetalChecker):
    check_item_id = "DFM-23"
    name = "槽的最小宽度"
    requires = ("faces", "normals", "adjacency")
    default_params = {
        "min_slot_width_ratio": 1.2,
        "sheet_thickness_mm": None,
    }

    def applies(self, model, params):
        feats = self.features(model, params)
        if not any(self.thickness(feats, slot.part_id) for slot in feats.slots):
            return False, "未识别到直槽候选（粗筛）"
        return True, ""

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        if ctx.rule.has_expression:
            return self._check_expression(ctx)
        return self._check_legacy(ctx)

    # ---------------- 规则模型 v2：槽宽下限判定在 R-DFM-23 的 expression 里 ----------------
    def _check_expression(self, ctx: CheckContext) -> list[Finding]:
        feats = self.features(ctx.model, ctx.params)
        findings = []
        for slot in feats.slots:
            thickness = self.thickness(feats, slot.part_id)
            if thickness is None:
                continue
            try:
                verdicts = ctx.evaluate(
                    {"width": slot.width, "thickness": thickness.value}
                )
            except ExprMissingSymbol:
                continue
            faces = "、".join(slot.face_ids)
            for verdict in verdicts:
                limit = float(verdict.threshold)
                findings.append(
                    emit_finding(
                        ctx,
                        severity=verdict.severity,
                        part_id=slot.part_id,
                        face_ids=slot.face_ids,
                        message=(
                            f"【粗筛】零件 {slot.part_id} 槽（面 {faces}）宽度 "
                            f"{float(verdict.measured):.3f} mm < {limit / thickness.value:.2f}×t={limit:.3f} mm"
                            f"（{thickness_text(thickness)}）"
                        ),
                        measured=verdict.measured,
                        threshold=verdict.threshold,
                        unit=verdict.unit or "mm",
                        suggestion=(
                            f"将槽宽增大到至少 {limit:.2f} mm，"
                            f"或改用更薄板材/激光切割工艺。"
                        ),
                        thickness=thickness,
                        feature_kind="slot",
                        feature_confidence=slot.confidence,
                        location=slot.location,
                        note=(
                            "钣金粗筛：只识别直槽（对置平面壁 + 共同平面槽底），"
                            "圆角槽/异形槽会被漏检，需人工复核"
                        ),
                    )
                )
        return findings

    # ---------------- 旧路径：规则没有 expression 时照旧跑（兼容期保留） ----------------
    def _check_legacy(self, ctx: CheckContext) -> Iterable[Finding]:
        ratio = positive_number(ctx.param("min_slot_width_ratio")) or 1.2
        feats = self.features(ctx.model, ctx.params)
        findings = []
        for slot in feats.slots:
            thickness = self.thickness(feats, slot.part_id)
            if thickness is None:
                continue
            limit = ratio * thickness.value
            if slot.width >= limit - 1e-9:
                continue
            faces = "、".join(slot.face_ids)
            findings.append(
                emit_finding(
                    ctx,
                    part_id=slot.part_id,
                    face_ids=slot.face_ids,
                    message=(
                        f"【粗筛】零件 {slot.part_id} 槽（面 {faces}）宽度 "
                        f"{slot.width:.3f} mm < {ratio:.2f}×t={limit:.3f} mm"
                        f"（{thickness_text(thickness)}）"
                    ),
                    measured=slot.width,
                    threshold=limit,
                    suggestion=(
                        f"将槽宽增大到至少 {limit:.2f} mm，"
                        f"或改用更薄板材/激光切割工艺。"
                    ),
                    thickness=thickness,
                    feature_kind="slot",
                    feature_confidence=slot.confidence,
                    location=slot.location,
                    note=(
                        "钣金粗筛：只识别直槽（对置平面壁 + 共同平面槽底），"
                        "圆角槽/异形槽会被漏检，需人工复核"
                    ),
                )
            )
        return findings


CHECKERS = [SlotWidthChecker()]
