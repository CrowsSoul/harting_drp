# DFM-32 底部圆角一致性 — Check-Mate 取证

## 1. 出处

`DESIGN_TOOLS\checkmate\dfmadvisor\localization\dfms_InconsistentBottomRadius.html`
（注册表 `NXCheckers.json#dfms_InconsistentBottomRadius`）。

## 2. Check-Mate 判定口径

- 识别与型腔底面平滑连接的内凹圆角；
- 测量每个底部圆角的**最小与最大半径**，半径不一致 → 失败（保证尺寸精度、减少换刀）；
- 参数：`milling_dir` 默认 `(0,0,-1)`；无半径阈值。

## 3. 我们的实现

- 规则 `R-DFM-32`：`meas.distinct_count > params.max_distinct_radii` → P2；
  measured = 半径种类数，threshold = 允许种类数（默认 3）。
- 几何：零件内全部回转圆角面半径聚类（容差 `cluster_tolerance_mm`）后计数。

## 4. 差异清单

| 项 | Check-Mate | 本项目 | 处理 |
|---|---|---|---|
| 判据 | 底部圆角半径是否一致（逐特征） | 全零件圆角种类数上限 | 项目更严格、可配置；两者都服务"减少非标换刀" |
| 范围 | 仅型腔底部圆角 | 全部回转圆角（含顶边） | 保留（与 DFM-33 配合） |
| 阈值 | 无 | `max_distinct_radii=3` | 项目增值 |

## 5. 置信度

**medium** —— 官方文档证语义（一致性判据）；具体计数规则是项目口径。
