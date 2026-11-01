# -*- coding: utf-8 -*-
"""Run a native Simcenter solve only from a verified solver_ready response."""

from __future__ import annotations

import os
import traceback

try:
    from .create_simcenter_case import (
        AUTHORIZED_LICENSE_MODES,
        JournalError,
        _required_capability_text,
        error_response,
        file_digest,
        identity_fields,
        journal_main,
        require_online_execution,
        verify_setup_manifest,
    )
except ImportError:  # run_journal executes this file with its directory on sys.path
    from create_simcenter_case import (
        AUTHORIZED_LICENSE_MODES,
        JournalError,
        _required_capability_text,
        error_response,
        file_digest,
        identity_fields,
        journal_main,
        require_online_execution,
        verify_setup_manifest,
    )


def _select_setup_response(identity: dict, request: dict) -> dict:
    candidates = []
    if "setup_response" in request:
        candidates.append(request["setup_response"])
    if "setup_response" in identity["manifest"]:
        candidates.append(identity["manifest"]["setup_response"])
    if "previous_response" in request:
        candidates.append(request["previous_response"])
    if len(candidates) != 1 or not isinstance(candidates[0], dict):
        raise JournalError(
            "PREREQUISITE_NOT_MET", "Exactly one embedded solver_ready response is required"
        )
    response = candidates[0]
    if response.get("ok") is not True or response.get("state") != "solver_ready":
        raise JournalError("PREREQUISITE_NOT_MET", "Setup state is not solver_ready")
    if response.get("output_requests_set") is not True:
        raise JournalError("PREREQUISITE_NOT_MET", "Native output requests are not confirmed")
    for field, value in identity_fields(identity).items():
        if response.get(field) != value:
            raise JournalError("PREREQUISITE_NOT_MET", "Setup response %s differs" % field)
    builders = response.get("builders")
    if not isinstance(builders, dict) or not builders:
        raise JournalError("PREREQUISITE_NOT_MET", "Committed setup builders are not recorded")
    for name, result in builders.items():
        if not isinstance(result, dict) or result.get("committed") is not True:
            raise JournalError("PREREQUISITE_NOT_MET", "Setup builder %s did not commit" % name)
    return response


def solve_with_simcenter(context: dict, payload: dict) -> dict:
    registry = context.get("solver_registry")
    solver = registry.get("simcenter_solve") if isinstance(registry, dict) else None
    if not callable(solver):
        raise JournalError(
            "NX_API_UNSUPPORTED",
            "No verified NX 2606 Simcenter solve implementation is registered",
            details={"required_action": "register the actual NX Open solve call; no synthetic result is allowed"},
            not_done=["native Simcenter solve"],
        )
    result = solver(context, payload)
    if not isinstance(result, dict) or result.get("completed") is not True:
        raise JournalError(
            "SOLVE_FAILED", "The native solve did not return an explicit completed result"
        )
    return result


def _native_artifact(result: dict, name: str) -> dict:
    path = result.get(name + "_path")
    if not isinstance(path, str) or not path:
        raise JournalError("SOLVE_FAILED", "Native solve did not return " + name + "_path")
    path = os.path.abspath(path)
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        raise JournalError("SOLVE_FAILED", "Native artifact is missing or empty: " + path)
    return {"path": path, "sha256": file_digest(path)}


def _validate_run_metadata(metadata: dict, identity: dict, artifacts: dict) -> None:
    if not isinstance(metadata, dict):
        raise JournalError("RUN_METADATA_INVALID", "Native run_metadata is required")
    for field in (
        "run_id",
        "native_api",
        "started_at",
        "finished_at",
        "input_digest",
        "solution_title",
    ):
        if not isinstance(metadata.get(field), str) or not metadata[field].strip():
            raise JournalError("RUN_METADATA_INVALID", "run_metadata.%s is required" % field)
    if metadata["solution_title"] != _required_capability_text(
        identity["capability"], "solution_title"
    ):
        raise JournalError("RUN_METADATA_INVALID", "Native solution title does not match capability")
    for field, value in identity_fields(identity).items():
        if metadata.get(field) != value:
            raise JournalError("RUN_METADATA_INVALID", "Native run %s does not match" % field)
    solver = metadata.get("solver")
    if not isinstance(solver, dict):
        raise JournalError("RUN_METADATA_INVALID", "Native solver metadata is required")
    if solver.get("product") != _required_capability_text(identity["capability"], "solver"):
        raise JournalError("RUN_METADATA_INVALID", "Native solver product does not match capability")
    if not isinstance(solver.get("version"), str) or not solver["version"]:
        raise JournalError("RUN_METADATA_INVALID", "Native solver version is required")
    if solver.get("license_mode") not in AUTHORIZED_LICENSE_MODES:
        raise JournalError("RUN_METADATA_INVALID", "Native solver license is not authorized")
    model_identity = metadata.get("model_identity")
    if not isinstance(model_identity, dict):
        raise JournalError("RUN_METADATA_INVALID", "Native model identity is required")
    if model_identity.get("content_digest") != identity["binding"]["source_geometry"]["model_digest"]:
        raise JournalError("RUN_METADATA_INVALID", "Native model content digest does not match binding")
    if not isinstance(model_identity.get("model_id"), str) or not model_identity["model_id"]:
        raise JournalError("RUN_METADATA_INVALID", "Native model_id is required")
    expected_identity = identity["setup"].get("model_identity")
    if isinstance(expected_identity, dict):
        for field in ("model_id", "content_digest", "input_digest"):
            expected_value = expected_identity.get(field)
            if expected_value and model_identity.get(field) != expected_value:
                raise JournalError(
                    "RUN_METADATA_INVALID", "Native model %s does not match setup" % field
                )
    if model_identity.get("input_digest") != metadata["input_digest"]:
        raise JournalError("RUN_METADATA_INVALID", "Native model input digest is inconsistent")
    if metadata.get("case_file") != artifacts["native_deck"]["path"]:
        raise JournalError("RUN_METADATA_INVALID", "Native case_file does not match the deck")
    if metadata.get("result_file") != artifacts["native_result"]["path"]:
        raise JournalError("RUN_METADATA_INVALID", "Native result_file does not match the result")


def _validate_steps(result: dict, check_item_id: str) -> list:
    steps = result.get("step_statuses")
    if not isinstance(steps, list) or not steps:
        raise JournalError("SOLVE_FAILED", "Native per-step statuses are required")
    normalized = []
    for step in steps:
        if not isinstance(step, dict) or isinstance(step.get("step"), bool):
            raise JournalError("SOLVE_FAILED", "Invalid native step status")
        number = step.get("step")
        if not isinstance(number, int) or step.get("status") != "converged":
            raise JournalError(
                "SOLVE_NOT_CONVERGED", "Every native load step must be converged"
            )
        normalized.append({"step": number, "status": "converged"})
    numbers = [step["step"] for step in normalized]
    if len(set(numbers)) != len(numbers):
        raise JournalError("SOLVE_FAILED", "Duplicate native load steps")
    if check_item_id == "PERF-02" and numbers != [1, 2, 3]:
        raise JournalError(
            "SOLVE_NOT_CONVERGED", "PERF-02 requires converged steps 1, 2 and 3 in order"
        )
    return normalized


def execute(request: dict, *, nxopen=None, solver_registry=None) -> dict:
    identity = verify_setup_manifest(request, require_confirmed_binding=True)
    setup_response = _select_setup_response(identity, request)
    require_online_execution(request)
    if nxopen is None:
        try:
            import NXOpen as nxopen_module
        except ImportError as exc:
            raise JournalError(
                "NX_API_UNSUPPORTED", "Solve requires NXOpen inside a licensed NX process"
            ) from exc
        nxopen = nxopen_module
    context = {
        "nxopen": nxopen,
        "session": nxopen.Session.GetSession(),
        "solver_registry": solver_registry,
        "identity": identity,
        "setup_response": setup_response,
    }
    result = solve_with_simcenter(
        context,
        {
            "case": identity["case"],
            "setup": identity["setup"],
            "binding": identity["binding"],
            "capability": identity["capability"],
            "setup_response": setup_response,
        },
    )
    artifacts = {
        name: _native_artifact(result, name)
        for name in ("native_deck", "native_result", "native_log")
    }
    metadata = result.get("run_metadata")
    _validate_run_metadata(metadata, identity, artifacts)
    steps = _validate_steps(result, identity["check_item_id"])
    if result.get("convergence_status") != "converged":
        raise JournalError("SOLVE_NOT_CONVERGED", "Native solution is not converged")
    payload = {
        "ok": True,
        "state": "solved",
        **identity_fields(identity),
        "native_deck": artifacts["native_deck"],
        "native_result": artifacts["native_result"],
        "native_log": artifacts["native_log"],
        "native_deck_path": artifacts["native_deck"]["path"],
        "native_result_path": artifacts["native_result"]["path"],
        "native_log_path": artifacts["native_log"]["path"],
        "native_deck_digest": artifacts["native_deck"]["sha256"],
        "native_result_digest": artifacts["native_result"]["sha256"],
        "native_log_digest": artifacts["native_log"]["sha256"],
        "run_metadata": metadata,
        "step_statuses": steps,
        "convergence_status": "converged",
        "not_done": ["native result extraction", "validated result export"],
    }
    extraction_path = result.get("native_extraction_path")
    if extraction_path is not None:
        if not isinstance(extraction_path, str) or not extraction_path:
            raise JournalError("SOLVE_FAILED", "native_extraction_path is invalid")
        extraction_path = os.path.abspath(extraction_path)
        if not os.path.isfile(extraction_path) or os.path.getsize(extraction_path) == 0:
            raise JournalError("SOLVE_FAILED", "Native extraction artifact is missing")
        payload["native_extraction_path"] = extraction_path
        payload["native_extraction_sha256"] = file_digest(extraction_path)
    return payload


def run(request: dict, *, nxopen=None, solver_registry=None) -> dict:
    try:
        return execute(request, nxopen=nxopen, solver_registry=solver_registry)
    except JournalError as exc:
        return exc.response()
    except Exception as exc:
        return error_response(
            "NX_API_ERROR",
            "Native solve failed: %r" % exc,
            details={"traceback": traceback.format_exc()[-2000:]},
            not_done=["native Simcenter solve"],
        )


def main() -> None:
    journal_main(run)


if __name__ == "__main__":
    main()
