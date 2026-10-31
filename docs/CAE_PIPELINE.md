# PERF CAE 流水线

## 状态机

```text
batch_ready
  -> geometry_ready
  -> simcenter_container_ready
  -> mesh_ready
  -> boundary_conditions_ready
  -> solver_ready
  -> solved
  -> ingested
  -> calibrated
  -> certified
```

当前代码自动完成 `batch_ready`、参数化 PRT、FEM/SIM 容器请求、结果接入和
校准/认证报告。网格、材料、接触、电热边界条件、求解和结果导出需要有效授权
环境及具体产品模型。

## 目录约定

```text
runtime/
  perf_cae_batch.json
  perf_cae_workspace/
    index.json
    PERF01-ET-0001/
      case.json
      geometry_request.json
      simcenter_actions.json
      bindings.json
      source.prt
      PERF01-ET-0001.fem
      PERF01-ET-0001.sim
      solver_result.json
  perf_solver_results/
  perf_solver_records.json
  perf_calibration.md
  perf_certification.md
```

## NX 创建流程

1. `cae_batch generate` 生成确定性参数矩阵；
2. `cae_batch materialize` 创建每个工况的工作目录；
3. `geometry-request` 生成 NX 几何 journal 请求；
4. `nx_geometry_runner` 生成导体圆柱或接触梁试验件；
5. `solver_case` 生成 FEM/SIM 容器请求；
6. `nx_cae_runner` 创建关联的 `.fem` 和 `.sim`；
7. 在 Simcenter 3D 中完成网格、材料、LBC、接触/电热工况和 Solve；
8. 按 `perf_solver_result.schema.json` 导出结果；
9. `cae_batch ingest` 接收结果；
10. `cae_batch report` 和 `cae_batch certify` 生成校准及认证报告。

`bindings.json` 必须由工程师确认以下内容后才能从 `bindings_incomplete` 进入
`ready_for_simcenter`：

- 源 PRT、模型摘要和实体标签；
- 各边界面角色及 face IDs；
- 材料牌号和完整物性字段；
- 电热或结构载荷；
- PERF-02 的接触源面、目标面、摩擦、罚刚度和搜索距离；
- 每个结果输出对应的仿真查询。

## 认证门禁

- 每一结果必须为 `converged`；
- `solver.license_mode` 必须为正式授权类型；
- PERF-01、PERF-02 各至少 20 条；
- 公式中位相对误差不超过 5%；
- 公式与求解器判定一致率不低于 95%；
- 每条结果必须有网格敏感性证据，默认变化不超过 3%；
- 不满足条件的批次状态保持 `not_ready`。

## 当前阶段

已生成 40 个参数工况并建立工作区。尚未在正式授权环境中执行几何、FEM/SIM、
网格、LBC 和 Solve，因此状态仍是 `ready_for_geometry`，不能标记 `certified`。
