# -*- coding: utf-8 -*-
"""Create verified PERF FEM/SIM containers with explicit NX Open calls.

The journal does not choose a solver from a case name.  A signed-off setup
manifest must carry the case, setup and binding payloads, their local SHA-256
digests, and a verified capability description.  Container creation is not a
mesh, boundary-condition, solve, or result-completion claim.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import traceback


REQUEST_ENV = "NXDRP_NX_REQUEST"
RESPONSE_ENV = "NXDRP_NX_RESPONSE"

SUPPORTED_CAPABILITY = {
    "PERF-01": "thermal_with_joule",
    "PERF-02": "SOL401",
}
NUMERIC_OUTPUTS = {
    "PERF-01": (
        "maximum_temperature_c",
        "delta_t_c",
        "total_resistance_ohm",
        "joule_power_w",
        "voltage_drop_v",
    ),
    "PERF-02": (
        "insertion_force_n",
        "withdrawal_force_n",
        "maximum_normal_contact_force_n",
        "maximum_penetration_mm",
        "maximum_equivalent_stress_mpa",
    ),
}
STATUS_OUTPUTS = ("convergence_status", "residual")
REQUIRED_RESULT_KEYS = {
    item: NUMERIC_OUTPUTS[item] + STATUS_OUTPUTS for item in NUMERIC_OUTPUTS
}
REQUIRED_FACE_ROLES = {
    "PERF-01": ("electrical_inlet", "electrical_outlet", "convection", "radiation"),
    "PERF-02": ("fixed_root", "driven_face", "contact_source", "contact_target"),
}
AUTHORIZED_LICENSE_MODES = {"authorized", "commercial", "floating", "node_locked"}


class JournalError(Exception):
    """An expected fail-closed journal error with a stable machine code."""

    def __init__(self, error_code: str, message: str, *, details=None, not_done=None):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.details = details or {}
        self.not_done = list(not_done or [])

    def response(self) -> dict:
        payload = {
            "ok": False,
            "state": "not_done",
            "error_code": self.error_code,
            "error": self.message,
            "not_done": self.not_done,
        }
        if self.details:
            payload["details"] = self.details
        return payload


def error_response(error_code: str, message: str, *, details=None, not_done=None) -> dict:
    return JournalError(
        error_code, message, details=details, not_done=not_done
    ).response()


def _canonical_bytes(payload: dict) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def payload_digest(payload: dict, digest_field: str = "") -> str:
    if not isinstance(payload, dict):
        raise JournalError("MANIFEST_INVALID", "Digest payload must be a JSON object")
    content = dict(payload)
    if digest_field:
        content.pop(digest_field, None)
    return hashlib.sha256(_canonical_bytes(content)).hexdigest()


def file_digest(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _verified_digest(payload: dict, field: str, label: str) -> str:
    expected = payload.get(field)
    if not isinstance(expected, str) or len(expected) != 64:
        raise JournalError(
            "DIGEST_UNVERIFIED",
            "%s must contain a SHA-256 %s" % (label, field),
            not_done=[label + " digest verification"],
        )
    actual = payload_digest(payload, field)
    if not hmac.compare_digest(expected, actual):
        raise JournalError(
            "DIGEST_MISMATCH",
            "%s does not match the local payload hash" % field,
            details={"field": field, "expected": expected, "actual": actual},
            not_done=[label + " digest verification"],
        )
    return actual


def _read_json(path: str, label: str) -> dict:
    if not isinstance(path, str) or not path:
        raise JournalError("MANIFEST_INVALID", label + " path is required")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as exc:
        raise JournalError(
            "MANIFEST_INVALID", "Cannot read %s: %s" % (label, exc)
        ) from exc
    if not isinstance(payload, dict):
        raise JournalError("MANIFEST_INVALID", label + " must be a JSON object")
    return payload


def _select_manifest(request: dict) -> dict:
    embedded = request.get("setup_manifest")
    path = request.get("setup_manifest_path") or request.get("manifest_path")
    if embedded is not None and path:
        raise JournalError(
            "MANIFEST_INVALID", "Use either setup_manifest or setup_manifest_path, not both"
        )
    if embedded is not None:
        if not isinstance(embedded, dict):
            raise JournalError("MANIFEST_INVALID", "setup_manifest must be an object")
        return embedded
    if path:
        return _read_json(path, "setup manifest")
    if all(name in request for name in ("case", "setup", "binding")):
        return request
    raise JournalError(
        "MANIFEST_INVALID",
        "A setup manifest with case, setup and binding payloads is required",
        not_done=["manifest validation"],
    )


def _select_capability(request: dict, manifest: dict) -> dict:
    from_request = request.get("capability")
    from_manifest = manifest.get("capability")
    if from_request is not None and from_manifest is not None:
        if _canonical_bytes(from_request) != _canonical_bytes(from_manifest):
            raise JournalError(
                "CAPABILITY_UNVERIFIED",
                "Request and manifest capabilities are different",
                not_done=["capability verification"],
            )
    capability = from_manifest if from_manifest is not None else from_request
    if not isinstance(capability, dict):
        raise JournalError(
            "CAPABILITY_UNVERIFIED",
            "An embedded verified capability is required",
            not_done=["capability verification"],
        )
    return capability


def _select_binding(request: dict, manifest: dict) -> dict:
    binding = manifest.get("binding")
    wrapper_digest = ""
    if isinstance(binding, dict) and "payload" in binding:
        wrapper_digest = binding.get("digest") or ""
        binding = binding.get("payload")
    binding_path = manifest.get("binding_path") or request.get("bindings_path")
    if binding is not None and binding_path:
        from_path = _read_json(binding_path, "binding")
        if _canonical_bytes(binding) != _canonical_bytes(from_path):
            raise JournalError(
                "DIGEST_MISMATCH", "Embedded binding and bindings_path differ"
            )
    if binding is None and binding_path:
        binding = _read_json(binding_path, "binding")
    if not isinstance(binding, dict):
        raise JournalError("MANIFEST_INVALID", "The setup manifest has no binding object")
    if wrapper_digest and wrapper_digest != binding.get("binding_digest"):
        raise JournalError("DIGEST_MISMATCH", "Binding wrapper digest is stale")
    return binding


def _check_optional_request_digest(request: dict, field: str, actual: str) -> None:
    expected = request.get(field)
    if expected is not None and expected != actual:
        raise JournalError(
            "DIGEST_MISMATCH",
            "Request %s does not match the manifest" % field,
            details={"field": field, "expected": expected, "actual": actual},
        )


def verify_capability(capability: dict, check_item_id: str) -> str:
    if capability.get("verified") is not True or capability.get("status", "verified") != "verified":
        raise JournalError(
            "CAPABILITY_UNVERIFIED",
            "Capability must be explicitly verified; offline assumptions are not verification",
            not_done=["NX 2606 capability verification"],
        )
    if capability.get("execution_ready") is False:
        raise JournalError(
            "CAPABILITY_UNVERIFIED", "Capability is explicitly marked not execution-ready"
        )
    if capability.get("check_item_id") != check_item_id:
        raise JournalError(
            "CAPABILITY_UNVERIFIED",
            "Capability check_item_id does not match the case",
            not_done=["capability verification"],
        )
    feature = SUPPORTED_CAPABILITY.get(check_item_id)
    if feature is None:
        raise JournalError(
            "CAPABILITY_UNVERIFIED", "Unsupported PERF check item: %s" % check_item_id
        )
    features = capability.get("capabilities")
    if isinstance(features, dict):
        supported = features.get(feature) is True
    else:
        supported_modes = capability.get("supported_modes")
        supported = (
            capability.get("mode") == feature
            and isinstance(supported_modes, list)
            and feature in supported_modes
        )
    if not supported:
        raise JournalError(
            "CAPABILITY_UNVERIFIED",
            "Verified capability %s is required for %s" % (feature, check_item_id),
            details={"required_capability": feature},
            not_done=["NX 2606 capability verification"],
        )
    if "capability_digest" in capability:
        _verified_digest(capability, "capability_digest", "capability")
    return payload_digest(capability, "capability_digest")


def validate_result_mappings(
    binding: dict, check_item_id: str, capability: dict = None, setup: dict = None
) -> dict:
    queries = binding.get("result_queries")
    if not isinstance(queries, dict):
        raise JournalError(
            "RESULT_MAPPING_UNVERIFIED", "binding.result_queries must be an object"
        )
    expected = set(REQUIRED_RESULT_KEYS[check_item_id])
    if set(queries) != expected:
        raise JournalError(
            "RESULT_MAPPING_UNVERIFIED",
            "Result query keys must exactly match the required native outputs",
            details={
                "missing": sorted(expected - set(queries)),
                "unknown": sorted(set(queries) - expected),
            },
        )
    native_mappings = {}
    if isinstance(capability, dict):
        for field in ("native_result_mapping", "native_result_keys", "result_mapping"):
            value = capability.get(field)
            if isinstance(value, dict) and value:
                native_mappings = value
                break
    if not native_mappings and isinstance(setup, dict):
        value = setup.get("result_mapping")
        if isinstance(value, dict):
            native_mappings = value
    required_units = (setup.get("required_output_units") or {}) if isinstance(setup, dict) else {}
    if not isinstance(required_units, dict):
        raise JournalError("RESULT_MAPPING_UNVERIFIED", "required_output_units must be an object")
    mappings = {}
    for name in sorted(expected):
        query = queries[name]
        if not isinstance(query, dict) or query.get("status") != "confirmed":
            raise JournalError(
                "RESULT_MAPPING_UNVERIFIED",
                "Result query %s is not confirmed" % name,
            )
        native_key = query.get("native_key") or native_mappings.get(name)
        if not isinstance(native_key, str) or not native_key.strip():
            raise JournalError(
                "RESULT_MAPPING_UNVERIFIED",
                "Result query %s needs a verified native key" % name,
            )
        mapping = {"native_key": native_key}
        if name in NUMERIC_OUTPUTS[check_item_id]:
            unit = required_units.get(name) or query.get("unit")
            query_unit = query.get("unit")
            if query_unit and name in required_units and query_unit != required_units[name]:
                raise JournalError(
                    "RESULT_MAPPING_UNVERIFIED", "Result units disagree for " + name
                )
            if not isinstance(unit, str) or not unit.strip():
                raise JournalError(
                    "RESULT_MAPPING_UNVERIFIED",
                    "Numeric result query %s needs a verified unit" % name,
                )
            mapping["unit"] = unit
        mappings[name] = mapping
    if len({m["native_key"] for m in mappings.values()}) != len(mappings):
        raise JournalError(
            "RESULT_MAPPING_UNVERIFIED", "Native result keys must be unique"
        )
    return mappings


def validate_confirmed_binding(
    binding: dict, check_item_id: str, capability: dict = None, setup: dict = None
) -> None:
    if binding.get("status") not in {"confirmed", "ready_for_simcenter"}:
        raise JournalError(
            "BINDING_NOT_CONFIRMED", "The engineering binding is not confirmed"
        )
    geometry = binding.get("source_geometry")
    if not isinstance(geometry, dict) or geometry.get("status") != "confirmed":
        raise JournalError(
            "BINDING_NOT_CONFIRMED", "Source geometry is not confirmed"
        )
    if not geometry.get("source_part") or not geometry.get("model_digest"):
        raise JournalError("BINDING_NOT_CONFIRMED", "Source identity is incomplete")
    if not isinstance(geometry.get("body_tags"), list) or not geometry["body_tags"]:
        raise JournalError("BINDING_NOT_CONFIRMED", "Confirmed body_tags are required")
    roles = binding.get("face_roles")
    if not isinstance(roles, dict):
        raise JournalError("BINDING_NOT_CONFIRMED", "face_roles must be an object")
    for role in REQUIRED_FACE_ROLES[check_item_id]:
        value = roles.get(role)
        if (
            not isinstance(value, dict)
            or value.get("status") != "confirmed"
            or not isinstance(value.get("face_ids"), list)
            or not value["face_ids"]
        ):
            raise JournalError(
                "BINDING_NOT_CONFIRMED", "Face role %s is not confirmed" % role
            )
    validate_result_mappings(binding, check_item_id, capability, setup)


def verify_setup_manifest(request: dict, *, require_confirmed_binding: bool = False) -> dict:
    if not isinstance(request, dict):
        raise JournalError("MANIFEST_INVALID", "Journal request must be a JSON object")
    manifest = _select_manifest(request)
    case = manifest.get("case")
    setup = manifest.get("setup")
    if setup is None and "setup_digest" in manifest:
        setup = manifest
    if not isinstance(case, dict) or not isinstance(setup, dict):
        raise JournalError("MANIFEST_INVALID", "case and setup must be objects")
    binding = _select_binding(request, manifest)
    capability = _select_capability(request, manifest)

    if "case_digest" in case:
        case_digest = _verified_digest(case, "case_digest", "case")
    else:
        model_identity = manifest.get("model_identity")
        expected_case_digest = manifest.get("case_digest")
        if expected_case_digest is None and isinstance(model_identity, dict):
            expected_case_digest = model_identity.get("input_digest")
        if not isinstance(expected_case_digest, str) or len(expected_case_digest) != 64:
            raise JournalError(
                "DIGEST_UNVERIFIED", "Case digest or model input_digest is required"
            )
        case_digest = payload_digest(case, "case_digest")
        if not hmac.compare_digest(case_digest, expected_case_digest):
            raise JournalError("DIGEST_MISMATCH", "Case payload hash does not match input_digest")
    setup_digest = _verified_digest(setup, "setup_digest", "setup")
    binding_digest = _verified_digest(binding, "binding_digest", "binding")
    for field, actual in (
        ("case_digest", case_digest),
        ("setup_digest", setup_digest),
        ("binding_digest", binding_digest),
    ):
        root_value = manifest.get(field)
        if root_value is not None and root_value != actual:
            raise JournalError("DIGEST_MISMATCH", "Manifest %s is stale" % field)
        _check_optional_request_digest(request, field, actual)

    case_id = case.get("case_id")
    check_item_id = case.get("check_item_id")
    if not isinstance(case_id, str) or not case_id:
        raise JournalError("MANIFEST_INVALID", "case.case_id is required")
    if check_item_id not in SUPPORTED_CAPABILITY:
        raise JournalError("CAPABILITY_UNVERIFIED", "Unsupported case check_item_id")
    for label, payload in (("setup", setup), ("binding", binding)):
        if payload.get("case_id") != case_id:
            raise JournalError("MANIFEST_MISMATCH", label + " case_id does not match")
        if payload.get("check_item_id") != check_item_id:
            raise JournalError(
                "MANIFEST_MISMATCH", label + " check_item_id does not match"
            )
    request_case_id = request.get("case_id")
    if request_case_id is not None and request_case_id != case_id:
        raise JournalError("MANIFEST_MISMATCH", "Request case_id does not match")
    request_item = request.get("check_item_id")
    if request_item is not None and request_item != check_item_id:
        raise JournalError("MANIFEST_MISMATCH", "Request check_item_id does not match")
    capability_digest = verify_capability(capability, check_item_id)
    if require_confirmed_binding:
        validate_confirmed_binding(binding, check_item_id, capability, setup)
    return {
        "manifest": manifest,
        "case": case,
        "setup": setup,
        "binding": binding,
        "capability": capability,
        "case_id": case_id,
        "check_item_id": check_item_id,
        "case_digest": case_digest,
        "setup_digest": setup_digest,
        "binding_digest": binding_digest,
        "capability_digest": capability_digest,
    }


def identity_fields(identity: dict) -> dict:
    return {
        "case_id": identity["case_id"],
        "check_item_id": identity["check_item_id"],
        "case_digest": identity["case_digest"],
        "setup_digest": identity["setup_digest"],
        "binding_digest": identity["binding_digest"],
        "capability_digest": identity["capability_digest"],
    }


def require_online_execution(request: dict) -> None:
    if request.get("online_execution") is not True:
        raise JournalError(
            "ONLINE_EXECUTION_REQUIRED",
            "online_execution must be true; offline validation cannot execute NX",
            not_done=["online NX execution"],
        )


def _part_from_result(value):
    return value[0] if isinstance(value, (tuple, list)) else value


def _binding_digest(binding: dict) -> str:
    """Backward-compatible name; verification still requires the stored digest."""
    return payload_digest(binding, "binding_digest")


def _required_capability_text(capability: dict, field: str) -> str:
    aliases = {
        "solver": ("solver", "solver_name"),
        "analysis_type": ("analysis_type", "analysis", "analysis_name"),
        "solution_type": ("solution_type",),
        "solution_title": ("solution_title", "solution_name", "registered_solution_title"),
        "fem_template": ("fem_template",),
        "sim_template": ("sim_template",),
        "presentation": ("presentation", "template_presentation", "solver", "solver_name"),
    }
    value = None
    for name in aliases[field]:
        candidate = capability.get(name)
        if isinstance(candidate, str) and candidate.strip():
            value = candidate
            break
    if value is None and field == "fem_template":
        templates = capability.get("template_names")
        if isinstance(templates, dict):
            value = templates.get("fem")
    if value is None and field == "sim_template":
        templates = capability.get("template_names")
        if isinstance(templates, dict):
            value = templates.get("sim")
    if not isinstance(value, str) or not value.strip():
        raise JournalError(
            "CAPABILITY_UNVERIFIED", "Verified capability is missing %s" % field
        )
    return value


def _is_sha256(value: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdefABCDEF" for character in value)
    )


def _verify_source_digest(geometry: dict, source_path: str) -> None:
    """Refuse to build containers from a source part that changed after sign-off."""
    expected = str(geometry.get("model_digest") or "")
    if not _is_sha256(expected):
        return
    actual = file_digest(source_path)
    if not hmac.compare_digest(expected.casefold(), actual):
        raise JournalError(
            "DIGEST_MISMATCH",
            "Source part content no longer matches the confirmed geometry digest",
            details={"expected": expected, "actual": actual, "source_part": source_path},
            not_done=["source geometry verification"],
        )


def _container_paths(identity: dict, request: dict, out_dir: str) -> tuple[str, str]:
    artifacts = request.get("artifacts")
    if artifacts is None:
        artifacts = identity["setup"].get("artifacts")
    if artifacts is not None and not isinstance(artifacts, dict):
        raise JournalError("MANIFEST_INVALID", "artifacts must be an object")
    artifacts = artifacts or {}
    case_id = identity["case_id"]
    fem_path = artifacts.get("fem") or os.path.join(out_dir, case_id + ".fem")
    sim_path = artifacts.get("sim") or os.path.join(out_dir, case_id + ".sim")
    return os.path.abspath(fem_path), os.path.abspath(sim_path)


def _create_containers(identity: dict, request: dict, nxopen) -> dict:
    case_id = identity["case_id"]
    binding = identity["binding"]
    capability = identity["capability"]
    geometry = binding["source_geometry"]
    source_path = os.path.abspath(geometry["source_part"])
    out_dir = request.get("out_dir") or identity["setup"].get("out_dir")
    if not isinstance(out_dir, str) or not out_dir:
        raise JournalError("MANIFEST_INVALID", "out_dir is required in request or setup")
    out_dir = os.path.abspath(out_dir)
    if not os.path.isfile(source_path):
        raise JournalError("SOURCE_NOT_FOUND", "Source part does not exist: " + source_path)
    _verify_source_digest(geometry, source_path)
    os.makedirs(out_dir, exist_ok=True)

    fem_path, sim_path = _container_paths(identity, request, out_dir)
    for path in (fem_path, sim_path):
        if os.path.exists(path):
            raise JournalError(
                "OUTPUT_EXISTS", "Refusing to overwrite an existing CAE artifact: " + path
            )

    session = nxopen.Session.GetSession()
    source = _part_from_result(session.Parts.OpenBaseDisplay(source_path))
    session.Parts.SetWork(source)

    def new_cae_part(template_field: str, application: str, path: str):
        params = session.Parts.FileNew()
        try:
            params.TemplateFileName = _required_capability_text(capability, template_field)
            params.TemplatePresentationName = _required_capability_text(
                capability, "presentation"
            )
            params.UseBlankTemplate = False
            params.ApplicationName = application
            params.Units = nxopen.Part.Units.Millimeters
            params.RelationType = ""
            params.UsesMasterModel = "No"
            params.TemplateType = nxopen.FileNewTemplateType.Item
            params.ItemType = ""
            params.Specialization = ""
            params.SetCanCreateAltrep(False)
            params.NewFileName = path
            params.MasterFileName = ""
            params.MakeDisplayedPart = True
            params.DisplayPartOption = nxopen.DisplayPartOption.AllowAdditional
            return _part_from_result(params.Commit())
        finally:
            params.Destroy()

    fem = new_cae_part("fem_template", "CaeFemTemplate", fem_path)
    requested_tags = {int(tag) for tag in geometry["body_tags"]}
    source_bodies = [body for body in list(source.Bodies) if int(body.Tag) in requested_tags]
    if len({int(body.Tag) for body in source_bodies}) != len(requested_tags):
        raise JournalError(
            "BINDING_NOT_CONFIRMED", "Not every confirmed body tag exists in the source part"
        )

    creation = fem.NewFemCreationOptions()
    synchronize = fem.NewFemSynchronizeOptions()
    try:
        synchronize.SynchronizePointsFlag = False
        synchronize.SynchronizeCoordinateSystemFlag = False
        synchronize.SynchronizeLinesFlag = False
        synchronize.SynchronizeArcsFlag = False
        synchronize.SynchronizeSplinesFlag = False
        synchronize.SynchronizeConicsFlag = False
        synchronize.SynchronizeSketchCurvesFlag = False
        synchronize.SynchronizeDplaneFlag = False
        creation.SetCadData(source, None)
        creation.SetGeometryOptions(
            nxopen.CAE.FemCreationOptions.UseBodiesOption.SelectedBodies,
            source_bodies,
            synchronize,
        )
        creation.SetSolverOptions(
            _required_capability_text(capability, "solver"),
            _required_capability_text(capability, "analysis_type"),
            nxopen.CAE.BaseFemPart.AxisymAbstractionType.NotSet,
        )
        creation.SetDescription(["Verified PERF CAE container for " + case_id])
        creation.SetMorphingFlag(False)
        creation.SetCyclicSymmetryData(False, nxopen.CoordinateSystem.Null)
        fem.FinalizeCreation(creation)
        fem.Save(
            nxopen.BasePart.SaveComponents.FalseValue,
            nxopen.BasePart.CloseAfterSave.FalseValue,
        )
    finally:
        synchronize.Dispose()
        creation.Dispose()

    sim = new_cae_part("sim_template", "CaeSimTemplate", sim_path)
    sim.FinalizeCreation(fem, 0, [])
    solution_title = ""
    create_solution = request.get("create_solution", False)
    if not isinstance(create_solution, bool):
        raise JournalError("MANIFEST_INVALID", "create_solution must be boolean")
    if create_solution:
        solution_title = _required_capability_text(capability, "solution_title")
        sim.Simulation.CreateSolution(
            _required_capability_text(capability, "solver"),
            _required_capability_text(capability, "analysis_type"),
            _required_capability_text(capability, "solution_type"),
            solution_title,
            nxopen.CAE.SimSimulation.AxisymAbstractionType.NotSet,
        )
    sim.Save(
        nxopen.BasePart.SaveComponents.FalseValue,
        nxopen.BasePart.CloseAfterSave.FalseValue,
    )
    for path in (fem_path, sim_path):
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            raise JournalError("NX_API_ERROR", "NX did not commit artifact: " + path)
    return {
        "fem_path": fem_path,
        "sim_path": sim_path,
        "fem_sha256": file_digest(fem_path),
        "sim_sha256": file_digest(sim_path),
        "solution_title": solution_title,
        "source_body_tags": sorted(int(body.Tag) for body in source_bodies),
    }


def execute(request: dict, *, nxopen=None) -> dict:
    identity = verify_setup_manifest(request)
    # Capability gates deliberately precede importing or calling NXOpen.
    for field in (
        "solver",
        "analysis_type",
        "solution_type",
        "solution_title",
        "fem_template",
        "sim_template",
        "presentation",
    ):
        _required_capability_text(identity["capability"], field)
    require_online_execution(request)
    if nxopen is None:
        try:
            import NXOpen as nxopen_module
        except ImportError as exc:
            raise JournalError(
                "NX_API_UNSUPPORTED", "NXOpen is available only inside a licensed NX process"
            ) from exc
        nxopen = nxopen_module
    try:
        artifacts = _create_containers(identity, request, nxopen)
    except JournalError:
        raise
    except (AttributeError, TypeError) as exc:
        raise JournalError(
            "NX_API_UNSUPPORTED",
            "The verified NX 2606 container API does not match this runtime: %s" % exc,
            not_done=["FEM/SIM container creation"],
        ) from exc
    payload = {
        "ok": True,
        "state": "container_created",
        **identity_fields(identity),
        "source_part": os.path.abspath(identity["binding"]["source_geometry"]["source_part"]),
        "solver": _required_capability_text(identity["capability"], "solver"),
        "analysis_type": _required_capability_text(identity["capability"], "analysis_type"),
        "solution_type": _required_capability_text(identity["capability"], "solution_type"),
        **artifacts,
        "not_done": [
            "setup material and mesh",
            "setup loads, boundary conditions and output requests",
            "native solve",
            "native result extraction and export",
        ],
    }
    return payload


def run(request: dict, *, nxopen=None) -> dict:
    try:
        return execute(request, nxopen=nxopen)
    except JournalError as exc:
        return exc.response()
    except Exception as exc:  # NX exceptions are not consistently typed across releases.
        return error_response(
            "NX_API_ERROR",
            "Container creation failed: %r" % exc,
            details={"traceback": traceback.format_exc()[-2000:]},
            not_done=["FEM/SIM container creation"],
        )


def _emit(payload: dict, response_path: str = "") -> None:
    path = response_path or os.environ.get(RESPONSE_ENV, "")
    if not path:
        raise RuntimeError(RESPONSE_ENV + " is required for the structured response")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, default=str, indent=2)


def journal_main(runner) -> None:
    request_path = os.environ.get(REQUEST_ENV, "")
    response_path = os.environ.get(RESPONSE_ENV, "")
    if not response_path:
        raise RuntimeError(RESPONSE_ENV + " is required")
    if not request_path:
        payload = error_response("REQUEST_INVALID", REQUEST_ENV + " is required")
    else:
        try:
            request = _read_json(request_path, "journal request")
            payload = runner(request)
        except JournalError as exc:
            payload = exc.response()
        except Exception as exc:
            payload = error_response("REQUEST_INVALID", repr(exc))
    _emit(payload, response_path)


def main() -> None:
    journal_main(run)


if __name__ == "__main__":
    main()
