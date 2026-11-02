# -*- coding: utf-8 -*-
"""DFM-14 倒扣。"""

from __future__ import annotations

from typing import Iterable

from ...checkers.base import BaseChecker, CheckContext
from ...contracts import Finding
from ...expr import ExprMissingSymbol
from ._rules import injection_default_params
from ._common import feature_face_ids, feature_location, undercut_features


class UndercutChecker(BaseChecker):
    check_item_id = "DFM-14"
    name = "倒扣"
    version = "0.1.0"
    owner = "注塑 代世航"
    process_types = ("injection", "casting")
    requires = ("faces",)
    default_params = injection_default_params("DFM-14")

    def applies(self, model, params) -> tuple[bool, str]:
        payload = model.meta.get("injection_features") or {}
        values = payload.get("undercuts", []) if isinstance(payload, dict) else []
        if not values:
            return False, "缺少倒扣特征记录；仅凭面法向无法可靠区分倒扣与普通侧壁"
        return True, ""

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        if ctx.rule.has_expression:
            return self._check_expression(ctx)
        return self._check_legacy(ctx)

    # ---------------- 规则模型 v2：深度门槛判定在 R-DFM-14 的 expression 里 ----------------
    def _check_expression(self, ctx: CheckContext) -> list[Finding]:
        findings: list[Finding] = []
        minimum_val = float(ctx.param("min_undercut_depth_mm"))
        for rec in undercut_features(ctx):
            if bool(rec.get("exempt") or rec.get("design_intent")):
                continue
            part_id = str(rec["part_id"])
            part = ctx.part(part_id)
            depth = rec.get("depth_mm", rec.get("undercut_depth_mm"))
            try:
                depth_val = float(depth) if depth is not None else None
            except (TypeError, ValueError):
                depth_val = None
            measurements = {
                "depth_mm": depth_val if depth_val is not None else 0.0,
                "has_depth": 1 if depth_val is not None else 0,
            }
            try:
                verdicts = ctx.evaluate(measurements)
            except ExprMissingSymbol:
                continue
            direction = rec.get("direction") or rec.get("draw_direction") or []
            for verdict in verdicts:
                findings.append(
                    ctx.finding(
                        severity=verdict.severity,
                        part_refs=[part_id],
                        location=feature_location(ctx, rec),
                        bbox=part.bbox if part else None,
                        measured_value=verdict.measured,
                        threshold_value=verdict.threshold,
                        unit=verdict.unit or "mm",
                        confidence=0.94,
                        face_ids=feature_face_ids(rec),
                        message=(
                            f"{part.name if part else part_id} 存在沿 "
                            f"{tuple(direction) if direction else '特征方向'} 无法直接脱模的倒扣"
                        ),
                        suggestion_text=(
                            "优先取消倒扣或改为斜顶/滑块可加工方向；"
                            "若功能必须保留，在模具方案中明确滑块、斜顶或二次抽芯机构。"
                        ),
                        suggestion_delta={"requires_mold_action": True},
                        note="来自上游倒扣特征记录；方向和深度可追溯到特征提取阶段",
                        extra={"feature": rec},
                    )
                )
        return findings

    # ---------------- 旧路径：规则没有 expression 时照旧跑（兼容期保留） ----------------
    def _check_legacy(self, ctx: CheckContext) -> Iterable[Finding]:
        findings: list[Finding] = []
        for rec in undercut_features(ctx):
            if bool(rec.get("exempt") or rec.get("design_intent")):
                continue
            part_id = str(rec["part_id"])
            part = ctx.part(part_id)
            depth = rec.get("depth_mm", rec.get("undercut_depth_mm"))
            minimum_val = float(ctx.param("min_undercut_depth_mm"))
            try:
                depth_val = float(depth) if depth is not None else None
            except (TypeError, ValueError):
                depth_val = None
            if depth_val is not None and depth_val < minimum_val:
                continue
            direction = rec.get("direction") or rec.get("draw_direction") or []
            findings.append(
                ctx.finding(
                    part_refs=[part_id],
                    location=feature_location(ctx, rec),
                    bbox=part.bbox if part else None,
                    measured_value=depth_val,
                    threshold_value=minimum_val,
                    confidence=0.94,
                    face_ids=feature_face_ids(rec),
                    message=(
                        f"{part.name if part else part_id} 存在沿 "
                        f"{tuple(direction) if direction else '特征方向'} 无法直接脱模的倒扣"
                    ),
                    suggestion_text=(
                        "优先取消倒扣或改为斜顶/滑块可加工方向；"
                        "若功能必须保留，在模具方案中明确滑块、斜顶或二次抽芯机构。"
                    ),
                    suggestion_delta={"requires_mold_action": True},
                    note="来自上游倒扣特征记录；方向和深度可追溯到特征提取阶段",
                    extra={"feature": rec},
                )
            )
        return findings


CHECKERS = [UndercutChecker()]
