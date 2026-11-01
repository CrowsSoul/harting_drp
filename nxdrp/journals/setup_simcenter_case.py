# -*- coding: utf-8 -*-
"""Commit a confirmed PERF setup, or report exactly what remains not_done.

NX 2606 setup builders are integration points, not speculative API calls.  A
verified runtime must inject builders that perform and commit the corresponding
NX Open operations.  Without one, the named builder raises NX_API_UNSUPPORTED.
"""

from __future__ import annotations

import math
import os
import traceback

try:
    from .create_simcenter_case import (
        JournalError,
        REQUIRED_RESULT_KEYS,
        _required_capability_text,
        identity_fields,
        journal_main,
        require_online_execution,
        validate_result_mappings,
        verify_setup_manifest,
        error_response,
        file_digest,
    )
except ImportError:  # run_journal executes this file with its directory on sys.path
    from create_simcenter_case import (
        JournalError,
        REQUIRED_RESULT_KEYS,
        _required_capability_text,
        identity_fields,
        journal_main,
        require_online_execution,
        validate_result_mappings,
        verify_setup_manifest,
        error_response,
        file_digest,
    )


PERF01_BUILDERS = (
    "perf01_material",
    "perf01_mesh",
    "perf01_electrical_current",
    "perf01_electrical_ground",
    "perf01_convection",
    "perf01_radiation",
    "perf01_output_requests",
)
PERF02_BUILDERS = (
    "perf02_material",
    "perf02_mesh",
    "perf02_fixed_root",
    "perf02_enforced_displacement",
    "perf02_surface_contact",
    "perf02_friction",
    "perf02_penalty",
    "perf02_search",
    "perf02_sol401_three_load_steps",
    "perf02_output_requests",
)


def _number(value, field: str, *, positive=False, nonnegative=False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JournalError("SETUP_INVALID", field + " must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise JournalError("SETUP_INVALID", field + " must be finite")
    if positive and result <= 0:
        raise JournalError("SETUP_INVALID", field + " must be greater than zero")
    if nonnegative and result < 0:
        raise JournalError("SETUP_INVALID", field + " must not be negative")
    return result


def _material_values(binding: dict, fields, item_id: str) -> None:
    material = binding.get("material")
    if not isinstance(material, dict) or not material.get("material"):
        raise JournalError("SETUP_INVALID", "A named material is required")
    for field in fields:
        _number(material.get(field), item_id + ".material." + field, positive=True)


def _validate_perf01(identity: dict) -> None:
    binding = identity["binding"]
    _material_values(
        binding,
        (
            "density_kg_m3",
            "thermal_conductivity_w_mk",
            "specific_heat_j_kgk",
            "electrical_resistivity_ohm_m",
            "temperature_coefficient_1_k",
            "emissivity",
        ),
        "PERF-01",
    )
    emissivity = _number(binding["material"]["emissivity"], "material.emissivity")
    if emissivity > 1:
        raise JournalError("SETUP_INVALID", "material.emissivity must be in [0, 1]")
    loads = binding.get("load_values")
    if not isinstance(loads, dict):
        raise JournalError("SETUP_INVALID", "PERF-01 load_values are required")
    _number(loads.get("current_a"), "current_a", positive=True)
    outlet_voltage = _number(loads.get("outlet_voltage_v"), "outlet_voltage_v")
    if outlet_voltage != 0.0:
        raise JournalError("SETUP_INVALID", "Electrical ground outlet_voltage_v must be zero")
    _number(loads.get("ambient_temperature_c"), "ambient_temperature_c")
    _number(loads.get("convection_h_w_m2k"), "convection_h_w_m2k", positive=True)
    radiation = _number(loads.get("radiation_emissivity"), "radiation_emissivity")
    if radiation > 1:
        raise JournalError("SETUP_INVALID", "radiation_emissivity must be in [0, 1]")


def _validate_perf02(identity: dict) -> None:
    binding = identity["binding"]
    _material_values(
        binding,
        ("density_kg_m3", "elastic_modulus_gpa", "yield_strength_mpa"),
        "PERF-02",
    )
    poisson = _number(binding["material"].get("poisson_ratio"), "poisson_ratio")
    if not 0 < poisson < 0.5:
        raise JournalError("SETUP_INVALID", "poisson_ratio must be between zero and 0.5")
    loads = binding.get("load_values")
    if not isinstance(loads, dict):
        raise JournalError("SETUP_INVALID", "PERF-02 load_values are required")
    _number(loads.get("normal_overlap_mm"), "normal_overlap_mm", positive=True)
    _number(loads.get("insertion_stroke_mm"), "insertion_stroke_mm", positive=True)
    pairs = binding.get("contact_pairs")
    if not isinstance(pairs, list) or not pairs:
        raise JournalError("SETUP_INVALID", "At least one contact pair is required")
    for index, pair in enumerate(pairs):
        label = "contact_pairs[%d]" % index
        if not isinstance(pair, dict) or pair.get("status") != "confirmed":
            raise JournalError("BINDING_NOT_CONFIRMED", label + " is not confirmed")
        if pair.get("method") != "penalty":
            raise JournalError("SETUP_INVALID", label + " must use penalty contact")
        if not pair.get("source_face_ids") or not pair.get("target_face_ids"):
            raise JournalError("SETUP_INVALID", label + " source/target faces are required")
        _number(pair.get("friction_coefficient"), label + ".friction", nonnegative=True)
        _number(pair.get("penalty_stiffness"), label + ".penalty", positive=True)
        _number(pair.get("search_distance_mm"), label + ".search", positive=True)
        if pair.get("normal_overlap_mm") != loads["normal_overlap_mm"]:
            raise JournalError("SETUP_INVALID", label + " normal overlap differs from load_values")
        if pair.get("insertion_stroke_mm") != loads["insertion_stroke_mm"]:
            raise JournalError("SETUP_INVALID", label + " insertion stroke differs from load_values")
        if pair.get("large_displacement") is not True:
            raise JournalError("SETUP_INVALID", label + " requires large displacement")
    steps = identity["case"].get("load_steps")
    if steps is None:
        steps = identity["setup"].get("load_steps")
    if not isinstance(steps, list) or len(steps) != 3:
        raise JournalError("SETUP_INVALID", "PERF-02 requires exactly three load steps")
    expected = ((1, "establish_contact"), (2, "insert"), (3, "withdraw"))
    actual = tuple((step.get("step"), step.get("action")) for step in steps if isinstance(step, dict))
    if actual != expected:
        raise JournalError(
            "SETUP_INVALID",
            "PERF-02 load steps must be establish_contact, insert, withdraw in that order",
        )


def _select_container(identity: dict, request: dict) -> dict:
    manifest = identity["manifest"]
    setup_payload = identity["setup"]
    candidates = []
    if "container_response" in request:
        candidates.append(request["container_response"])
    if "container" in manifest:
        candidates.append(manifest["container"])
    if setup_payload is not manifest and "container" in setup_payload:
        candidates.append(setup_payload["container"])
    if len(candidates) > 1:
        raise JournalError("CONTAINER_UNVERIFIED", "Multiple container responses are ambiguous")
    if candidates:
        container = candidates[0]
        if not isinstance(container, dict):
            raise JournalError("CONTAINER_UNVERIFIED", "Container response must be an object")
        if container.get("ok") is not True or container.get("state") != "container_created":
            raise JournalError("CONTAINER_UNVERIFIED", "Container response is not complete")
        for field, value in identity_fields(identity).items():
            if container.get(field) != value:
                raise JournalError("CONTAINER_UNVERIFIED", "Container %s does not match" % field)
    else:
        # The setup orchestrator invokes create then setup with the same request.
        # Verify the on-disk products directly rather than inventing a response.
        artifacts = setup_payload.get("artifacts")
        if not isinstance(artifacts, dict):
            raise JournalError("CONTAINER_UNVERIFIED", "Manifest FEM/SIM artifacts are required")
        container = {
            "ok": True,
            "state": "container_created",
            **identity_fields(identity),
            "fem_path": artifacts.get("fem"),
            "sim_path": artifacts.get("sim"),
        }
    for stem in ("fem", "sim"):
        path = container.get(stem + "_path")
        if not isinstance(path, str) or not path or not os.path.isfile(path):
            raise JournalError("CONTAINER_UNVERIFIED", "Container artifact is missing: %s" % path)
        if os.path.getsize(path) == 0:
            raise JournalError("CONTAINER_UNVERIFIED", "Container artifact is empty: " + path)
        actual = file_digest(path)
        expected = container.get(stem + "_sha256")
        if expected is not None and actual != expected:
            raise JournalError("DIGEST_MISMATCH", "Container artifact changed: " + path)
        container[stem + "_path"] = os.path.abspath(path)
        container[stem + "_sha256"] = actual
    return container


def _invoke_builder(name: str, context: dict, payload: dict) -> dict:
    registry = context.get("builder_registry")
    builder = registry.get(name) if isinstance(registry, dict) else None
    if not callable(builder):
        raise JournalError(
            "NX_API_UNSUPPORTED",
            "No verified NX 2606 builder is registered for %s; refusing a no-op setup" % name,
            details={"builder": name, "required_action": "implement and verify the NX Open commit"},
            not_done=[name],
        )
    result = builder(context, payload)
    if not isinstance(result, dict) or result.get("committed") is not True:
        raise JournalError(
            "NX_API_UNSUPPORTED",
            "Builder %s did not return an explicit committed result" % name,
            details={"builder": name},
            not_done=[name],
        )
    if name.endswith("output_requests") and result.get("output_requests_set") is not True:
        raise JournalError(
            "OUTPUT_REQUESTS_NOT_SET",
            "Builder %s committed without confirming native output requests" % name,
            not_done=["native output requests"],
        )
    return result


def build_perf01_material(context: dict, payload: dict) -> dict:
    return _invoke_builder("perf01_material", context, payload)


def build_perf01_mesh(context: dict, payload: dict) -> dict:
    return _invoke_builder("perf01_mesh", context, payload)


def build_perf01_electrical_current(context: dict, payload: dict) -> dict:
    return _invoke_builder("perf01_electrical_current", context, payload)


def build_perf01_electrical_ground(context: dict, payload: dict) -> dict:
    return _invoke_builder("perf01_electrical_ground", context, payload)


def build_perf01_convection(context: dict, payload: dict) -> dict:
    return _invoke_builder("perf01_convection", context, payload)


def build_perf01_radiation(context: dict, payload: dict) -> dict:
    return _invoke_builder("perf01_radiation", context, payload)


def build_perf01_output_requests(context: dict, payload: dict) -> dict:
    return _invoke_builder("perf01_output_requests", context, payload)


def build_perf02_material(context: dict, payload: dict) -> dict:
    return _invoke_builder("perf02_material", context, payload)


def build_perf02_mesh(context: dict, payload: dict) -> dict:
    return _invoke_builder("perf02_mesh", context, payload)


def build_perf02_fixed_root(context: dict, payload: dict) -> dict:
    return _invoke_builder("perf02_fixed_root", context, payload)


def build_perf02_enforced_displacement(context: dict, payload: dict) -> dict:
    return _invoke_builder("perf02_enforced_displacement", context, payload)


def build_perf02_surface_contact(context: dict, payload: dict) -> dict:
    return _invoke_builder("perf02_surface_contact", context, payload)


def build_perf02_friction(context: dict, payload: dict) -> dict:
    return _invoke_builder("perf02_friction", context, payload)


def build_perf02_penalty(context: dict, payload: dict) -> dict:
    return _invoke_builder("perf02_penalty", context, payload)


def build_perf02_search(context: dict, payload: dict) -> dict:
    return _invoke_builder("perf02_search", context, payload)


def build_perf02_sol401_three_load_steps(context: dict, payload: dict) -> dict:
    return _invoke_builder("perf02_sol401_three_load_steps", context, payload)


def build_perf02_output_requests(context: dict, payload: dict) -> dict:
    return _invoke_builder("perf02_output_requests", context, payload)


def _run_perf01_builders(context: dict, payload: dict) -> dict:
    results = {}
    results["perf01_material"] = build_perf01_material(context, payload)
    results["perf01_mesh"] = build_perf01_mesh(context, payload)
    results["perf01_electrical_current"] = build_perf01_electrical_current(context, payload)
    results["perf01_electrical_ground"] = build_perf01_electrical_ground(context, payload)
    results["perf01_convection"] = build_perf01_convection(context, payload)
    results["perf01_radiation"] = build_perf01_radiation(context, payload)
    results["perf01_output_requests"] = build_perf01_output_requests(context, payload)
    return results


def _run_perf02_builders(context: dict, payload: dict) -> dict:
    results = {}
    results["perf02_material"] = build_perf02_material(context, payload)
    results["perf02_mesh"] = build_perf02_mesh(context, payload)
    results["perf02_fixed_root"] = build_perf02_fixed_root(context, payload)
    results["perf02_enforced_displacement"] = build_perf02_enforced_displacement(context, payload)
    results["perf02_surface_contact"] = build_perf02_surface_contact(context, payload)
    results["perf02_friction"] = build_perf02_friction(context, payload)
    results["perf02_penalty"] = build_perf02_penalty(context, payload)
    results["perf02_search"] = build_perf02_search(context, payload)
    results["perf02_sol401_three_load_steps"] = build_perf02_sol401_three_load_steps(context, payload)
    results["perf02_output_requests"] = build_perf02_output_requests(context, payload)
    return results


def execute(request: dict, *, nxopen=None, builder_registry=None) -> dict:
    identity = verify_setup_manifest(request, require_confirmed_binding=True)
    if identity["check_item_id"] == "PERF-01":
        _validate_perf01(identity)
    else:
        _validate_perf02(identity)
    mappings = validate_result_mappings(
        identity["binding"], identity["check_item_id"], identity["capability"], identity["setup"]
    )
    container = _select_container(identity, request)
    require_online_execution(request)
    if nxopen is None:
        try:
            import NXOpen as nxopen_module
        except ImportError as exc:
            raise JournalError(
                "NX_API_UNSUPPORTED", "Setup requires NXOpen inside a licensed NX process"
            ) from exc
        nxopen = nxopen_module
    context = {
        "nxopen": nxopen,
        "session": nxopen.Session.GetSession(),
        "builder_registry": builder_registry,
        "identity": identity,
        "container": container,
    }
    builder_payload = {
        "case": identity["case"],
        "setup": identity["setup"],
        "binding": identity["binding"],
        "capability": identity["capability"],
        "container": container,
        "output_requests": mappings,
    }
    if identity["check_item_id"] == "PERF-01":
        results = _run_perf01_builders(context, builder_payload)
        expected_builders = PERF01_BUILDERS
    else:
        results = _run_perf02_builders(context, builder_payload)
        expected_builders = PERF02_BUILDERS
    if set(results) != set(expected_builders):
        raise JournalError("SETUP_INCOMPLETE", "Not every required builder committed")
    return {
        "ok": True,
        "state": "solver_ready",
        **identity_fields(identity),
        "solver": _required_capability_text(identity["capability"], "solver"),
        "solution_title": _required_capability_text(identity["capability"], "solution_title"),
        "builders": results,
        "output_requests_set": True,
        "required_result_keys": list(REQUIRED_RESULT_KEYS[identity["check_item_id"]]),
        "not_done": ["native Simcenter solve", "native result extraction and export"],
    }


def run(request: dict, *, nxopen=None, builder_registry=None) -> dict:
    try:
        return execute(request, nxopen=nxopen, builder_registry=builder_registry)
    except JournalError as exc:
        return exc.response()
    except Exception as exc:
        return error_response(
            "NX_API_ERROR",
            "Setup failed before solver_ready: %r" % exc,
            details={"traceback": traceback.format_exc()[-2000:]},
            not_done=["setup did not fully commit"],
        )


def main() -> None:
    journal_main(run)


if __name__ == "__main__":
    main()
