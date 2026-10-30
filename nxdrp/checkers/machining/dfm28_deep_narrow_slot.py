# -*- coding: utf-8 -*-
"""DFM-28 深窄槽（粗筛）。

槽深 / 槽宽 > deep_slot_ratio（默认 3）报。槽取「对置内壁 + 共同槽底」的直槽，
槽深取两块槽壁沿槽底法向包围盒跨度的较小值。异形槽、斜槽、无平面槽底的槽
会漏检；槽壁是零件大侧面的一部分时槽深可能高估，需人工复核。
"""

from __future__ import annotations

from typing import Iterable

from nxdrp.checkers.base import CheckContext
from nxdrp.contracts import Finding
from nxdrp.expr import ExprMissingSymbol

from ._machining_common import (
    MachiningChecker,
    emit_finding,
    extract_slots,
    positive_number,
)


class DeepNarrowSlotChecker(MachiningChecker):
    check_item_id = "DFM-28"
    name = "深窄槽"
    requires = ("faces", "normals", "adjacency", "face_bbox")
    default_params = {
        "deep_slot_ratio": 3.0,
    }

    def applies(self, model, params) -> tuple[bool, str]:
        if not extract_slots(model):
            return False, "未识别到槽特征（粗筛）"
        return True, ""

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        if ctx.rule.has_expression:
            return self._check_expression(ctx)
        return self._check_legacy(ctx)

    # ---------------- 规则模型 v2：深宽比比较在 R-DFM-28 的 expression 里 ----------------
    def _check_expression(self, ctx: CheckContext) -> list[Finding]:
        limit = positive_number(ctx.param("deep_slot_ratio")) or 3.0
        findings = []
        for slot in extract_slots(ctx.model):
            if slot.depth <= 0 or slot.width <= 0:
                continue
            ratio = slot.depth / slot.width
            try:
                verdicts = ctx.evaluate(
                    {"ratio": ratio, "depth": slot.depth, "width": slot.width}
                )
            except ExprMissingSymbol:
                continue
            target_w = slot.depth / limit
            for verdict in verdicts:
                findings.append(
                    emit_finding(
                        ctx,
                        severity=verdict.severity,
                        part_id=slot.part_id,
                        face_ids=slot.face_ids,
                        message=(
                            f"【粗筛】零件 {slot.part_id} 槽（面 {'、'.join(slot.face_ids)}）"
                            f"深宽比 {verdict.measured:.2f} > {float(verdict.threshold):.2f}"
                            f"（槽深 {slot.depth:.2f} mm / 槽宽 {slot.width:.2f} mm）"
                        ),
                        measured=verdict.measured,
                        threshold=verdict.threshold,
                        unit=verdict.unit,
                        suggestion=(
                            f"优先将槽宽加大到 {target_w:.2f} mm 以上，或将槽深降到 "
                            f"{limit * slot.width:.2f} mm 以内；结构受限时改用分层铣削、"
                            f"插铣或电火花加工，并与工艺确认刀具悬伸。"
                        ),
                        feature_kind="slot",
                        confidence=slot.confidence,
                        location=slot.location,
                        extra={
                            "depth_mm": round(slot.depth, 4),
                            "width_mm": round(slot.width, 4),
                        },
                    )
                )
        return findings

    # ---------------- 旧路径：规则没有 expression 时照旧跑（兼容期保留） ----------------
    def _check_legacy(self, ctx: CheckContext) -> Iterable[Finding]:
        limit = positive_number(ctx.param("deep_slot_ratio")) or 3.0

        findings = []
        for slot in extract_slots(ctx.model):
            if slot.depth <= 0 or slot.width <= 0:
                continue
            ratio = slot.depth / slot.width
            if ratio <= limit:
                continue
            target_w = slot.depth / limit
            findings.append(
                emit_finding(
                    ctx,
                    part_id=slot.part_id,
                    face_ids=slot.face_ids,
                    message=(
                        f"【粗筛】零件 {slot.part_id} 槽（面 {'、'.join(slot.face_ids)}）"
                        f"深宽比 {ratio:.2f} > {limit:.2f}"
                        f"（槽深 {slot.depth:.2f} mm / 槽宽 {slot.width:.2f} mm）"
                    ),
                    measured=ratio,
                    threshold=limit,
                    unit="比值",
                    suggestion=(
                        f"优先将槽宽加大到 {target_w:.2f} mm 以上，或将槽深降到 "
                        f"{limit * slot.width:.2f} mm 以内；结构受限时改用分层铣削、"
                        f"插铣或电火花加工，并与工艺确认刀具悬伸。"
                    ),
                    feature_kind="slot",
                    confidence=slot.confidence,
                    location=slot.location,
                    extra={
                        "depth_mm": round(slot.depth, 4),
                        "width_mm": round(slot.width, 4),
                    },
                )
            )
        return findings


CHECKERS = [DeepNarrowSlotChecker()]
