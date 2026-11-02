# DFM-13 拔模角 — Check-Mate 取证

## 1. 出处

| 通道 | 位置（本机安装，不入库） |
|---|---|
| 官方文档 | `DESIGN_TOOLS\checkmate\dfmadvisor\localization\dfms_MinimumDraftAngle.html` |
| 规则文件 | `TOOLING_BASE\dfa\mw_check_draft_angle.dfa`（Mold Wizard） |

## 2. Check-Mate 判定口径

- `dfms_MinimumDraftAngle`：按腔/芯/竖直/过渡面分类后逐采样点测拔模角；
  **cavity 最小 2°、core 最小 1°**（`cavity_dir` 默认 `(0,0,1)`）；
- `mw_check_draft_angle.dfa`：面法向与开模方向夹角小于 `draft_angle`（**默认 3.0°**）即报；
  另有 `cross_angle`（默认 5.0°）与开模方向参数。

## 3. 我们的实现

规则 `R-DFM-13`：`meas.angle_deg < params.min_draft_angle_deg - params.angle_tolerance_deg`；
默认 `min_draft_angle_deg = 0.5`、`angle_tolerance_deg = 1e-6`（近似"小于 0.5° 即报"）。
几何层按平面外法向与统一开模方向计算，不做腔/芯分类。

## 4. 差异清单

| 项 | Check-Mate | 本项目 | 处理 |
|---|---|---|---|
| 阈值 | 2°（腔）/1°（芯）/3°（Mold Wizard） | 0.5° | 差异显著，待工艺确认（我方松） |
| 分类 | 腔/芯自动分类 | 统一开模方向 | 粗筛；方向可配 |
| 容差 | 无显式容差参数 | `angle_tolerance_deg` | 项目增值 |

## 5. 置信度

**medium** —— 文档已核对；阈值差异需工艺确认。
