# DFM-07 紧固件啮合长度 — Check-Mate 取证

## 1. 出处

`DESIGN_TOOLS\checkmate\dfmadvisor\localization\dfms_FastenerEngagement.html`
（注册表 `NXCheckers.json#dfms_FastenerEngagement`）。

## 2. Check-Mate 判定口径

- `engagement_length / nominal_diameter < min_eng_len_diam_ratio`（**默认 1.5**）→ 失败。

## 3. 我们的实现

规则 `R-DFM-07`：
`meas.engagement_ratio < if(meas.is_soft == 1, params.engagement_ratio_plastic, params.engagement_ratio_steel) - 1e-9`；
默认钢 1.0、塑料/铝 1.5（材料分类在 checker 里按关键字）。

## 4. 差异清单

| 项 | Check-Mate | 本项目 | 处理 |
|---|---|---|---|
| 比值 | 统一 1.5 | 钢 1.0 / 软材料 1.5 | 塑料/铝与 NX 默认一致；钢更松，待工艺确认 |
| 数据 | 几何自动测量 | 上游紧固件测量记录 | 粗筛 |

## 5. 置信度

**medium** —— 公式与默认值已核对；钢件阈值差异需工艺确认。
