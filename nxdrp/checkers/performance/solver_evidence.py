# -*- coding: utf-8 -*-
"""NX / Simcenter / FloEFD 求解结果的可审计读取器。

PERF 公式可以独立做快速筛查，但只有经过这里校验的求解结果才允许标记为
``cae_solver``。缺少结果、未收敛、模型摘要不一致或来源伪造时，调用方必须
退回公式筛査或跳过，不能把本地公式冒充成 CAE 结果。
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any


class SolverEvidenceError(ValueError):
    pass


@dataclass(frozen=True)
class SolverEvidence:
    path: str
    case_id: str
    check_item_id: str
    product: str
    version: str
    license_mode: str
    convergence_status: str
    outputs: dict[str, dict]
    model_id: str = ""
    content_digest: str = ""
    input_digest: str = ""
    residual: float | None = None

    @property
    def is_converged(self) -> bool:
        return self.convergence_status == "converged"

    def value(self, name: str, unit: str | None = None) -> float:
        if name not in self.outputs:
            raise SolverEvidenceError(f"{self.path}: 缺少求解输出 {name}")
        item = self.outputs[name]
        value = item.get("value")
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
            raise SolverEvidenceError(f"{self.path}: 输出 {name} 不是有限数值")
        actual_unit = str(item.get("unit") or "")
        if unit is not None and actual_unit != unit:
            raise SolverEvidenceError(
                f"{self.path}: 输出 {name} 单位是 {actual_unit!r}，规则要求 {unit!r}"
            )
        return float(value)

    def as_dict(self) -> dict:
        return {
            "source": "cae_solver",
            "path": self.path,
            "case_id": self.case_id,
            "product": self.product,
            "version": self.version,
            "license_mode": self.license_mode,
            "convergence_status": self.convergence_status,
            "model_id": self.model_id,
            "content_digest": self.content_digest,
            "input_digest": self.input_digest,
            "residual": self.residual,
        }


@lru_cache(maxsize=32)
def _load_cached(path: str, mtime_ns: int) -> tuple[dict, str]:
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    return json.loads(text), text


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def load_solver_evidence(
    path: str,
    *,
    expected_item: str | None = None,
    expected_model_id: str = "",
    expected_digest: str = "",
    require_converged: bool = True,
    require_authorized: bool = False,
) -> SolverEvidence:
    ap = os.path.abspath(path)
    if not os.path.isfile(ap):
        raise SolverEvidenceError(f"求解结果文件不存在：{ap}")
    stat = os.stat(ap)
    payload, _raw = _load_cached(ap, stat.st_mtime_ns)
    if payload.get("schema_version") != "1.0.0":
        raise SolverEvidenceError(f"{ap}: schema_version 必须为 1.0.0")
    case_id = str(payload.get("case_id") or "")
    item = str(payload.get("check_item_id") or "")
    if not case_id or item not in ("PERF-01", "PERF-02"):
        raise SolverEvidenceError(f"{ap}: case_id/check_item_id 无效")
    if expected_item and item != expected_item:
        raise SolverEvidenceError(f"{ap}: 结果所属 {item}，当前检查要求 {expected_item}")

    solver = payload.get("solver") or {}
    if not isinstance(solver, dict):
        raise SolverEvidenceError(f"{ap}: solver 必须是对象")
    product = str(solver.get("product") or "")
    version = str(solver.get("version") or "")
    license_mode = str(solver.get("license_mode") or "")
    if not _nonempty(product) or not _nonempty(version):
        raise SolverEvidenceError(f"{ap}: solver.product/version 不能为空")
    if require_authorized and license_mode.casefold() not in {
        "authorized",
        "commercial",
        "floating",
        "node_locked",
        "evaluation",
    }:
        raise SolverEvidenceError(
            f"{ap}: solver.license_mode={license_mode!r} 不是可接受的正式授权标记"
        )
    lowered = product.casefold()
    if any(word in lowered for word in ("mock", "simulated", "python", "formula only")):
        raise SolverEvidenceError(f"{ap}: {product!r} 不是可接受的 CAE 求解器来源")

    convergence = str(payload.get("convergence_status") or "")
    if convergence not in ("converged", "not_converged", "failed", "unknown"):
        raise SolverEvidenceError(f"{ap}: convergence_status 无效")
    if require_converged and convergence != "converged":
        raise SolverEvidenceError(f"{ap}: 求解未收敛（{convergence}）")

    outputs = payload.get("outputs")
    if not isinstance(outputs, dict) or not outputs:
        raise SolverEvidenceError(f"{ap}: outputs 不能为空")
    normalized: dict[str, dict] = {}
    for name, item_value in outputs.items():
        if not isinstance(item_value, dict):
            raise SolverEvidenceError(f"{ap}: 输出 {name} 必须是对象")
        value = item_value.get("value")
        unit = str(item_value.get("unit") or "")
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
            raise SolverEvidenceError(f"{ap}: 输出 {name} 不是有限数值")
        if not unit:
            raise SolverEvidenceError(f"{ap}: 输出 {name} 缺少单位")
        normalized[str(name)] = dict(item_value)

    identity = payload.get("model_identity") or {}
    if not isinstance(identity, dict):
        raise SolverEvidenceError(f"{ap}: model_identity 必须是对象")
    model_id = str(identity.get("model_id") or "")
    content_digest = str(identity.get("content_digest") or "")
    input_digest = str(identity.get("input_digest") or "")
    if expected_model_id and model_id != expected_model_id:
        raise SolverEvidenceError(f"{ap}: model_id={model_id!r}，当前模型={expected_model_id!r}")
    if expected_digest and content_digest != expected_digest:
        raise SolverEvidenceError(
            f"{ap}: content_digest={content_digest!r}，当前模型={expected_digest!r}"
        )

    residual = payload.get("residual")
    if residual is not None:
        if not isinstance(residual, (int, float)) or isinstance(residual, bool):
            raise SolverEvidenceError(f"{ap}: residual 必须是数值或 null")
        residual = float(residual)
    return SolverEvidence(
        path=ap,
        case_id=case_id,
        check_item_id=item,
        product=product,
        version=version,
        license_mode=license_mode,
        convergence_status=convergence,
        outputs=normalized,
        model_id=model_id,
        content_digest=content_digest,
        input_digest=input_digest,
        residual=residual,
    )
