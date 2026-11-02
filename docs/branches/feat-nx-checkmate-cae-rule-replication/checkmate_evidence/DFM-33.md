# DFM-33 顶部圆角 — Check-Mate 取证

## 1. 出处

| 通道 | 位置（本机安装，不入库） |
|---|---|
| 官方文档 | `DESIGN_TOOLS\checkmate\dfmadvisor\localization\dfms_TopFillets.html` |
| 官方文档 | `DESIGN_TOOLS\checkmate\dfmadvisor\localization\dfms_StandardCornerRadius.html` |
| 注册表 | `DESIGN_TOOLS\checkmate\dfmadvisor\application\NXCheckers.json#dfms_TopFillets` |

## 2. Check-Mate 判定口径

- **`dfms_TopFillets`**：把"垂直于铣削方向的平面"识别为入口面，**入口面上有圆角即判失败**
  （Check-Mate 的设计取向是顶边优先用倒角/斜切，圆角刀具成本高）。参数只有 `milling_dir`（默认 `(0,0,-1)`）。
- **`dfms_StandardCornerRadius`**（半径口径参考）：识别轴线平行铣削方向的**凹圆柱面**，
  半径不在标准半径表内即失败；默认标准半径 `1.0/1.5/2.0/3.0/5.0/10.0 mm`。
- 两者都没有"最小刀尖圆角"这个阈值概念，也没有"顶区范围内缺圆角"的判定。

## 3. 黑盒样本

W1 未跑：`dfms_TopFillets` 判的是"有圆角"而非"缺/小圆角"，与我们的语义不同，
需先由工艺确认要对齐哪一侧口径，再用参数化试验件做差分。

## 4. 我们的实现

- 规则：`R-DFM-33`，两个 case + 一条豁免：
  - `meas.sharp_edge_count > 0` → P2（顶区锐边：两平面直接相交、无圆角）；
  - `meas.radius < params.min_top_fillet_mm` → P2（顶边圆角小于最小刀尖圆角，默认 0.5 mm）；
  - `exceptions`: `meas.exempt_edge == 1` → skip（模型 meta `sharp_edge_exempt_parts` 声明装配贴合面）。
- 顶区定义：沿 `up_direction` 上部 (1 - `top_region_ratio`) 跨度，粗筛按建模方向。

## 5. 差异清单（**口径级差异，需工艺拍板**）

| 项 | Check-Mate | 本项目 | 说明 |
|---|---|---|---|
| 判定方向 | 入口面**有**圆角 → 失败（建议改倒角） | 顶区**缺**圆角 / 圆角过小 → 失败 | 方向相反，不是参数差异 |
| 半径基准 | 标准半径表（枚举） | 最小刀尖圆角（阈值） | 可用 `standard_corner_radii` 表替代，属 W2 选项 |
| 顶区范围 | 无此概念 | 上部 25% 带锐边归并 | 项目增值，保留 |

**结论**：DFM-33 不能简单"对齐 Check-Mate"；当前实现保持项目原有工艺口径，
仅把判定公式化、可配置化。差异提交工艺负责人确认后，再决定是否新增"入口面圆角"子判据。

## 6. 置信度

**low（对齐度）** —— 公式与参数来源已核实（文档），但与 Check-Mate 的判定方向不同，
一致率指标不适用于本条，需要工艺确认口径。
