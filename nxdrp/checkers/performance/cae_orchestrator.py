# -*- coding: utf-8 -*-
"""可恢复的 PERF CAE 编排；默认离线，绝不隐式启动 NX/求解器。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from typing import Protocol

from .cae_bindings import binding_digest, validate_bindings
from .nx_cae_runner import DEFAULT_SOLVE_TIMEOUT_S, run_nx_journal
from .solver_environment import capability_for
from .solver_evidence import load_solver_evidence


STAGES = ("prepare", "setup", "solve", "export")
STAGE_JOURNALS = {
    "setup": ("create_simcenter_case", "setup_simcenter_case"),
    "solve": ("solve_simcenter_case",),
    "export": ("export_simcenter_results",),
}


class OfflineExecutionError(RuntimeError):
    pass


class JournalExecutor(Protocol):
    def execute(
        self,
        journal: str,
        request_path: str,
        response_path: str,
        timeout_s: float,
    ) -> dict:
        ...


class OfflineExecutor:
    def execute(self, journal: str, request_path: str, response_path: str, timeout_s: float) -> dict:
        raise OfflineExecutionError("离线模式不会执行 NX journal 或 CAE 求解")


class NxJournalExecutor:
    def __init__(self, run_journal: str = ""):
        self.run_journal = run_journal

    def execute(self, journal: str, request_path: str, response_path: str, timeout_s: float) -> dict:
        return run_nx_journal(
            journal,
            request_path,
            response_path,
            run_journal=self.run_journal,
            timeout_seconds=int(timeout_s),
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: JSON 顶层必须是对象")
    return payload


def _write(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def payload_digest(payload: dict) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_digest(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _without_digest(payload: dict, key: str) -> dict:
    value = dict(payload)
    value.pop(key, None)
    return value


def _capability_value(capability: dict, *names: str, default=""):
    for name in names:
        value = capability.get(name)
        if value not in (None, ""):
            return value
    solution = capability.get("solution") or {}
    for name in names:
        value = solution.get(name)
        if value not in (None, ""):
            return value
    return default


def _infer_batch_id(case_dir: str, case: dict) -> str:
    """Infer the owning batch when the caller did not pass --batch-id.

    Ingest rejects results whose batch_id is empty or foreign, so prepare must
    recover the workspace identity instead of producing an un-ingestable case.
    """
    direct = str(case.get("batch_id") or "")
    if direct:
        return direct
    root = os.path.abspath(case_dir)
    index_path = os.path.join(os.path.dirname(root), "index.json")
    if not os.path.isfile(index_path):
        return ""
    try:
        index = _load(index_path)
    except (OSError, ValueError):
        return ""
    case_id = str(case.get("case_id") or "")
    for entry in index.get("cases") or []:
        if not isinstance(entry, dict):
            continue
        directory = entry.get("directory") or ""
        if not directory:
            continue
        if os.path.normcase(os.path.abspath(directory)) != os.path.normcase(root):
            continue
        entry_case = str(entry.get("case_id") or "")
        if entry_case and case_id and entry_case != case_id:
            return ""
        return str(index.get("batch_id") or "")
    return ""


def build_setup_manifest(
    case_dir: str,
    nx_release: str,
    *,
    batch_id: str = "",
    require_verified: bool = False,
) -> dict:
    """从已确认工况构造不可歧义的 setup manifest，不执行 NX。"""
    root = os.path.abspath(case_dir)
    case = _load(os.path.join(root, "case.json"))
    binding_path = os.path.join(root, "bindings.json")
    binding = _load(binding_path)
    validation = validate_bindings(binding)
    if not validation["valid"]:
        raise ValueError("绑定尚未确认：" + "；".join(validation["errors"]))
    if binding.get("binding_digest") != binding_digest(binding):
        raise ValueError("binding_digest 不匹配")

    item = case["check_item_id"]
    capability = capability_for(nx_release, item, require_verified=require_verified)
    if capability.get("status") == "not_done" or capability.get("ok") is False:
        details = "；".join(
            str(error.get("message") or error) for error in capability.get("errors") or []
        )
        raise ValueError(f"求解能力不可用：{details or capability}")
    expected_mode = "thermal_with_joule" if item == "PERF-01" else "nonlinear_contact"
    mode = _capability_value(capability, "solution_mode", "mode", default=expected_mode)
    if mode != expected_mode:
        raise ValueError(f"{item} 要求 {expected_mode}，能力映射却为 {mode}")

    required_units = dict(
        case.get("required_output_units")
        or case.get("solver_output_units")
        or case.get("expected_units")
        or {}
    )
    if not required_units:
        raise ValueError("工况没有声明 required_output_units")
    geometry = binding.get("source_geometry") or {}
    case_identity = case.get("model_identity") or {}
    model_identity = {
        "model_id": str(case_identity.get("model_id") or case["case_id"]),
        "content_digest": str(
            case_identity.get("content_digest") or geometry.get("model_digest") or ""
        ),
        "input_digest": str(case_identity.get("input_digest") or payload_digest(case)),
    }
    if not model_identity["content_digest"]:
        raise ValueError("缺少已确认的 source_geometry.model_digest")

    boundary = dict(case.get("boundary_conditions") or {})
    boundary.setdefault("load_values", dict(binding.get("load_values") or {}))
    # Artifact paths are versioned by a stable setup identity so a changed
    # binding or capability can be re-prepared without OUTPUT_EXISTS failures
    # from the previous generation.
    setup_id = payload_digest({
        "case_id": case["case_id"],
        "check_item_id": item,
        "case_digest": payload_digest(case),
        "binding_digest": binding["binding_digest"],
        "capability_digest": payload_digest(capability),
    })[:16]
    artifacts = {
        "working_directory": root,
        "case": os.path.join(root, "case.json"),
        "geometry_request": os.path.join(root, "geometry_request.json"),
        "geometry_response": os.path.join(root, "geometry_response.json"),
        "fem": os.path.join(root, f"{case['case_id']}.{setup_id}.fem"),
        "sim": os.path.join(root, f"{case['case_id']}.{setup_id}.sim"),
        "native_result": os.path.join(root, f"native_result.{setup_id}.json"),
        "solver_result": os.path.join(root, f"solver_result.{setup_id}.json"),
    }
    manifest = {
        "schema_version": "1.0.0",
        "setup_id": setup_id,
        "batch_id": batch_id or _infer_batch_id(root, case),
        "case_id": case["case_id"],
        "check_item_id": item,
        "status": "ready",
        "solver_run_performed": False,
        "model_identity": model_identity,
        "case": case,
        "binding": {
            "path": binding_path,
            "digest": binding["binding_digest"],
            "payload": binding,
        },
        "capability": capability,
        "solution": {
            "mode": mode,
            "nx_release": nx_release,
            "solver": _capability_value(capability, "solver", "solver_name"),
            "analysis": _capability_value(capability, "analysis", "analysis_type"),
            "solution_type": _capability_value(
                capability, "solution_type", "solution_title", "registered_solution_title",
            ),
            "capability_status": str(capability.get("status") or "unverified"),
        },
        "material": dict(binding.get("material") or {}),
        "mesh": dict(case.get("mesh") or case.get("mesh_requirements") or {}),
        "boundary_conditions": boundary,
        "contact_pairs": list(binding.get("contact_pairs") or []),
        "load_steps": list(case.get("load_steps") or case.get("solution_steps") or []),
        "required_output_units": required_units,
        "result_mapping": dict(
            capability.get("native_result_keys")
            or capability.get("result_mapping")
            or {}
        ),
        "artifacts": artifacts,
    }
    manifest["setup_digest"] = payload_digest(_without_digest(manifest, "setup_digest"))
    return manifest


def prepare_case(case_dir: str, nx_release: str, *, batch_id: str = "") -> dict:
    manifest = build_setup_manifest(case_dir, nx_release, batch_id=batch_id)
    root = os.path.abspath(case_dir)
    manifest_path = os.path.join(root, "setup_manifest.json")
    _write(manifest_path, manifest)
    not_done = []
    if str(manifest["capability"].get("status") or "unverified") != "verified":
        not_done.append("CAPABILITY_UNVERIFIED：需在目标 NX 版本完成 journal/API 联调")
    stages = {
        name: {
            "status": "pending",
            "attempt": 0,
            "input_digest": "",
            "artifacts": {},
            "not_done": [],
        }
        for name in STAGES
    }
    stages["prepare"].update({
        "status": "succeeded",
        "attempt": 1,
        "input_digest": manifest["setup_digest"],
        "artifacts": _artifact_records({"setup_manifest": manifest_path}),
        "finished_at": _now(),
        "not_done": not_done,
    })
    stages["setup"]["status"] = "ready"
    state = {
        "schema_version": "1.0.0",
        "batch_id": manifest.get("batch_id", ""),
        "case_id": manifest["case_id"],
        "setup_digest": manifest["setup_digest"],
        "offline": True,
        "status": "ready",
        "solver_run_performed": False,
        "created_at": _now(),
        "updated_at": _now(),
        "stages": stages,
    }
    _write(os.path.join(root, "run_state.json"), state)
    return state


def _artifact_records(paths: dict[str, str]) -> dict:
    records = {}
    for name, path in paths.items():
        if not path:
            continue
        ap = os.path.abspath(path)
        records[name] = {
            "path": ap,
            "sha256": file_digest(ap) if os.path.isfile(ap) else "",
        }
    return records


def _artifacts_valid(records: dict) -> bool:
    for item in records.values():
        path = item.get("path") or ""
        expected = item.get("sha256") or ""
        if not expected or not os.path.isfile(path) or file_digest(path) != expected:
            return False
    return True


def _load_run(root: str) -> tuple[dict, dict]:
    manifest = _load(os.path.join(root, "setup_manifest.json"))
    state = _load(os.path.join(root, "run_state.json"))
    actual_setup_digest = payload_digest(_without_digest(manifest, "setup_digest"))
    if actual_setup_digest != manifest.get("setup_digest"):
        raise ValueError("setup manifest 内容与摘要不一致，请重新 prepare")
    if state.get("setup_digest") != manifest.get("setup_digest"):
        raise ValueError("setup manifest 已变化，请重新 prepare 使下游阶段失效")
    binding_info = manifest.get("binding") or {}
    current_binding = _load(binding_info["path"])
    if binding_digest(current_binding) != binding_info.get("digest"):
        raise ValueError("confirmed binding 已变化，请重新确认并 prepare")
    return manifest, state


def _invalidate_downstream(state: dict, stage: str) -> None:
    """Clear later stage success when the current stage is about to re-run."""
    index = STAGES.index(stage)
    for later in STAGES[index + 1:]:
        record = state["stages"].get(later)
        if not isinstance(record, dict):
            continue
        record.update({
            "status": "pending",
            "attempt": 0,
            "input_digest": "",
            "artifacts": {},
            "not_done": [],
            "error": "",
        })
        for key in ("started_at", "finished_at", "elapsed_s", "response_path"):
            record.pop(key, None)
    if stage == "setup":
        # New containers and setup data invalidate any previous solve.
        state["solver_run_performed"] = False


def build_journal_request(manifest: dict, stage: str, online: bool = False) -> dict:
    binding = manifest["binding"]["payload"]
    capability = manifest["capability"]
    return {
        "schema_version": "1.0.0",
        "case_id": manifest["case_id"],
        "check_item_id": manifest["check_item_id"],
        "kind": "thermal" if manifest["check_item_id"] == "PERF-01" else "structural",
        "online_execution": bool(online),
        "solver_run_performed": False,
        "setup_manifest": manifest,
        "setup": manifest,
        "setup_digest": manifest["setup_digest"],
        "capability": manifest["capability"],
        "binding": binding,
        "bindings": binding,
        "binding_digest": manifest["binding"]["digest"],
        "bindings_path": manifest["binding"]["path"],
        "source_part": (binding.get("source_geometry") or {}).get("source_part", ""),
        "body_tags": (binding.get("source_geometry") or {}).get("body_tags", []),
        "out_dir": manifest["artifacts"]["working_directory"],
        "artifacts": manifest["artifacts"],
        # The create stage must produce a real registered solution; setup then
        # configures that solution instead of relying on a template default.
        "create_solution": stage == "setup",
        "solution_name": _capability_value(
            capability, "solution_title", "solution_name", "registered_solution_title",
        ),
    }


def _response_paths(root: str, stage: str) -> dict[str, str]:
    return {
        journal: os.path.join(root, f"{stage}_{journal}_response.json")
        for journal in STAGE_JOURNALS[stage]
    }


def _validate_stage_response(
    stage: str,
    journal: str,
    response: dict,
    manifest: dict,
    *,
    expected_native_digest: str = "",
) -> None:
    if response.get("case_id") not in (None, "", manifest["case_id"]):
        raise ValueError("journal 响应的 case_id 与 setup 不匹配")
    if journal == "create_simcenter_case" and response.get("state") != "container_created":
        raise ValueError("FEM/SIM 容器未成功创建")
    if journal == "setup_simcenter_case" and response.get("state") != "solver_ready":
        raise ValueError("材料、网格、边界/接触和输出请求尚未全部完成")
    if journal == "solve_simcenter_case":
        native_path = response.get("native_result_path") or ""
        native_digest = response.get("native_result_digest") or ""
        if response.get("state") != "solved" or not native_path:
            raise ValueError("求解响应缺少 solved 状态或原生结果")
        if not os.path.isfile(native_path):
            raise ValueError("求解响应中的原生结果文件不存在")
        if not native_digest or file_digest(native_path) != native_digest:
            raise ValueError("原生结果文件摘要与求解响应不一致")
    if journal == "export_simcenter_results":
        result_path = response.get("solver_result_path") or manifest["artifacts"]["solver_result"]
        if response.get("state") != "exported" or not os.path.isfile(result_path):
            raise ValueError("结果导出响应缺少 exported 状态或 solver_result.json")
        load_solver_evidence(
            result_path,
            expected_item=manifest["check_item_id"],
            expected_case_id=manifest["case_id"],
            expected_batch_id=manifest.get("batch_id", ""),
            expected_model_id=manifest["model_identity"]["model_id"],
            expected_digest=manifest["model_identity"]["content_digest"],
            expected_input_digest=manifest["model_identity"].get("input_digest", ""),
            expected_setup_digest=manifest["setup_digest"],
            expected_binding_digest=manifest["binding"]["digest"],
            expected_native_result_digest=expected_native_digest,
            required_outputs=manifest["required_output_units"],
            require_converged=True,
            require_native_evidence=True,
        )


def run_stage(
    case_dir: str,
    stage: str,
    *,
    online: bool = False,
    executor: JournalExecutor | None = None,
    timeout_s: float | None = None,
) -> dict:
    """运行一个阶段；默认 offline executor 永远不会启动子进程。"""
    if stage not in STAGE_JOURNALS:
        raise ValueError("stage 必须为 setup/solve/export")
    root = os.path.abspath(case_dir)
    manifest, state = _load_run(root)
    index = STAGES.index(stage)
    previous = state["stages"][STAGES[index - 1]]
    if previous.get("status") != "succeeded":
        raise ValueError(f"前序阶段 {STAGES[index - 1]} 尚未成功")

    request = build_journal_request(manifest, stage, online)
    # A solve from an older generation is not an input to setup; keeping it out
    # of the setup request digest lets an unchanged re-prepare stay a no-op.
    request["solver_run_performed"] = (
        False if stage == "setup" else bool(state.get("solver_run_performed"))
    )
    if stage != "setup":
        prior_name = STAGES[index - 1]
        prior_response = os.path.join(root, f"{prior_name}_response.json")
        request["previous_response_path"] = prior_response
        if os.path.isfile(prior_response):
            previous_payload = _load(prior_response)
            request["previous_response"] = previous_payload
            if stage == "export":
                request["native_result_path"] = previous_payload.get("native_result_path", "")
                request["native_result_digest"] = previous_payload.get("native_result_digest", "")
    input_digest = payload_digest(request)
    record = state["stages"][stage]
    if (
        record.get("status") == "succeeded"
        and record.get("input_digest") == input_digest
        and _artifacts_valid(record.get("artifacts") or {})
    ):
        state["status"] = "succeeded" if stage == "export" else state["status"]
        return state

    # Re-running a stage must never leave an older downstream success behind,
    # including when this attempt is blocked offline or fails.
    _invalidate_downstream(state, stage)
    state["offline"] = not online
    state["updated_at"] = _now()
    if not online:
        record.update({
            "status": "blocked",
            "error": "OFFLINE_EXECUTION_DISABLED：需要显式 --online；本轮不启动 NX/CAE",
            "input_digest": input_digest,
            "not_done": ["explicit_online_execution"],
        })
        state["status"] = "blocked"
        _write(os.path.join(root, "run_state.json"), state)
        return state
    if str(manifest["capability"].get("status") or "unverified") != "verified":
        record.update({
            "status": "not_done",
            "error": "CAPABILITY_UNVERIFIED：当前 NX 版本能力尚未联调确认",
            "input_digest": input_digest,
            "not_done": ["CAPABILITY_UNVERIFIED"],
        })
        state["status"] = "not_done"
        _write(os.path.join(root, "run_state.json"), state)
        return state

    executor = executor or NxJournalExecutor()
    paths = _response_paths(root, stage)
    request_path = os.path.join(root, f"{stage}_request.json")
    _write(request_path, request)
    record.update({
        "status": "running",
        "attempt": int(record.get("attempt") or 0) + 1,
        "input_digest": input_digest,
        "started_at": _now(),
        "error": "",
        "not_done": [],
    })
    state["status"] = "running"
    _write(os.path.join(root, "run_state.json"), state)
    started = time.perf_counter()
    try:
        responses = {}
        for journal, response_path in paths.items():
            response = executor.execute(
                journal,
                request_path,
                response_path,
                timeout_s or (DEFAULT_SOLVE_TIMEOUT_S if stage == "solve" else 900.0),
            )
            _validate_stage_response(
                stage,
                journal,
                response,
                manifest,
                expected_native_digest=request.get("native_result_digest", ""),
            )
            responses[journal] = response
            if journal == "create_simcenter_case":
                # Hand the verified container identity to the setup journal.
                request["container_response"] = response
                _write(request_path, request)
            if journal == "solve_simcenter_case":
                state["solver_run_performed"] = True
                request["solver_run_performed"] = True
                request["native_result_path"] = response["native_result_path"]
                request["native_result_digest"] = response.get("native_result_digest", "")
                request["solve_response"] = response
                _write(request_path, request)
        final_response_path = os.path.join(root, f"{stage}_response.json")
        _write(final_response_path, responses[STAGE_JOURNALS[stage][-1]])
        artifacts = {"request": request_path, "response": final_response_path}
        artifacts.update({f"{name}_response": path for name, path in paths.items()})
        if stage == "solve":
            native = responses["solve_simcenter_case"]["native_result_path"]
            artifacts["native_result"] = native
        if stage == "export":
            artifacts["solver_result"] = (
                responses["export_simcenter_results"].get("solver_result_path")
                or manifest["artifacts"]["solver_result"]
            )
        record.update({
            "status": "succeeded",
            "artifacts": _artifact_records(artifacts),
            "response_path": final_response_path,
            "elapsed_s": round(time.perf_counter() - started, 3),
            "finished_at": _now(),
        })
        next_index = index + 1
        if next_index < len(STAGES):
            state["stages"][STAGES[next_index]]["status"] = "ready"
        state["status"] = "succeeded" if stage == "export" else "ready"
    except Exception as exc:
        record.update({
            "status": "failed",
            "error": str(exc),
            "elapsed_s": round(time.perf_counter() - started, 3),
            "finished_at": _now(),
            "not_done": [stage],
        })
        state["status"] = "failed"
        if stage == "solve":
            state["solver_run_performed"] = False
    state["updated_at"] = _now()
    _write(os.path.join(root, "run_state.json"), state)
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description="PERF CAE 离线准备与显式在线编排")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--case-dir", required=True)
    prepare.add_argument("--nx-release", required=True)
    prepare.add_argument("--batch-id", default="")
    run = sub.add_parser("run")
    run.add_argument("--case-dir", required=True)
    run.add_argument("--stage", required=True, choices=tuple(STAGE_JOURNALS))
    run.add_argument("--online", action="store_true")
    run.add_argument("--run-journal", default="")
    run.add_argument("--timeout", type=float)
    status = sub.add_parser("status")
    status.add_argument("--case-dir", required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        payload = prepare_case(args.case_dir, args.nx_release, batch_id=args.batch_id)
    elif args.command == "run":
        executor = NxJournalExecutor(args.run_journal) if args.online else OfflineExecutor()
        payload = run_stage(
            args.case_dir,
            args.stage,
            online=args.online,
            executor=executor,
            timeout_s=args.timeout,
        )
    else:
        payload = _load(os.path.join(os.path.abspath(args.case_dir), "run_state.json"))
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
