# DFM-14 倒扣 — Check-Mate 取证

## 1. 出处

| 通道 | 位置（本机安装，不入库） |
|---|---|
| 官方文档 | `DESIGN_TOOLS\checkmate\dfmadvisor\localization\dfms_UndercutDetection.html` |
| 规则文件 | `TOOLING_BASE\dfa\mw_check_undercut_area.dfa`（Mold Wizard 倒扣面积检查） |

## 2. Check-Mate 判定口径

- `dfms_UndercutDetection`：识别倒扣区域包围的面；若倒扣区域在 `draft_dirs`
  （默认 `(0,0,1)`、`(0,0,-1)`）任一方向上**部分不可见** → 失败；
- `mw_check_undercut_area.dfa`：按开模方向统计倒扣面并报告面积；
- 均无"最小倒扣深度"阈值。

## 3. 我们的实现

规则 `R-DFM-14` 两个 case：
1. `meas.has_depth == 1 and meas.depth_mm >= params.min_undercut_depth_mm` → 报（measured=深度）；
2. `meas.has_depth == 0` → 报（无 measured，只给阈值）。
默认 `min_undercut_depth_mm = 0.0`（几何层只筛有记录且非设计意图的倒扣）。

## 4. 差异清单

| 项 | Check-Mate | 本项目 | 处理 |
|---|---|---|---|
| 判定对象 | 几何可见性推倒扣 | 上游倒扣特征记录（方向/深度） | 粗筛：无记录即跳过，不自推 |
| 深度门槛 | 无 | 参数（默认 0，即全部报） | 项目增值 |

## 5. 置信度

**medium** —— 文档证清 NX 口径；本项目依赖上游特征记录，暂不做几何反推。
