# DFM-38 孔的入刀/出刀面 — Check-Mate 取证

## 1. 出处

`DESIGN_TOOLS\checkmate\dfmadvisor\localization\dfms_EntryExitSurfaceForHoles.html`
（注册表 `NXCheckers.json#dfms_EntryExitSurfaceForHoles`）。

## 2. Check-Mate 判定口径

- 识别孔的入刀/出刀边；
- 判定：入刀/出刀边的**边类型不是圆弧（Arc）→ 失败**（斜切/非圆孔口导致钻头侧向阻力）；
- 无尺寸/角度阈值参数。

## 3. 我们的实现

- 规则 `R-DFM-38`：`meas.angle_deg > params.max_entry_angle_deg`（默认 5°）→ P2；
- 几何：孔口面法向与孔轴的锐角；孔口在曲面上（无法向）暂不判定。

## 4. 差异清单（口径级差异）

| 项 | Check-Mate | 本项目 | 处理 |
|---|---|---|---|
| 判据 | 入/出刀边是否为圆弧 | 孔口面与孔轴夹角 > 5° | 相关但不同：NX 看边形状，我方看法向夹角 |
| 曲面孔口 | 按边类型判 | 暂不判定 | 缺数据跳过 |
| 阈值 | 无 | 5° | 项目增值 |

## 5. 置信度

**low（对齐度）** —— NX 判据（边类型）与我方（面法向夹角）不同；需工艺确认是否补充边类型判据。
