# DFM-02 最小间隙 — Check-Mate 取证

## 1. 出处

- Check-Mate DFM Advisor **无"零件最小间隙"检查器**；
- 参考：`DESIGN_TOOLS\checkmate\dfa\checker\assemblies\mqc_check_assembly_clearance_analysis.dfa`
  （装配间隙分析，面向 DFA 场景）。

## 2. 判定口径（本项目基线）

- 零件两两之间取最小间隙（NX 精确测距优先，否则包围盒距离下界）；
- `gap ≤ min_clearance_mm + 1e-9` → 报；精确测距用规则 severity，包围盒粗筛降为 P3。

## 3. 我们的实现

规则 `R-DFM-02` 两个 case（按 `meas.precise` 分支）：
1. 精确：`meas.precise == 1 and meas.gap_mm <= params.min_clearance_mm + 1e-9` → 规则 severity；
2. 粗筛：`meas.precise == 0 and ...` → P3。

## 4. 差异清单

无 Check-Mate 直接对照项；默认 0.3 mm 为项目基线，精确/粗筛分级为项目增值。

## 5. 置信度

**low（对齐度）** —— 无对照；公式与阈值待工艺确认。
