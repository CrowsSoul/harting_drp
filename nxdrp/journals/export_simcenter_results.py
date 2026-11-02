# -*- coding: utf-8 -*-
"""Export native Simcenter values without formula-derived fallbacks."""

from __future__ import annotations

import json
import math
import os
import traceback

try:
    from .create_simcenter_case import (
        JournalError,
        NUMERIC_OUTPUTS,
        REQUIRED_RESULT_KEYS,
        error_response,
        file_digest,
        identity_fields,
        journal_main,
        validate_result_mappings,
        verify_setup_manifest,
    )
    from .solve_simcenter_case import (
        _native_artifact,
        _validate_run_metadata,
        _validate_steps,
    )
except ImportError:  # run_journal executes this file with its directory on sys.path
    from create_simcenter_case import (
        JournalError,
        NUMERIC_OUTPUTS,
        REQUIRED_RESULT_KEYS,
        error_response,
        file_digest,
        identity_fields,
        journal_main,
        validate_result_mappings,
        verify_setup_manifest,
    )
    from solve_simcenter_case import (
        _native_artifact,
        _validate_run_metadata,
        _validate_steps,
    )


QUALITY_KEYS = {
    "PERF-01": {"mesh_sensitivity_relative_change_pct", "energy_balance_relative_error"},
    "PERF-02": {"mesh_sensitivity_relative_change_pct", "penetration_max_mm"},
}


def _select_solved_response(identity: dict, request: dict) -> dict:
    candidates = []
    if "solved_response" in request:
        candidates.append(request["solved_response"])
    if "solved_response" in identity["manifest"]:
        candidates.append(identity["manifest"]["solved_response"])
    if "previous_response" in request:
        candidates.append(request["previous_response"])
    if "solve_response" in request:
        candidates.append(request["solve_response"])
    if len(candidates) != 1 or not isinstance(candidates[0], dict):
        raise JournalError(
            "PREREQUISITE_NOT_MET", "Exactly one embedded solved response is required"
        )
    solved = candidates[0]
    if solved.get("ok") is not True or solved.get("state") != "solved":
        raise JournalError("PREREQUISITE_NOT_MET", "A completed native solved response is required")
    for field, value in identity_fields(identity).items():
        if solved.get(field) != value:
            raise JournalError("PREREQUISITE_NOT_MET", "Solved response %s differs" % field)
    if solved.get("convergence_status") != "converged":
        raise JournalError("SOLVE_NOT_CONVERGED", "Solved response is not converged")
    return solved


def _validate_solved_artifacts(identity: dict, solved: dict) -> dict:
    artifacts = {}
    for name in ("native_deck", "native_result", "native_log"):
        artifact = _native_artifact(solved, name)
        recorded = solved.get(name)
        if not isinstance(recorded, dict) or recorded.get("sha256") != artifact["sha256"]:
            raise JournalError("DIGEST_MISMATCH", "Solved %s digest does not match" % name)
        if recorded.get("path") != artifact["path"]:
            raise JournalError("RUN_METADATA_INVALID", "Solved %s path is inconsistent" % name)
        artifacts[name] = artifact
    _validate_run_metadata(solved.get("run_metadata"), identity, artifacts)
    _validate_steps(solved, identity["check_item_id"])
    return artifacts


def _read_extraction(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as exc:
        raise JournalError("NATIVE_RESULT_INVALID", "Cannot read native extraction: %s" % exc) from exc
    if not isinstance(payload, dict):
        raise JournalError("NATIVE_RESULT_INVALID", "Native extraction must be an object")
    return payload


def _select_extraction(request: dict, solved: dict) -> dict:
    embedded = request.get("native_extraction")
    path = request.get("native_extraction_path") or solved.get("native_extraction_path")
    if embedded is None and not path:
        path = solved.get("native_result_path")
    if embedded is not None and path:
        raise JournalError(
            "NATIVE_RESULT_INVALID", "Use embedded native_extraction or one extraction path"
        )
    if embedded is not None:
        if not isinstance(embedded, dict):
            raise JournalError("NATIVE_RESULT_INVALID", "native_extraction must be an object")
        extraction = embedded
    else:
        if not isinstance(path, str) or not path:
            raise JournalError(
                "PREREQUISITE_NOT_MET", "An explicit NX-produced native extraction is required"
            )
        path = os.path.abspath(path)
        extraction = _read_extraction(path)
        expected_digest = solved.get("native_extraction_sha256")
        if expected_digest is not None and file_digest(path) != expected_digest:
            raise JournalError("DIGEST_MISMATCH", "Native extraction file has changed")
    if not isinstance(extraction.get("native_api"), str) or not extraction["native_api"].strip():
        raise JournalError("NATIVE_RESULT_INVALID", "Extraction native_api provenance is required")
    return extraction


def _native_number(value, label: str, *, nonnegative=False) -> float:
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JournalError("NATIVE_RESULT_INVALID", label + " must be a native numeric value")
    result = float(value)
    if not math.isfinite(result):
        raise JournalError("NATIVE_RESULT_INVALID", label + " must be finite")
    if nonnegative and result < 0:
        raise JournalError("NATIVE_RESULT_INVALID", label + " must not be negative")
    return result


def build_export_payload(identity: dict, solved: dict, extraction: dict) -> dict:
    item_id = identity["check_item_id"]
    metadata = solved["run_metadata"]
    if extraction.get("run_metadata") != metadata:
        raise JournalError(
            "RUN_METADATA_INVALID", "Extraction run metadata does not match the native solve"
        )
    if extraction.get("model_identity") != metadata["model_identity"]:
        raise JournalError("RUN_METADATA_INVALID", "Extraction model identity does not match")
    native_result = solved["native_result"]
    if extraction.get("native_result_path") != native_result["path"]:
        raise JournalError("RUN_METADATA_INVALID", "Extraction is for a different native result")
    if extraction.get("native_result_sha256") != native_result["sha256"]:
        raise JournalError("DIGEST_MISMATCH", "Extraction native result digest differs")
    _validate_steps(extraction, item_id)
    if extraction["step_statuses"] != solved["step_statuses"]:
        raise JournalError("RUN_METADATA_INVALID", "Extraction load-step evidence differs")

    mappings = validate_result_mappings(
        identity["binding"], item_id, identity["capability"], identity["setup"]
    )
    values = extraction.get("values")
    if not isinstance(values, dict):
        raise JournalError("NATIVE_RESULT_INVALID", "Native extraction values are required")
    expected_native = {mappings[name]["native_key"] for name in REQUIRED_RESULT_KEYS[item_id]}
    actual_native = set(values)
    if actual_native != expected_native:
        missing = sorted(expected_native - actual_native)
        unknown = sorted(actual_native - expected_native)
        code = "UNKNOWN_RESULT_KEY" if unknown else "OUTPUT_INCOMPLETE"
        raise JournalError(
            code,
            "Native values do not exactly match verified result mappings",
            details={"missing_native_keys": missing, "unknown_native_keys": unknown},
        )

    outputs = {}
    for name in NUMERIC_OUTPUTS[item_id]:
        mapping = mappings[name]
        native_value = values[mapping["native_key"]]
        number = _native_number(native_value, name)
        output = {
            "value": number,
            "unit": mapping["unit"],
            "native_key": mapping["native_key"],
        }
        if isinstance(native_value, dict):
            native_unit = native_value.get("unit")
            if native_unit != mapping["unit"]:
                raise JournalError(
                    "NATIVE_RESULT_INVALID", "Native unit does not match mapping for " + name
                )
            for field in ("location", "face_ids"):
                if field in native_value:
                    output[field] = native_value[field]
        outputs[name] = output

    convergence = values[mappings["convergence_status"]["native_key"]]
    if isinstance(convergence, dict):
        convergence = convergence.get("value")
    if convergence != "converged":
        raise JournalError("SOLVE_NOT_CONVERGED", "Native convergence value is not converged")
    residual = _native_number(
        values[mappings["residual"]["native_key"]], "residual", nonnegative=True
    )
    quality_values = extraction.get("quality")
    if not isinstance(quality_values, dict) or set(quality_values) != QUALITY_KEYS[item_id]:
        raise JournalError(
            "QUALITY_INCOMPLETE",
            "Native quality keys are incomplete or unknown",
            details={"required": sorted(QUALITY_KEYS[item_id])},
        )
    quality = {
        name: _native_number(value, "quality." + name, nonnegative=True)
        for name, value in quality_values.items()
    }
    return {
        "schema_version": "1.0.0",
        "case_id": identity["case_id"],
        "check_item_id": item_id,
        "batch_id": identity["setup"].get("batch_id", ""),
        "setup_digest": identity["setup_digest"],
        "binding_digest": identity["binding_digest"],
        "capability_id": identity["capability"].get("capability_id", ""),
        "evidence_source": "cae_solver",
        "solver": metadata["solver"],
        "model_identity": metadata["model_identity"],
        "run": {
            "run_id": metadata["run_id"],
            "started_at": metadata["started_at"],
            "finished_at": metadata["finished_at"],
            "case_file": metadata["case_file"],
            "result_file": metadata["result_file"],
            "native_result_path": solved["native_result"]["path"],
            "native_result_digest": solved["native_result"]["sha256"],
            "log_file": solved["native_log"]["path"],
            "native_api": metadata["native_api"],
            "extraction_api": extraction["native_api"],
            "solution_title": metadata["solution_title"],
            "case_digest": identity["case_digest"],
            "setup_digest": identity["setup_digest"],
            "binding_digest": identity["binding_digest"],
            "capability_digest": identity["capability_digest"],
            "step_statuses": solved["step_statuses"],
        },
        "convergence_status": "converged",
        "residual": residual,
        "outputs": outputs,
        "quality": quality,
        "notes": ["Values and quality metrics were extracted by the declared native NX API."],
    }


def execute(request: dict) -> dict:
    identity = verify_setup_manifest(request, require_confirmed_binding=True)
    solved = _select_solved_response(identity, request)
    _validate_solved_artifacts(identity, solved)
    extraction = _select_extraction(request, solved)
    result = build_export_payload(identity, solved, extraction)
    out_path = request.get("out_path") or identity["setup"].get("result_path")
    if not out_path:
        artifacts = identity["setup"].get("artifacts")
        if isinstance(artifacts, dict):
            out_path = artifacts.get("solver_result")
    if not isinstance(out_path, str) or not out_path:
        raise JournalError("EXPORT_PATH_REQUIRED", "out_path is required for the native result export")
    out_path = os.path.abspath(out_path)
    if os.path.exists(out_path):
        raise JournalError("OUTPUT_EXISTS", "Refusing to overwrite result export: " + out_path)
    parent = os.path.dirname(out_path)
    if not parent:
        raise JournalError("EXPORT_PATH_REQUIRED", "An absolute result output path is required")
    os.makedirs(parent, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
    return {
        "ok": True,
        "state": "exported",
        **identity_fields(identity),
        "result_path": out_path,
        "solver_result_path": out_path,
        "result_sha256": file_digest(out_path),
        "output_keys": list(NUMERIC_OUTPUTS[identity["check_item_id"]]),
        "quality_keys": sorted(QUALITY_KEYS[identity["check_item_id"]]),
        "not_done": ["downstream ingestion and certification"],
    }


def run(request: dict) -> dict:
    try:
        return execute(request)
    except JournalError as exc:
        return exc.response()
    except Exception as exc:
        return error_response(
            "EXPORT_FAILED",
            "Native result export failed: %r" % exc,
            details={"traceback": traceback.format_exc()[-2000:]},
            not_done=["native result export"],
        )


def main() -> None:
    journal_main(run)


if __name__ == "__main__":
    main()
