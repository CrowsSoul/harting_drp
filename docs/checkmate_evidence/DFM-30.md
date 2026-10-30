# DFM-30 刀具可达性 — Check-Mate 取证

## 1. 出处

`DESIGN_TOOLS\checkmate\dfmadvisor\localization\dfms_InconvenientToolAccess.html`
（注册表 `NXCheckers.json#dfms_InconvenientToolAccess`）。

## 2. Check-Mate 判定口径

- 识别"从铣削方向或其反方向都不可见"的面区域；
- 参数：`milling_dir` 默认 `(0,0,-1)`；无尺寸阈值。
- 结论：**可见性/可达性判据**，与具体刀具包络无关。

## 3. 我们的实现

- 规则 `R-DFM-30`：`meas.blocker_count > 0` → P2；measured 取包络半径，无阈值。
- 几何（二期占位粗筛）：从孔口沿孔轴伸出包络圆柱（半径 = 孔半径 + `tool_clearance_mm`，
  长 `envelope_length_mm`），与其他零件包围盒相交即遮挡；单零件直接跳过。

## 4. 差异清单

| 项 | Check-Mate | 本项目 | 处理 |
|---|---|---|---|
| 判据 | 面可见性（几何可见域） | 包围盒级包络遮挡 | 粗筛不同实现，方向一致 |
| 范围 | 单零件全部面 | 只查跨零件孔口遮挡 | 二期升级为包络扫掠 + 实体求交 |
| 阈值 | 无 | 包络半径/长度参数 | 项目增值 |

## 5. 置信度

**low** —— 语义方向一致但实现粒度差距大；黑盒差分需 NX 实体可见性结果配合。
