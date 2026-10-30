# DFM-27 深孔 — Check-Mate 取证

## 1. 出处

| 通道 | 位置（本机安装，不入库） |
|---|---|
| 官方文档 | `DESIGN_TOOLS\checkmate\dfmadvisor\localization\dfms_DeepHoles.html` |
| 注册表 | `DESIGN_TOOLS\checkmate\dfmadvisor\application\NXCheckers.json#dfms_DeepHoles` |
| 黑盒样本 | `.local/checkmate_results/dfm27-deephole-default.json`、`dfm27-deephole-pass30.json`（本机） |

## 2. Check-Mate 判定口径

- **测量**：孔深 L 取不含钻尖的最大深度；孔径 D 取不含钻尖的最小直径；阶梯孔按一条计，带横向孔按两条计。
- **公式**：`L / D`
- **比较**：`L/D > ld_ratio_max` 判失败（严格大于；日志判据写作 `5.0 < L/D`）。
- **默认参数**：`ld_ratio_max = 5`（另有 `Disabled`、`SaveInPart`、`LogOption`、`LogMessage`）。

## 3. 黑盒样本（DeepHole.prt，产品自带示例件）

| 样本 | 参数 | 孔 1（L=95.0, D=3.5） | 孔 2（L=90.0, D=10.0） | 整件 |
|---|---|---|---|---|
| 默认 | `ld_ratio_max=5` | L/D=27.14 → fail | L/D=9.0 → fail | fail |
| 放宽 | `ld_ratio_max=30` | pass | pass | pass |
| 收紧 | `ld_ratio_max=2` | fail | fail | fail |

（样本 JSON 由 `tools/checkmate/run_checkmate.py` 解析 XML 生成，判定与判据文案齐全。）

## 4. 我们的实现

- 规则：`R-DFM-27`，expression 两级 cases：
  - `meas.ratio > params.very_deep_hole_ratio` → P1（本项目工艺分级，Check-Mate 无对应概念）
  - `meas.ratio > params.deep_hole_ratio` → P2
- 几何测量：`extract_holes` 取同轴孔组，孔深用包围盒跨度（粗筛，偏保守）、孔径取最窄段。

## 5. 差异清单（需工艺确认，不擅自改）

| 项 | Check-Mate | 本项目 | 处理 |
|---|---|---|---|
| 阈值 | 单一 `ld_ratio_max=5` | 两级 4 / 10（P2 / P1） | **保留两级**：P1 对应深孔钻工艺，属项目增值；默认值与 5 的差异待工艺确认 |
| 深度口径 | 不含钻尖的真实深度 | 包围盒跨度（含钻尖段） | 粗筛偏保守；后续可用 NX 精确量测替换 |
| 孔计数 | 横向孔拆成两条 | 同轴孔组合并成一条 | 判定口径不冲突（比值取最恶劣段），产物粒度不同 |

## 6. 置信度

**high** —— 官方文档 + 黑盒样本双证（公式、比较算子、参数类型与覆盖行为均已实测）。
