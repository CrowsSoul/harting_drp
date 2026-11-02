# -*- coding: utf-8 -*-
"""DFM-26 冲压凸台高度（二期占位实现，粗筛）。

凸台候选 = 圆柱面端部有与轴平行、面积约等于 πr² 的小平面端盖。
凸台高度取圆柱面包围盒沿轴向的跨度，h/t 超出允许区间即报告。
"""

from __future__ import annotations

from typing import Iterable

from nxdrp.checkers.base import CheckContext
from nxdrp.contracts import Finding
from nxdrp.expr import ExprMissingSymbol

from ._sheet_metal_dfm_common import (
    SheetMetalChecker,
    emit_finding,
    face_point,
    positive_number,
    thickness_text,
)


class PunchBossHeightChecker(SheetMetalChecker):
    check_item_id = "DFM-26"
    name = "冲压凸台高度"
    requires = ("faces", "normals", "axes", "cylindrical_faces", "face_radius")
    default_params = {
        "min_boss_height_ratio": 0.6,
        "max_boss_height_ratio": 1.5,
        "sheet_thickness_mm": None,
    }

    def applies(self, model, params):
        feats = self.features(model, params)
        if not any(self.thickness(feats, boss.part_id) for boss in feats.bosses):
            return False, "未识别到冲压凸台候选（粗筛）"
        return True, ""

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        if ctx.rule.has_expression:
            return self._check_expression(ctx)
        return self._check_legacy(ctx)

    # ---------------- 规则模型 v2：h/t 区间判定在 R-DFM-26 的 expression 里 ----------------
    def _check_expression(self, ctx: CheckContext) -> list[Finding]:
        min_ratio = positive_number(ctx.param("min_boss_height_ratio")) or 0.6
        max_ratio = positive_number(ctx.param("max_boss_height_ratio")) or 1.5
        if min_ratio > max_ratio:
            return []          # 参数自相矛盾：几何层直接跳过（配置问题，不是判定）
        feats = self.features(ctx.model, ctx.params)
        findings = []
        for boss in feats.bosses:
            thickness = self.thickness(feats, boss.part_id)
            if thickness is None:
                continue
            try:
                verdicts = ctx.evaluate(
                    {"height": boss.height, "thickness": thickness.value}
                )
            except ExprMissingSymbol:
                continue
            ratio = boss.height / thickness.value
            for verdict in verdicts:
                low = min_ratio * thickness.value
                high = max_ratio * thickness.value
                findings.append(
                    emit_finding(
                        ctx,
                        severity=verdict.severity,
                        part_id=boss.part_id,
                        face_ids=[boss.face.face_id],
                        message=(
                            f"【粗筛】零件 {boss.part_id} 冲压凸台 {boss.face.face_id} "
                            f"高 {float(verdict.measured):.3f} mm，h/t={ratio:.2f} 超出 "
                            f"[{min_ratio:.2f}, {max_ratio:.2f}]"
                            f"（{thickness_text(thickness)}）"
                        ),
                        measured=verdict.measured,
                        threshold=verdict.threshold,
                        unit=verdict.unit or "mm",
                        suggestion=(
                            f"将凸台高度调整到 {low:.2f}–{high:.2f} mm 区间内，"
                            f"必要时增加冲压次数或修改凸台直径。"
                        ),
                        thickness=thickness,
                        feature_kind="boss",
                        feature_confidence=boss.confidence,
                        location=face_point(boss.face),
                        note=(
                            "钣金粗筛（二期项）：凸台高度取圆柱面包围盒轴向跨度，"
                            "未区分材料流动与端盖形状，需人工复核"
                        ),
                    )
                )
        return findings

    # ---------------- 旧路径：规则没有 expression 时照旧跑（兼容期保留） ----------------
    def _check_legacy(self, ctx: CheckContext) -> Iterable[Finding]:
        min_ratio = positive_number(ctx.param("min_boss_height_ratio")) or 0.6
        max_ratio = positive_number(ctx.param("max_boss_height_ratio")) or 1.5
        if min_ratio > max_ratio:
            return []
        feats = self.features(ctx.model, ctx.params)
        findings = []
        for boss in feats.bosses:
            thickness = self.thickness(feats, boss.part_id)
            if thickness is None:
                continue
            low = min_ratio * thickness.value
            high = max_ratio * thickness.value
            if low - 1e-9 <= boss.height <= high + 1e-9:
                continue
            threshold = low if boss.height < low else high
            ratio = boss.height / thickness.value
            findings.append(
                emit_finding(
                    ctx,
                    part_id=boss.part_id,
                    face_ids=[boss.face.face_id],
                    message=(
                        f"【粗筛】零件 {boss.part_id} 冲压凸台 {boss.face.face_id} "
                        f"高 {boss.height:.3f} mm，h/t={ratio:.2f} 超出 "
                        f"[{min_ratio:.2f}, {max_ratio:.2f}]"
                        f"（{thickness_text(thickness)}）"
                    ),
                    measured=boss.height,
                    threshold=threshold,
                    suggestion=(
                        f"将凸台高度调整到 {low:.2f}–{high:.2f} mm 区间内，"
                        f"必要时增加冲压次数或修改凸台直径。"
                    ),
                    thickness=thickness,
                    feature_kind="boss",
                    feature_confidence=boss.confidence,
                    location=face_point(boss.face),
                    note=(
                        "钣金粗筛（二期项）：凸台高度取圆柱面包围盒轴向跨度，"
                        "未区分材料流动与端盖形状，需人工复核"
                    ),
                )
            )
        return findings


CHECKERS = [PunchBossHeightChecker()]
