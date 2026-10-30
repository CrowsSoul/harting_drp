# DFM-26 冲压凸台高度 — Check-Mate 取证

## 1. 出处

`DESIGN_TOOLS\checkmate\dfmadvisor\localization\dfms_EmbossmentMaximumDepth.html`
（注册表 `NXCheckers.json#dfms_EmbossmentMaximumDepth`）。

## 2. Check-Mate 判定口径

- 识别凸/凹冲压凸台（有平端面且背面有对应特征），测端面到基面的法向深度 D；
- `D/T > height_thickness_ratio_max`（**默认 5**）→ 失败；
- 只有**上限**，没有"过矮"下限。

## 3. 我们的实现

规则 `R-DFM-26` 两个 case：
1. `meas.height < params.min_boss_height_ratio * meas.thickness - 1e-9` → 报（过矮）；
2. `meas.height > params.max_boss_height_ratio * meas.thickness + 1e-9` → 报（过高）。
默认区间 `[0.6, 1.5]`；几何层取圆柱面包围盒轴向跨度（粗筛）。

## 4. 差异清单（口径级差异）

| 项 | Check-Mate | 本项目 | 处理 |
|---|---|---|---|
| 判据 | `D/T > 5` | `h/t ∈ [0.6, 1.5]` | **上限差 3 倍以上**，且本项目有下限；需工艺确认 |
| 测量 | 端面到基面法向距离 | 圆柱面包围盒轴向跨度 | 粗筛近似 |

## 5. 置信度

**low（对齐度）** —— NX 判据与阈值已核实，但与我方区间口径差异大。
