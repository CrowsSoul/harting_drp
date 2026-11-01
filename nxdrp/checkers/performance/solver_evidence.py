# -*- coding: utf-8 -*-
"""NX / Simcenter / FloEFD 求解结果的可审计读取器。

本地公式只用于筛查。只有通过身份、单位、收敛和授权校验的真实求解结果，
才能作为 ``cae_solver`` 证据；smoke 数据永远不能进入生产认证。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from typing import Any


PRODUCTION_LICENSE_MODES = frozenset({
    "authorized", "commercial", "floating", "node_locked",
})
EVIDENCE_SOURCES = frozenset({"cae_solver", "cae_smoke", "smoke_fixture"})


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
    batch_id: str = ""
    setup_digest: str = ""
    binding_digest: str = ""
    capability_id: str = ""
    native_result_path: str = ""
    native_result_digest: str = ""
    evidence_source: str = "cae_solver"

    @property
    def is_converged(self) -> bool:
        return self.convergence_status == "converged"

    @property
    def certification_eligible(self) -> bool:
        return (
            self.is_converged
            and self.evidence_source == "cae_solver"
            and self.license_mode in PRODUCTION_LICENSE_MODES
        )

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
            "source": self.evidence_source,
            "path": self.path,
            "batch_id": self.batch_id,
            "case_id": self.case_id,
            "product": self.product,
            "version": self.version,
            "license_mode": self.license_mode,
            "convergence_status": self.convergence_status,
            "model_id": self.model_id,
            "content_digest": self.content_digest,
            "input_digest": self.input_digest,
            "setup_digest": self.setup_digest,
            "binding_digest": self.binding_digest,
            "capability_id": self.capability_id,
            "native_result_path": self.native_result_path,
            "native_result_digest": self.native_result_digest,
            "residual": self.residual,
            "certification_eligible": self.certification_eligible,
        }


def _load_payload(path: str) -> dict:
    # Evidence files may be replaced rapidly by an exporter. Caching by path/mtime
    # can validate stale content on filesystems with coarse timestamp resolution.
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _expected(actual: str, expected: str, label: str, path: str) -> None:
    if expected and actual != expected:
        raise SolverEvidenceError(f"{path}: {label}={actual!r}，预期为 {expected!r}")


def load_solver_evidence(
    path: str,
    *,
    expected_item: str | None = None,
    expected_case_id: str = "",
    expected_batch_id: str = "",
    expected_model_id: str = "",
    expected_digest: str = "",
    expected_input_digest: str = "",
    expected_setup_digest: str = "",
    expected_binding_digest: str = "",
    expected_capability_id: str = "",
    expected_native_result_digest: str = "",
    required_outputs: dict[str, str] | None = None,
    require_converged: bool = True,
    require_authorized: bool = False,
    require_native_evidence: bool = False,
) -> SolverEvidence:
    ap = os.path.abspath(path)
    if not os.path.isfile(ap):
        raise SolverEvidenceError(f"求解结果文件不存在：{ap}")
    payload = _load_payload(ap)
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0.0":
        raise SolverEvidenceError(f"{ap}: schema_version 必须为 1.0.0")
    case_id = str(payload.get("case_id") or "")
    item = str(payload.get("check_item_id") or "")
    if not case_id or item not in ("PERF-01", "PERF-02"):
        raise SolverEvidenceError(f"{ap}: case_id/check_item_id 无效")
    if expected_item and item != expected_item:
        raise SolverEvidenceError(f"{ap}: 结果所属 {item}，当前检查要求 {expected_item}")
    _expected(case_id, expected_case_id, "case_id", ap)
    batch_id = str(payload.get("batch_id") or "")
    _expected(batch_id, expected_batch_id, "batch_id", ap)

    solver = payload.get("solver") or {}
    if not isinstance(solver, dict):
        raise SolverEvidenceError(f"{ap}: solver 必须是对象")
    product = str(solver.get("product") or "")
    version = str(solver.get("version") or "")
    license_mode = str(solver.get("license_mode") or "").strip().casefold().replace("-", "_")
    if not _nonempty(product) or not _nonempty(version):
        raise SolverEvidenceError(f"{ap}: solver.product/version 不能为空")
    if require_authorized and license_mode not in PRODUCTION_LICENSE_MODES:
        raise SolverEvidenceError(
            f"{ap}: solver.license_mode={license_mode!r} 不具备生产认证资格"
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
    _expected(model_id, expected_model_id, "model_id", ap)
    _expected(content_digest, expected_digest, "content_digest", ap)
    _expected(input_digest, expected_input_digest, "input_digest", ap)

    setup_digest = str(payload.get("setup_digest") or "")
    binding_digest = str(payload.get("binding_digest") or "")
    capability_id = str(payload.get("capability_id") or "")
    run = payload.get("run") or {}
    if not isinstance(run, dict):
        raise SolverEvidenceError(f"{ap}: run 必须是对象")
    native_path = str(run.get("native_result_path") or run.get("result_file") or "")
    native_digest = str(run.get("native_result_digest") or "")
    _expected(setup_digest, expected_setup_digest, "setup_digest", ap)
    _expected(binding_digest, expected_binding_digest, "binding_digest", ap)
    _expected(capability_id, expected_capability_id, "capability_id", ap)
    _expected(native_digest, expected_native_result_digest, "native_result_digest", ap)

    residual = payload.get("residual")
    if residual is not None:
        if (
            not isinstance(residual, (int, float))
            or isinstance(residual, bool)
            or not math.isfinite(float(residual))
        ):
            raise SolverEvidenceError(f"{ap}: residual 必须是有限数值或 null")
        residual = float(residual)

    if require_native_evidence:
        if residual is None:
            raise SolverEvidenceError(f"{ap}: 受信任结果必须包含有限收敛残差")
        if not native_path or not native_digest:
            raise SolverEvidenceError(f"{ap}: 缺少原生求解结果路径或摘要")
        native_file = os.path.abspath(native_path)
        if not os.path.isfile(native_file):
            raise SolverEvidenceError(f"{ap}: 原生求解结果不存在：{native_file}")
        digest = hashlib.sha256()
        with open(native_file, "rb") as fh:
            for block in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != native_digest:
            raise SolverEvidenceError(f"{ap}: 原生求解结果摘要与文件内容不一致")

    evidence_source = str(payload.get("evidence_source") or "cae_solver")
    if evidence_source not in EVIDENCE_SOURCES:
        raise SolverEvidenceError(f"{ap}: evidence_source={evidence_source!r} 无效")
    if license_mode == "unverified" and evidence_source == "cae_solver":
        evidence_source = "cae_smoke"

    evidence = SolverEvidence(
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
        batch_id=batch_id,
        setup_digest=setup_digest,
        binding_digest=binding_digest,
        capability_id=capability_id,
        native_result_path=native_path,
        native_result_digest=native_digest,
        evidence_source=evidence_source,
    )
    for name, unit in (required_outputs or {}).items():
        evidence.value(name, unit)
    return evidence
