# -*- coding: utf-8 -*-
"""Exact-release PERF solver capabilities and read-only environment detection.

This module never starts NX, Nastran, FloEFD, or any other process.  Catalog
entries describe workflow inputs only; ``unverified`` entries and null native
result keys are intentional and must not be treated as execution support.
"""

from __future__ import annotations

import copy
import json
import os
from typing import Iterable

from ...adapters.nx_batch import detect_run_journal
from .rule_engine import PROJECT_ROOT


CAPABILITIES_PATH = os.path.join(
    PROJECT_ROOT, "rules", "perf_solver_capabilities_v1.json"
)
SUPPORTED_RELEASE = "NX 2606.3002"
SUPPORTED_ITEMS = ("PERF-01", "PERF-02")


def load_capabilities(path: str = CAPABILITIES_PATH) -> dict:
    """Load and minimally validate the exact-release capability catalog."""
    with open(path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if payload.get("schema_version") != "1.0.0":
        raise ValueError("PERF solver capabilities schema_version 必须为 1.0.0")
    if payload.get("release_matching") != "exact":
        raise ValueError("PERF solver capabilities 必须采用 exact release matching")
    releases = payload.get("releases")
    if not isinstance(releases, dict) or not releases:
        raise ValueError("PERF solver capabilities.releases 不能为空")
    for release, release_data in releases.items():
        if release_data.get("release") != release:
            raise ValueError(f"能力库 release key 与内容不一致：{release}")
        items = release_data.get("items")
        if not isinstance(items, dict):
            raise ValueError(f"能力库 {release}.items 必须是对象")
        for item, capability in items.items():
            if capability.get("check_item_id") != item:
                raise ValueError(f"能力库 {release}/{item} 的 check_item_id 不一致")
            modes = capability.get("supported_modes")
            if not isinstance(modes, list) or capability.get("mode") not in modes:
                raise ValueError(f"能力库 {release}/{item} 的 mode 配置无效")
            if not isinstance(capability.get("native_result_mapping"), dict):
                raise ValueError(f"能力库 {release}/{item} 缺少 native_result_mapping")
    return payload


def _error(code: str, message: str, action: str, **details) -> dict:
    return {
        "code": code,
        "message": message,
        "action": action,
        **details,
    }


def _not_done(
    release: str,
    item: str,
    errors: list[dict],
    *,
    mode: str | None = None,
) -> dict:
    return {
        "ok": False,
        "status": "not_done",
        "release": release,
        "check_item_id": item,
        "mode": mode,
        "verified": False,
        "execution_ready": False,
        "errors": errors,
        "not_done": [dict(error) for error in errors],
    }


def capability_for(
    release: str,
    item: str,
    require_verified: bool = False,
) -> dict:
    """Return an exact release/item capability or a structured ``not_done``.

    No release parsing, prefix matching, nearest-version selection, or item
    aliasing is performed.  Callers can therefore safely pass the result to
    :func:`validate_capability_mode` without a second lookup.
    """
    release_key = str(release or "").strip()
    item_key = str(item or "").strip()
    catalog = load_capabilities()
    release_data = (catalog.get("releases") or {}).get(release_key)
    if release_data is None:
        return _not_done(
            release_key,
            item_key,
            [_error(
                "unsupported_release",
                f"没有 NX release {release_key!r} 的精确能力映射",
                "仅使用能力库列出的完整 release；核实版本后补充并验证该 release 的映射，禁止使用邻近版本。",
                requested_release=release_key,
                supported_releases=sorted(catalog.get("releases") or {}),
            )],
        )
    capability = (release_data.get("items") or {}).get(item_key)
    if capability is None:
        return _not_done(
            release_key,
            item_key,
            [_error(
                "unsupported_item",
                f"{release_key} 没有 {item_key!r} 的能力映射",
                "仅为明确映射的 PERF 项生成求解请求；不要复用其他检查项的模板或结果键。",
                supported_items=sorted(release_data.get("items") or {}),
            )],
        )
    result = copy.deepcopy(capability)
    result.update({
        "ok": True,
        "release": release_key,
        "catalog_id": catalog.get("catalog_id", ""),
        "catalog_provenance": copy.deepcopy(catalog.get("provenance") or {}),
        # The orchestrator consumes this alias; values intentionally remain null
        # until native keys are verified for this exact release.
        "result_mapping": copy.deepcopy(result.get("native_result_mapping") or {}),
    })
    if require_verified and not result.get("verified", False):
        return _not_done(
            release_key,
            item_key,
            [_error(
                "capability_unverified",
                f"{release_key}/{item_key} 的能力尚未验证",
                "先在对应精确 release 上完成模板、求解模式、单位和结果映射验证；当前只能离线准备，不能执行。",
            )],
            mode=result.get("mode"),
        )
    return result


def validate_capability_mode(
    capability: dict,
    mode: str,
    output_keys: Iterable[str] | None = None,
    *,
    require_verified: bool = False,
    for_execution: bool = False,
) -> dict:
    """Validate an exact mode and contract output keys, failing closed.

    ``for_execution=True`` additionally requires a verified capability and a
    non-empty native key for every requested output.  Unknown contract output
    keys are errors; known keys with null native mappings are ``not_done``.
    """
    if not isinstance(capability, dict):
        return _not_done(
            "",
            "",
            [_error(
                "invalid_capability",
                "capability 必须是 capability_for 返回的对象",
                "先调用 capability_for(release, item)，不要手工构造求解能力。",
            )],
            mode=str(mode or ""),
        )
    if capability.get("status") == "not_done" or capability.get("ok") is False:
        result = copy.deepcopy(capability)
        result["valid"] = False
        result["execution_ready"] = False
        return result

    release = str(capability.get("release") or "")
    item = str(capability.get("check_item_id") or "")
    requested_mode = str(mode or "")
    errors: list[dict] = []
    not_done: list[dict] = []
    supported_modes = list(capability.get("supported_modes") or [])
    if requested_mode not in supported_modes:
        errors.append(_error(
            "unsupported_mode",
            f"{release}/{item} 不支持求解模式 {requested_mode!r}",
            "使用 supported_modes 中的精确模式；不要按相似名称或邻近 SOL 编号回退。",
            requested_mode=requested_mode,
            supported_modes=supported_modes,
        ))

    if (require_verified or for_execution) and not capability.get("verified", False):
        not_done.append(_error(
            "capability_unverified",
            f"{release}/{item} 的能力尚未验证",
            "完成精确 release 的端到端验证后再执行；当前仅允许离线 handoff。",
        ))

    mapping = capability.get("native_result_mapping") or {}
    if isinstance(output_keys, str):
        requested_outputs = [output_keys]
    elif output_keys is None:
        requested_outputs = list(mapping) if for_execution else []
    else:
        requested_outputs = [str(key) for key in output_keys]

    for output_key in requested_outputs:
        if output_key not in mapping:
            errors.append(_error(
                "unknown_output_key",
                f"{release}/{item} 没有合同输出键 {output_key!r} 的映射",
                "使用 perf_solver_result 合同和能力库中已声明的输出键；新增键前必须核实其含义与单位。",
                output_key=output_key,
                known_output_keys=sorted(mapping),
            ))
        elif not mapping.get(output_key):
            not_done.append(_error(
                "native_output_key_unverified",
                f"输出 {output_key!r} 的 native result key 尚未建立",
                "由工程师在精确 release 中确认 native key、位置和单位后更新能力库；禁止猜测名称。",
                output_key=output_key,
                native_key=None,
            ))

    execution_blocked = for_execution and bool(errors or not_done)
    return {
        "ok": not errors,
        "valid": not errors,
        "status": "not_done" if errors or execution_blocked else capability.get("status", "unverified"),
        "release": release,
        "check_item_id": item,
        "mode": requested_mode,
        "verified": bool(capability.get("verified", False)),
        "execution_ready": bool(for_execution and not errors and not not_done),
        "output_keys": requested_outputs,
        "errors": errors,
        "not_done": not_done,
    }


def _executable_summary(path: str | None, source: str, executable: str) -> dict:
    normalized = os.path.abspath(path) if path else None
    exists = bool(normalized and os.path.isfile(normalized))
    return {
        "executable": executable,
        "path": normalized,
        "exists": exists,
        "source": source,
        "license_mode": "unverified",
        "license_verified": False,
        "authorized": False,
        "authorization_status": "unverified",
    }


def _first_explicit(*values) -> tuple[str | None, str]:
    for value, source in values:
        if value:
            return os.fspath(value), source
    return None, "not_detected"


def _find_under_base(base: str | None, executable: str) -> str | None:
    """Find an exact executable basename below UGII_BASE_DIR, read-only."""
    if not base or not os.path.isdir(base):
        return None
    target = executable.casefold()
    for root, dirs, files in os.walk(base):
        dirs.sort(key=str.casefold)
        for name in sorted(files, key=str.casefold):
            if name.casefold() == target:
                return os.path.join(root, name)
    return None


def detect_solver_environment(
    *,
    nx_release: str | None = None,
    ugii_base_dir: str | None = None,
    run_journal: str | None = None,
    nastran_analysis: str | None = None,
    floefd_solver: str | None = None,
    environ: dict | None = None,
) -> dict:
    """Detect local paths without invoking processes or checking out licenses.

    Release identity is accepted only from an explicit argument or
    ``NXDRP_NX_RELEASE``; it is never guessed from an installation path.
    Executable-specific environment variables are ``NXDRP_RUN_JOURNAL``,
    ``NXDRP_NASTRAN_ANALYSIS`` and ``NXDRP_FLOEFD_SOLVER``.
    """
    env = os.environ if environ is None else environ
    if nx_release:
        release = str(nx_release).strip()
        release_source = "explicit"
    elif env.get("NXDRP_NX_RELEASE"):
        release = str(env["NXDRP_NX_RELEASE"]).strip()
        release_source = "env:NXDRP_NX_RELEASE"
    else:
        release = None
        release_source = "not_detected"

    base = ugii_base_dir or env.get("UGII_BASE_DIR") or None
    base_source = (
        "explicit" if ugii_base_dir
        else "env:UGII_BASE_DIR" if env.get("UGII_BASE_DIR")
        else "not_detected"
    )

    run_path, run_source = _first_explicit(
        (run_journal, "explicit"),
        (env.get("NXDRP_RUN_JOURNAL"), "env:NXDRP_RUN_JOURNAL"),
    )
    if not run_path and environ is None:
        detected = detect_run_journal()
        if detected:
            run_path = detected
            run_source = "detect_run_journal"
    if not run_path and base:
        candidate = os.path.join(base, "NXBIN", "run_journal.exe")
        if os.path.isfile(candidate):
            run_path = candidate
            run_source = "UGII_BASE_DIR"
    if not base and run_path:
        base = os.path.dirname(os.path.dirname(os.path.abspath(run_path)))
        base_source = "derived_from_run_journal"
    base = os.path.abspath(base) if base else None

    nastran_path, nastran_source = _first_explicit(
        (nastran_analysis, "explicit"),
        (env.get("NXDRP_NASTRAN_ANALYSIS"), "env:NXDRP_NASTRAN_ANALYSIS"),
        (env.get("NXDRP_NASTRAN_PATH"), "env:NXDRP_NASTRAN_PATH"),
    )
    if not nastran_path:
        nastran_path = _find_under_base(base, "analysis.exe")
        nastran_source = "UGII_BASE_DIR" if nastran_path else "not_detected"

    floefd_path, floefd_source = _first_explicit(
        (floefd_solver, "explicit"),
        (env.get("NXDRP_FLOEFD_SOLVER"), "env:NXDRP_FLOEFD_SOLVER"),
        (env.get("NXDRP_FLOEFD_PATH"), "env:NXDRP_FLOEFD_PATH"),
    )
    if not floefd_path:
        floefd_path = _find_under_base(base, "efdsolver.exe")
        floefd_source = "UGII_BASE_DIR" if floefd_path else "not_detected"

    run_summary = _executable_summary(run_path, run_source, "run_journal.exe")
    nastran_summary = _executable_summary(nastran_path, nastran_source, "analysis.exe")
    floefd_summary = _executable_summary(floefd_path, floefd_source, "efdsolver.exe")
    missing = [
        summary["executable"]
        for summary in (run_summary, nastran_summary, floefd_summary)
        if not summary["exists"]
    ]
    not_done = [
        _error(
            "executable_not_found",
            f"未检测到 {name}",
            "设置 UGII_BASE_DIR 或对应的 NXDRP_* 显式路径；文件存在仍不代表许可证已授权。",
            executable=name,
        )
        for name in missing
    ]
    if not release:
        not_done.append(_error(
            "nx_release_not_detected",
            "没有可靠的 NX release 标识",
            "通过 nx_release 参数或 NXDRP_NX_RELEASE 提供完整 release（例如 NX 2606.3002）。",
        ))
    not_done.append(_error(
        "license_unverified",
        "只检测了文件存在性，未验证任何许可证或授权",
        "由授权工程师在目标环境确认 license_mode；不要把 exists=true 当作 authorized=true。",
    ))
    return {
        "schema_version": "1.0.0",
        "status": "unverified",
        "detection_status": "complete" if release and not missing else "partial",
        "read_only": True,
        "solver_run_performed": False,
        "nx_release": release,
        "nx_release_source": release_source,
        "ugii_base_dir": base,
        "ugii_base_dir_source": base_source,
        "license_mode": "unverified",
        "license_verified": False,
        "authorized": False,
        "run_journal": run_summary,
        "nastran": nastran_summary,
        "floefd": floefd_summary,
        "not_done": not_done,
    }


# A concise alias for orchestrators that already provide solver context.
detect_environment = detect_solver_environment


__all__ = [
    "CAPABILITIES_PATH",
    "SUPPORTED_RELEASE",
    "SUPPORTED_ITEMS",
    "capability_for",
    "detect_environment",
    "detect_solver_environment",
    "load_capabilities",
    "validate_capability_mode",
]
