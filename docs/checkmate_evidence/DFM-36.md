# DFM-36 角度铣削面 — Check-Mate 取证

## 1. 出处

`DESIGN_TOOLS\checkmate\dfmadvisor\localization\dfms_AngularMillingFaces.html`
（注册表 `NXCheckers.json#dfms_AngularMillingFaces`）。

## 2. Check-Mate 判定口径

- 识别型腔底面（垂直铣削方向的平面）与凹连接侧壁；
- 测量**铣削角 A**：铣削轴与侧壁的夹角（垂直为 0°，倒扣为负）；
- 判定：斜面/斜底型腔 → 失败（需多轴加工），无角度阈值参数；
- 参数：`milling_dir` 默认 `(0,0,-1)`。

## 3. 我们的实现

- 规则 `R-DFM-36`：
  `abs(meas.angle_deg - nearest(meas.standard_angles_deg, meas.angle_deg)) > params.angle_tolerance_deg` → 报；
  threshold = 最近标准角；标准系列默认 0/30/45/60/90°。
- 几何：以最大平面为基准面，逐平面取与基准法向的锐角（面积 ≥ `min_face_area_mm2`，倒角面除外）。

## 4. 差异清单

| 项 | Check-Mate | 本项目 | 处理 |
|---|---|---|---|
| 判据 | 铣削轴 vs 侧壁夹角（非 0° 即斜面） | 面法向 vs 基准法向 → 到标准角系列最近元 | 本项目更宽容（标准角视为可加工） |
| 阈值 | 无 | ±1° 容差 + 标准角系列 | 项目增值 |

## 5. 置信度

**medium** —— 文档证清 NX 的口径；本项目为工程化变体，需工艺确认标准角系列。
