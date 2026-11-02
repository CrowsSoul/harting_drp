# DFM-28 深窄槽 — Check-Mate 取证

## 1. 出处

| 通道 | 位置（本机安装，不入库） |
|---|---|
| 官方文档 | `DESIGN_TOOLS\checkmate\dfmadvisor\localization\dfms_SlotsDeepAndNarrow.html` |
| 注册表 | `DESIGN_TOOLS\checkmate\dfmadvisor\application\NXCheckers.json#dfms_SlotsDeepAndNarrow` |

## 2. Check-Mate 判定口径

- **识别**：两块平行平面，法向垂直于铣削方向且相对，之间无遮挡。
- **测量**：槽深 D = 槽壁最高点到最低点的距离；槽宽 W = 两平行平面间距。
- **公式**：`D / W`
- **比较**：`D/W > depth_width_ratio_max` 判失败。
- **默认参数**：`depth_width_ratio_max = 4`；另 `milling_dir` 默认 `(0,0,-1)`。

## 3. 黑盒样本

W1 尚未跑（需要带直槽的试验件；W2 用 `f_slot_sweep` 试验件补齐）。
判定公式与算子来自官方文档，参数默认值已核对。

## 4. 我们的实现

- 规则：`R-DFM-28`，单 case：`meas.ratio > params.deep_slot_ratio` → P2。
- 几何测量：`extract_slots` 用对置内壁 + 共同槽底识别直槽，深度取包围盒跨度。

## 5. 差异清单

| 项 | Check-Mate | 本项目 | 处理 |
|---|---|---|---|
| 阈值 | 4 | 3 | 保留 3（更严，工艺经验值），差异待工艺确认 |
| 槽深口径 | 最高点到最低点 | 槽壁沿槽底法向跨度 | 粗筛近似，判定方向一致 |

## 6. 置信度

**medium** —— 官方文档证口径；黑盒样本待 W2 试验件补齐后升 high。
