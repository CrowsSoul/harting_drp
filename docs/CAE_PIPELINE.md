# PERF CAE 流水线

## 目标与边界

PERF-01 使用 Simcenter 3D 稳态固体电热（`thermal_with_joule`）工况，PERF-02
使用 NX Nastran SOL 401 多步非线性接触工况。流水线负责参数化、拓扑绑定、执行编排、
结果证据和校准认证；本地公式始终只作为筛查值及求解结果的交叉校核。

当前交付为**离线联调实现**：工况、manifest、状态机、结果契约和测试可以离线验证，
但 NX 2606 的 journal/API 尚未在正式授权环境完成联调。没有能力验证、工程师确认、
原生求解结果及网格证据时，不得声称已求解或已认证。

FloEFD 目前仅提供 PERF-01 的环境探测、工程交接单和统一结果回填，不包含 COM/API
自动建案或自动求解。

## 阶段状态

```text
prepare
  -> setup
  -> solve
  -> export
  -> ingested
  -> calibrated
  -> certified
```

`prepare/setup/solve/export` 的详细状态记录在每个工况的 `run_state.json`。文件存在、
FEM/SIM 同时存在或进程返回 0 都不能单独证明求解成功：

- `setup` 成功需要容器和完整设置响应；
- `solve` 成功需要成功响应及原生结果文件；
- `export` 成功需要通过身份、收敛、输出和单位校验的结果契约；
- 修改 setup、binding 或能力映射后必须重新 `prepare`，下游结果随之失效；
- 重跑 `setup`/`solve` 会清空后续阶段的状态和产物记录，失败或离线阻断不会保留旧的成功状态；
- FEM/SIM、原生结果和 `solver_result` 文件名包含稳定的 `setup_id`，重新 `prepare` 不会因旧产物触发 `OUTPUT_EXISTS`。

## 两类工况的物理约定

### PERF-01：稳态电热

- 模式为 `thermal_with_joule`，不是流固耦合 `Coupled Thermal-Flow`；
- 入口端面施加电流，出口端面为 0 V；
- 材料包含导热率、密度、比热和温度相关电阻率；
- 暴露面定义对流、辐射、环境温度及发射率；
- 求解器必须输出最高温度、温升、电阻、焦耳热和电压降。

纯热结果或本地公式不得补齐电阻、电压降和焦耳热并冒充电热求解输出。

### PERF-02：非线性接触

- 簧片长度沿 X、宽度沿 Y、厚度及法向过盈沿 Z；
- 根部 `x=0` 固定，目标具有由 `lead_angle_deg` 定义的斜面；
- 目标初始位于非穿透位置，沿 -X 建立接触并形成过盈，再沿 +X 拔出；
- 法向过盈 `normal_overlap_mm` 与 X 向插入行程 `insertion_stroke_mm` 是不同物理量；
- 首轮标定使用一个簧片和一个接触对，公式预期同样按单触点归一化；
- SOL 401 包含 `establish_contact`、`insert`、`withdraw` 三个载荷步；
- 必须保存各步收敛、反力、接触法向力、穿透和等效应力证据。

## 目录约定

```text
runtime/
  perf_cae_batch.json
  perf_cae_workspace/
    index.json
    PERF01-ET-0001/
      case.json
      geometry_request.json
      geometry_response.json
      bindings.json
      setup_manifest.json
      run_state.json
      setup_request.json
      setup_response.json
      solve_response.json
      export_response.json
      source.prt
      PERF01-ET-0001.<setup_id>.fem
      PERF01-ET-0001.<setup_id>.sim
      native_result.<setup_id>.json
      solver_result.<setup_id>.json
  perf_solver_results/
  perf_solver_records.json
  perf_calibration.md
  perf_certification.md
```

## 离线准备

生成确定性参数矩阵及每工况目录：

```powershell
python -m nxdrp.checkers.performance.cae_batch generate --count 20 --out runtime/perf_cae_batch.json
python -m nxdrp.checkers.performance.cae_batch materialize --batch runtime/perf_cae_batch.json --out-dir runtime/perf_cae_workspace
```

几何 journal 在创建参数化试验件后会返回确定性的 body/face 角色及 tags。
`cae_bindings.apply_geometry_response()` 只将它们填为 `proposed`；工程师检查几何后，
必须显式调用确认操作并记录审核人和 geometry-response digest。代码不会把猜测的面角色
自动标记为 `confirmed`。

确认后生成设置清单和运行状态：

```powershell
python -m nxdrp.checkers.performance.cae_orchestrator prepare `
  --case-dir runtime/perf_cae_workspace/PERF01-ET-0001 `
  --nx-release "NX 2606.3002" `
  --batch-id PERF-CAE-20261030-20
```

`--batch-id` 可省略：此时从工况目录的父级 `index.json` 读取所属批次，避免生成
`batch_id` 为空、无法回填认证的结果。

不带 `--online` 的执行请求只记录阻断原因，不启动 NX：

```powershell
python -m nxdrp.checkers.performance.cae_orchestrator run `
  --case-dir runtime/perf_cae_workspace/PERF01-ET-0001 `
  --stage setup
```

## 后续授权环境的在线联调

只有精确 NX release 的能力映射为 `verified`、绑定已确认且显式传入 `--online` 后，
编排器才会调用 journal。顺序为：

1. `create_simcenter_case.py` 校验源 PRT 摘要，创建并关联 FEM/SIM，并在 setup 请求中注册 solution；
2. `setup_simcenter_case.py` 设置材料、网格、边界/接触、载荷步及输出请求；
3. `solve_simcenter_case.py` 提交求解并返回原生 deck/result 和日志；
4. `export_simcenter_results.py` 按版本化结果键导出 `solver_result.<setup_id>.json`。

未知 NX 版本、未验证 API、未知原生结果键或不匹配的 solution mode 均返回
`CAPABILITY_UNVERIFIED` / `NX_API_UNSUPPORTED`，不允许用相近名称继续。

## FloEFD 交接

```powershell
python -m nxdrp.checkers.performance.floefd_handoff `
  --case runtime/perf_cae_workspace/PERF01-ET-0001/case.json `
  --binding runtime/perf_cae_workspace/PERF01-ET-0001/bindings.json `
  --out runtime/perf_cae_workspace/PERF01-ET-0001/floefd_handoff.json
```

交接单包含材料、温度相关电阻率、电流/接地、对流/辐射、网格及局部细化、探针、
目标单位、能量平衡和网格研究要求。`automation_supported=false`，工程师后续按同一
`perf_solver_result.schema.json` 回填真实结果。

## 结果接入、校准与认证

```powershell
python -m nxdrp.checkers.performance.cae_batch ingest --batch runtime/perf_cae_batch.json --results runtime/perf_solver_results --out runtime/perf_solver_records.json
python -m nxdrp.checkers.performance.cae_batch report --batch runtime/perf_cae_batch.json --records runtime/perf_solver_records.json --out runtime/perf_calibration.md
python -m nxdrp.checkers.performance.cae_batch certify --batch runtime/perf_cae_batch.json --records runtime/perf_solver_records.json --out runtime/perf_certification.md
```

接入会检查 batch/case、模型、setup、binding 和原生结果身份，以及全部必需输出、单位、
收敛和残差。认证还要求：

- PERF-01、PERF-02 各至少 20 条可认证样本；
- 关键公式输出的中位相对误差不超过 5%；
- 公式与求解器判定一致率不低于 95%；
- 每项满足自己的网格、能量平衡和接触穿透要求；
- 结果来源为真实求解且许可证具备生产认证资格。

`unverified`、`cae_smoke`、`smoke_fixture` 和 evaluation 结果不具备生产认证资格；
records 中混入 smoke 数据时，该文件不能用于 `certified` 结论。

## 当前未完成的真实验收

1. 在正式授权 NX 2606 环境验证几何、材料、网格、接触、Solve 和结果 API；
2. 工程师确认材料 TDS、实体及各边界面；
3. 至少走通一个 PERF-01 和一个 PERF-02 原生求解及导出；
4. 完成粗/中/细网格和收敛研究；
5. 扩展至每项至少 20 个正式授权样本，再生成校准与认证报告。
