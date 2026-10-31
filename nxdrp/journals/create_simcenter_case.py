# -*- coding: utf-8 -*-
"""在 NX 内创建 Simcenter 3D 结构或 Thermal Flow 分析的 FEM/SIM 容器。

该 journal 只使用 NX 2606 自带模板和公开 NX Open API。它完成：

1. 打开源 CAD 零件；
2. 创建 Metric FEM；
3. 关联源零件和选定实体；
4. 设置 Simcenter Nastran Structural 或 Thermal/Flow 求解环境；
5. 创建关联 SIM；
6. 可选创建 solution；
7. 返回 FEM/SIM 路径和未完成项。

网格、边界条件和求解命令必须由具体 PERF 工况继续定义；本脚本不会把
空分析容器冒充成已完成的接触或电热计算。
"""

from __future__ import annotations

import hashlib
import json
import os
import traceback


REQ = os.environ.get("NXDRP_CAE_REQUEST", "")
RESP = os.environ.get("NXDRP_CAE_RESPONSE", "")


def _emit(payload: dict) -> None:
    if not RESP:
        return
    with open(RESP, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, default=str, indent=2)


def _part_from_result(value):
    return value[0] if isinstance(value, (tuple, list)) else value


def _binding_digest(binding: dict) -> str:
    payload = dict(binding)
    payload.pop("binding_digest", None)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def main() -> None:
    import NXOpen

    with open(REQ, "r", encoding="utf-8") as fh:
        request = json.load(fh)

    binding = None
    binding_path = request.get("bindings_path") or ""
    if binding_path:
        with open(binding_path, "r", encoding="utf-8") as fh:
            binding = json.load(fh)
        if binding.get("binding_digest") != _binding_digest(binding):
            raise ValueError("bindings.json 摘要不一致")
        if request.get("case_id") and binding.get("case_id") != request["case_id"]:
            raise ValueError("bindings.json 的 case_id 与请求不一致")
        request.setdefault("source_part", "")
        if not request["source_part"]:
            request["source_part"] = binding["source_geometry"]["source_part"]
        if not request.get("body_tags"):
            request["body_tags"] = binding["source_geometry"]["body_tags"]

    source_path = os.path.abspath(request["source_part"])
    out_dir = os.path.abspath(request["out_dir"])
    case_id = request.get("case_id") or "PERF-CAE"
    kind = request.get("kind") or "structural"
    create_solution = bool(request.get("create_solution", False))
    mesh_request = request.get("mesh") or {}
    mesh_enabled = bool(mesh_request.get("enabled", False))
    os.makedirs(out_dir, exist_ok=True)

    session = NXOpen.Session.GetSession()
    source = _part_from_result(session.Parts.OpenBaseDisplay(source_path))
    session.Parts.SetWork(source)

    if kind == "structural":
        config = {
            "fem_template": "FemNxNastranMetric.fem",
            "sim_template": "SimNxNastranMetric.sim",
            "presentation": "Simcenter Nastran",
            "solver": "NX NASTRAN",
            "analysis": "Structural",
            "default_solution_type": "Nonlinear Statics",
        }
    elif kind == "thermal":
        config = {
            "fem_template": "FemThermalFlowMetric.fem",
            "sim_template": "SimThermalFlowMetric.sim",
            "presentation": "Simcenter 3D Thermal/Flow",
            "solver": "NX THERMAL / FLOW",
            "analysis": "Coupled Thermal-Flow",
            "default_solution_type": request.get("solution_type", "Thermal"),
        }
    else:
        raise ValueError(f"未知 CAE 类型：{kind}")

    def new_cae_part(template: str, application: str, path: str):
        params = session.Parts.FileNew()
        params.TemplateFileName = template
        params.TemplatePresentationName = config["presentation"]
        params.UseBlankTemplate = False
        params.ApplicationName = application
        params.Units = NXOpen.Part.Units.Millimeters
        params.RelationType = ""
        params.UsesMasterModel = "No"
        params.TemplateType = NXOpen.FileNewTemplateType.Item
        params.ItemType = ""
        params.Specialization = ""
        params.SetCanCreateAltrep(False)
        params.NewFileName = path
        params.MasterFileName = ""
        params.MakeDisplayedPart = True
        params.DisplayPartOption = NXOpen.DisplayPartOption.AllowAdditional
        try:
            return _part_from_result(params.Commit())
        finally:
            params.Destroy()

    fem_path = os.path.join(out_dir, f"{case_id}.fem")
    sim_path = os.path.join(out_dir, f"{case_id}.sim")
    if os.path.exists(fem_path):
        os.remove(fem_path)
    if os.path.exists(sim_path):
        os.remove(sim_path)

    fem = new_cae_part(config["fem_template"], "CaeFemTemplate", fem_path)
    source_bodies = list(source.Bodies)
    requested_tags = {int(tag) for tag in request.get("body_tags", [])}
    if requested_tags:
        source_bodies = [body for body in source_bodies if int(body.Tag) in requested_tags]
    if not source_bodies:
        raise ValueError("源零件没有可关联的实体")

    creation = fem.NewFemCreationOptions()
    synchronize = fem.NewFemSynchronizeOptions()
    for name in (
        "SynchronizePointsFlag",
        "SynchronizeCoordinateSystemFlag",
        "SynchronizeLinesFlag",
        "SynchronizeArcsFlag",
        "SynchronizeSplinesFlag",
        "SynchronizeConicsFlag",
        "SynchronizeSketchCurvesFlag",
        "SynchronizeDplaneFlag",
    ):
        setattr(synchronize, name, False)
    try:
        creation.SetCadData(source, None)
        creation.SetGeometryOptions(
            NXOpen.CAE.FemCreationOptions.UseBodiesOption.SelectedBodies,
            source_bodies,
            synchronize,
        )
        creation.SetSolverOptions(
            config["solver"],
            config["analysis"],
            NXOpen.CAE.BaseFemPart.AxisymAbstractionType.NotSet,
        )
        creation.SetDescription([f"PERF CAE container for {case_id}"])
        creation.SetMorphingFlag(False)
        creation.SetCyclicSymmetryData(False, NXOpen.CoordinateSystem.Null)
        fem.FinalizeCreation(creation)
        fem.Save(
            NXOpen.BasePart.SaveComponents.FalseValue,
            NXOpen.BasePart.CloseAfterSave.FalseValue,
        )
    finally:
        synchronize.Dispose()
        creation.Dispose()

    mesh_info = None
    if mesh_enabled:
        fem_model = fem.BaseFEModel
        mesh_manager = getattr(fem_model, "MeshManager", None) or getattr(fem, "MeshManager", None)
        if mesh_manager is None:
            raise RuntimeError("当前 NX Open FEM 对象没有 MeshManager")
        mesh_builder = mesh_manager.CreateMesh3dTetBuilder(NXOpen.CAE.Mesh3d.Null)
        try:
            mesh_builder.MeshName = mesh_request.get("name") or f"{case_id} Tet Mesh"
            mesh_builder.AutoResetOption = True
            mesh_builder.AutoSizeOption = mesh_request.get("element_size_mm") is None
            if mesh_request.get("element_size_mm") is not None:
                try:
                    mesh_builder.PropertyTable.SetDouble(
                        "ElementSize",
                        float(mesh_request["element_size_mm"]),
                    )
                except Exception as exc:
                    raise RuntimeError(f"设置网格尺寸失败：{exc}") from exc
            cae_bodies = list(fem.Bodies)
            if not cae_bodies:
                raise RuntimeError("FEM 中未找到可网格化 CAEBody")
            mesh_builder.SelectionList.Add(cae_bodies)
            mesh_result = mesh_builder.CommitMesh()
            if hasattr(fem_model, "UpdateFemodel"):
                fem_model.UpdateFemodel()
            fem.Save(
                NXOpen.BasePart.SaveComponents.FalseValue,
                NXOpen.BasePart.CloseAfterSave.FalseValue,
            )
            mesh_info = {
                "name": mesh_builder.MeshName,
                "element_size_mm": mesh_request.get("element_size_mm"),
                "result": str(mesh_result),
            }
        finally:
            mesh_builder.Destroy()

    sim = new_cae_part(config["sim_template"], "CaeSimTemplate", sim_path)
    sim.FinalizeCreation(fem, 0, [])

    solution_name = ""
    if create_solution:
        solution_name = request.get("solution_name") or f"{case_id} Solution"
        sim.Simulation.CreateSolution(
            config["solver"],
            config["analysis"],
            request.get("solution_type") or config["default_solution_type"],
            solution_name,
            NXOpen.CAE.SimSimulation.AxisymAbstractionType.NotSet,
        )
    sim.Save(
        NXOpen.BasePart.SaveComponents.FalseValue,
        NXOpen.BasePart.CloseAfterSave.FalseValue,
    )
    _emit({
        "ok": True,
        "state": "container_created",
        "case_id": case_id,
        "kind": kind,
        "source_part": source_path,
        "fem_path": fem_path,
        "sim_path": sim_path,
        "solver": config["solver"],
        "analysis_type": config["analysis"],
        "solution_name": solution_name,
        "mesh": mesh_info,
        "bindings_path": os.path.abspath(binding_path) if binding_path else "",
        "binding_digest": binding.get("binding_digest", "") if binding else "",
        "source_body_tags": [int(body.Tag) for body in source_bodies],
        "not_done": [
            "material assignment",
            "loads and boundary conditions",
            "solver export and solve",
            "result extraction",
        ] if mesh_enabled else [
            "mesh",
            "material assignment",
            "loads and boundary conditions",
            "solver export and solve",
            "result extraction",
        ],
    })


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        _emit({
            "ok": False,
            "state": "failed",
            "error": repr(exc),
            "traceback": traceback.format_exc()[-2000:],
        })
        raise
