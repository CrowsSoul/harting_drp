# DFM-08 最小壁厚 — Check-Mate 取证

## 1. 出处

- Check-Mate DFM Advisor：**无最小壁厚检查器**（已核对 `dfmadvisor\localization\dfms_*.html` 全量清单与 `NXCheckers.json` 注册表）；
- 同类参考：`checkmate\dfa\checker\sheet_metal\mqc_dfm_check_sheet_metal_thickness.dfa`（板材厚度范围 1–10 mm，仅用于钣金）。

## 2. 判定口径（本项目基线）

- 阈值 = 材料最小壁厚表查值（`table(params.material_min_wall_thickness_mm, meas.material)`）；
- 判定：`meas.thickness < 材料下限` → 报；`< 材料下限 × critical_wall_ratio` → 升级 P1；
- 材料不在表内 = 缺数据，跳过不猜。

## 3. 我们的实现

规则 `R-DFM-08` 两个 case（首个命中生效）：P1（临界倍率）在前，默认 severity 在后；
`suggestion`/`note` 沿用旧路径文案；几何层 `wall_samples` 不变。

## 4. 差异清单

Check-Mate 无对应项，无法做黑盒差分；本项目阈值来自甲方工艺基线（`source_standard` 已注明）。
若后续甲方提供注塑 DFM 规则集，按同一模板补证据。

## 5. 置信度

**low（对齐度）** —— 无 Check-Mate 对照；公式与材料表需甲方工艺确认。
