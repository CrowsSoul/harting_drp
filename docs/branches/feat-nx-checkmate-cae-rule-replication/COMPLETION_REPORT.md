# V2 分支任务完成情况报告（DFM 规则复刻 + PERF CAE 复刻）

| 项目 | 内容 |
|---|---|
| 分支 | `feat/nx-checkmate-cae-rule-replication` |
| 当前提交 | `e3e9e81`（与 `origin` 同步） |
| 报告日期 | 2026-10-31 |
| 结论 | **本轮离线可交付范围已全部完成**；现场验收项（依赖甲方环境/正式许可）明确列为后续工作 |
| 详细记录 | DFM 见 `docs/branches/feat-nx-checkmate-cae-rule-replication/CHECKMATE_WORK_STATUS.md`；PERF 见 `docs/branches/feat-nx-checkmate-cae-rule-replication/CAE_PIPELINE.md`、`docs/branches/feat-nx-checkmate-cae-rule-replication/NX_PERF_RULE_EVIDENCE.md` |

---

## 一、一页结论

| 任务线 | 本轮完成 | 现场验收（后续） |
|---|---|---|
| **DFM（Check-Mate）** | 38/38 项公式化；规则模型 v2 + 表达式引擎；38 份证据文档；双跑零差异；边界/单位/舍入单测 | 参数化试验件一致率 ≥95% 报告 |
| **PERF（Simcenter/FloEFD）** | PERF-01/02 公式驱动重构；CAE 离线链路（setup/solve/export、FloEFD 交接、结果契约、认证门禁）；文档与模型卡 | CAE 正式认证（授权许可、每项 ≥20 样本、误差 ≤5%、一致率 ≥95%、网格研究） |
| **工程质量** | 全量 492 项单测通过（1 跳过）；selftest 通过；schema 零漂移；契约收尾完成 | — |

**判定口径**：`需要现场完成的先不做`。本报告把这两类工作标为"范围外"，其余全部视为已完成并附验证证据。

---

## 二、任务目标与验收口径

来源：`CLAUDE.md` 第五节、`docs/V2_PLAN_详细版.md` 主线 C。

- **DFM**：借助 NX Check-Mate 梳理检查规则，把"填参数、比阈值"改成"公式 + 比较规则"，
  并为规则补齐单位、舍入、例外与出处；38 项全部迁移。
- **PERF**：借助 Simcenter 3D / FloEFD 建立电热与结构接触工况，用 AI 梳理求解模型、公式、边界与
  比较规则，重构 PERF-01/02 检查插件；逐条落库并标置信度。
- **验收**：DFM 38 项每条有公式与出处；与 Check-Mate 在试验件上一致率 ≥95%；边界/单位/舍入有单测；
  PERF 模型卡更新、区间预测回归通过。

---

## 三、DFM 完成情况

### 3.1 交付清单

| 交付物 | 位置 | 状态 |
|---|---|---|
| 规则模型 v2（expression/unit/rounding/exceptions/reference） | `nxdrp/contracts/core.py` | ✅ |
| 受限 DSL 表达式引擎（无 eval；单位/函数/失败语义） | `nxdrp/expr/` | ✅ |
| CheckContext.evaluate 集成 | `nxdrp/checkers/base.py` | ✅ |
| 38 项规则双路径迁移 | `nxdrp/checkers/{machining,injection,sheet_metal,assembly,examples}/` | ✅ 38/38 |
| 规则库（含公式、单位、舍入、出处） | `rules/dfm_default.json` v0.9 | ✅ |
| Check-Mate 取证工具（.dfa 解析、黑盒执行、双跑对账） | `tools/checkmate/`、`nxdrp/journals/checkmate_checker.py` | ✅ |
| 规则证据文档 | `docs/branches/feat-nx-checkmate-cae-rule-replication/checkmate_evidence/DFM-01~38.md` + `README.md` + `smoke.md` | ✅ 40 份 |
| 规则模型技术文档 | `docs/branches/feat-nx-checkmate-cae-rule-replication/CHECKMATE_RULE_V2.md` | ✅ |
| 任务进度记录 | `docs/branches/feat-nx-checkmate-cae-rule-replication/CHECKMATE_WORK_STATUS.md` | ✅ |

### 3.2 迁移批次

| 批次 | 范围 | 数量 | 提交 |
|---|---|---|---|
| W1 | 机加示范（DFM-27/28/33）+ 引擎 + 契约 | 3 | `e70e5de` |
| W2 | 机加其余 9 项（DFM-29~32、34~38） | 9 | `5afeb0c` |
| W3 | 注塑 11 项（DFM-08~18） | 11 | `65e687a` |
| W4 | 钣金 8 项（DFM-19~26） | 8 | `e61e845` |
| W5 | 装配 7 项（DFM-01~07） | 7 | `b57da53` |

### 3.3 置信度与差异统计

- **置信度分布**（按证据文档）：high 3 项（DFM-22/27/29）、medium 20 项、low 15 项；
- **Check-Mate 无对应检查器的 8 项**：DFM-02、08、09、10、11、12、15、17
  （注塑壁厚/筋/凸台/抽芯方向在 NX DFM Advisor 中不存在，仅能给出项目基线）；
- **口径级差异（公式或判定方向不同，需工艺拍板）**：
  DFM-05（头隙/插入空间 vs 工具包络）、DFM-16（标准半径 vs 壁厚倍率）、
  DFM-19（0.1t 标准倍数 vs 最小 R/t）、DFM-26（5t 上限 vs 区间）、
  DFM-33（入口面带圆角即失败 vs 缺/小圆角）、DFM-34（有内倒角即失败 vs 非标才报）、
  DFM-35（L/R 比 vs 绝对半径）、DFM-38（边类型 vs 面法向夹角）；
- **主要阈值差异**（同构公式，仅数值不同）：DFM-13（0.5° vs 2°/1°/3°）、
  DFM-20（1.5t vs 3T）、DFM-21（2t vs 3T）、DFM-27（4/10 vs 5）、
  DFM-28（3 vs 4）、DFM-37（1 vs 2 mm）、DFM-07（钢 1.0 vs 1.5）；
- **完全一致**：DFM-22（`D < 1×T`）公式与默认阈值一致。

> **重要**：本轮迁移**未修改任何原项目阈值**（38 项 `params` 与分支起点逐字节一致），
> NX 默认值仅作为差异基准记录，未被采纳。

### 3.4 验证证据

| 验证 | 结果 |
|---|---|
| 全量单测 | **492 项通过 / 1 跳过** |
| DFM v2 专项测试 | 98 项（引擎 51、契约 10、迁移 34、工具 3） |
| 双跑对账 | 13 个 mock 模型 + `bent_sheet` 夹具，38 项**零差异** |
| `python -m nxdrp selftest` | ✅ 通过 |
| 规则库校验 | `RuleBook.validate()` 通过；schema 与生成物零漂移 |
| Check-Mate 黑盒冒烟 | ✅ `dfms_DeepHoles` 可跑、参数可覆盖、XML 判定可解析（`smoke.md`） |

### 3.5 范围外（现场验收）

- **与 Check-Mate 试验件一致率 ≥95% 报告**：目前仅 DFM-27 有真实黑盒样本；
  其余为文档级对照。需要参数化试验件 + 本机/甲方 NX 批量跑 Check-Mate。
  已评估难度与路线：先做 38 项可比性矩阵，再按机加 → 钣金 → 装配 → 注塑分批，
  预计 1.5~3 周（不含工艺口径决策）。

---

## 四、PERF 完成情况

### 4.1 公式驱动重构

| 项 | 内容 |
|---|---|
| 规则库 | `rules/perf_formula_v2.json`（v2.0.0）：输入、变量、求解未知量、判定式、局限、置信度 |
| 执行引擎 | `nxdrp/checkers/performance/rule_engine.py`（受限 DSL，禁用属性/下标/任意函数） |
| 规则绑定 | `rules/dfm_default.json` 的 PERF-01/02 通过 `formula_ref` 指向公式库 |
| PERF-01 | 稳态电热：焦耳热 + 对流 + 辐射 + 温度相关电阻率 + 端部接触电阻，二分法求稳态温度 |
| PERF-02 | 悬臂梁 + 摩擦：`I=bt³/12`、`k=3EI/L³`、正压力、引导角合成插入/拔出力 |
| 判定 | `decisions`（温升 ≥ 45 °C、绝对温度 ≥ 2000 °C、插入力 ≥ 20 N、拔出力 < 1 N） |
| 回归树 | 仅保留 80% 标定区间，不再决定 PASS/FAIL |

### 4.2 CAE 离线链路

- **Simcenter**：几何试验件 journal、FEM/SIM 容器创建、setup/solve/export journal；
- **FloEFD**：PERF-01 工程交接单（`automation_supported=false`）与统一结果回填；
- **结果契约**：`rules/perf_cae_bindings_v1.json`、`perf_cae_cases.json`、结果 schema；
- **认证门禁**：`cae_batch ingest/report/certify`，要求真实授权、已收敛、模型摘要匹配、
  每项 ≥20 样本、中位误差 ≤5%、判定一致率 ≥95%、网格敏感性证据；
- **版本能力映射**：`rules/perf_solver_capabilities_v1.json`，未验证 API 返回 `not_done`。

### 4.3 置信度

- PERF-01/02 `confidence_level = low`（降阶筛查公式，未经 CAE 认证样本校验）；
- 证据级别区分 `cae_solver`（真实求解结果）与 `formula`（本地降阶公式），后者不得对外宣称 NX 结果；
- 原有 `source.confidence`（证据来源级别）保留，与新字段 `confidence_level` 语义分离。

### 4.4 验证证据

| 验证 | 结果 |
|---|---|
| PERF 专项测试 | **107 项通过**（公式引擎、CAE 批量、绑定、能力、结果接入、FloEFD、Simcenter journal） |
| 公式库校验 | `validate_formula_library()` 返回 2 个模型，无错误 |
| 实际检查 | PERF-01/02 输出由公式与判定式产生（温升 103.7 °C、插入力 77.34 N 等） |
| 全量回归 | 492 项通过 / 1 跳过 |

### 4.5 范围外（现场/正式授权）

1. 在正式授权 NX 2606 环境验证几何、材料、网格、接触、Solve 与结果 API；
2. 工程师确认材料 TDS、实体与各边界面；
3. 至少走通一个 PERF-01 和一个 PERF-02 原生求解及导出；
4. 完成粗/中/细网格与收敛研究；
5. 扩展至每项至少 20 个正式授权样本，生成校准与认证报告。

> 当前 Nastran 许可来源为非正式授权，冒烟结果不进入 `cae_solver` 认证数据；
> 公式仍属筛查级。详见 `docs/branches/feat-nx-checkmate-cae-rule-replication/CAE_PIPELINE.md` 与 `docs/branches/feat-nx-checkmate-cae-rule-replication/NX_PERF_RULE_EVIDENCE.md`。

---

## 五、工程质量与合规

| 项 | 状态 |
|---|---|
| 全量单测 | 492 通过 / 1 跳过 |
| `python -m nxdrp selftest` | 通过 |
| schema 生成物漂移 | 无（9 份文档一致） |
| 规则库生成器 | `tools/gen_rules.py` 增量补骨架，不覆盖人工调参与 expression |
| 契约收尾 | schema 重复键已清理；`exceptions` 统一为 `skip: true`（checker 执行型标 `enforced_by: "checker"`） |
| 合规 | 仅提取判定口径；Siemens 原文、黑盒日志、试验件均放 `.local/`（gitignore），未入库 |
| 阈值 provenance | 38 项阈值全部继承自原项目，未采用 NX 默认值 |

---

## 六、遗留事项与建议

| 事项 | 依赖 | 建议 |
|---|---|---|
| DFM 一致率 ≥95% 报告 | 参数化试验件 + Check-Mate 环境 | 先做可比性矩阵，机加 12 项试点（约 1.5–2 周出首版） |
| 38 项差异清单评审 | 工艺负责人 | 优先确认 8 项口径差异与主要阈值差异 |
| PERF CAE 认证 | 正式 SPLM 许可 + 现场 | 按 `CAE_PIPELINE.md` 5 步执行 |
| PERF 置信度升级 | 认证样本 | 认证通过后 low → medium/high |
| `PARAM_SKELETON` 与 JSON 分叉提示 | 无 | 可选的长期清理，不影响运行 |

---

## 七、关键文件索引

| 内容 | 位置 |
|---|---|
| 规则模型 v2 与 DSL | `docs/branches/feat-nx-checkmate-cae-rule-replication/CHECKMATE_RULE_V2.md`、`nxdrp/expr/` |
| DFM 进度与范围 | `docs/branches/feat-nx-checkmate-cae-rule-replication/CHECKMATE_WORK_STATUS.md` |
| 规则证据（38 份） | `docs/branches/feat-nx-checkmate-cae-rule-replication/checkmate_evidence/` |
| Check-Mate 工具 | `tools/checkmate/` |
| 规则库 | `rules/dfm_default.json`（DFM+PERF 绑定）、`rules/perf_formula_v2.json` |
| PERF CAE 流水线 | `docs/branches/feat-nx-checkmate-cae-rule-replication/CAE_PIPELINE.md`、`nxdrp/checkers/performance/cae_*.py` |
| PERF 规则取证 | `docs/branches/feat-nx-checkmate-cae-rule-replication/NX_PERF_RULE_EVIDENCE.md`、`rules/nx_rule_evidence_v1.json` |
| 认证模板 | `docs/branches/feat-nx-checkmate-cae-rule-replication/PERF_CAE_CERTIFICATION_TEMPLATE.md` |

---

## 八、复现命令

```bash
# 全量单测
python -m unittest discover -s tests

# 自检
python -m nxdrp selftest

# DFM 38 项双跑对账（零差异）
python tools/checkmate/reconcile_verdicts.py --model mockdata/models \
  --model tests/fixtures/bent_sheet.model.json \
  --no-expression-for $(python -c "print(','.join(f'DFM-{i:02d}' for i in range(1,39)))")

# PERF 公式库校验与检查
python -c "from nxdrp.checkers.performance.rule_engine import validate_formula_library; print(validate_formula_library())"
python -m nxdrp check nxdrp/checkers/performance/data/simulated_nx_terminal.model.json --only PERF-01
python -m nxdrp check nxdrp/checkers/performance/data/contact_spring.model.json --only PERF-02

# Check-Mate 黑盒冒烟
python tools/checkmate/run_checkmate.py smoke --checker dfms_DeepHoles
```

---

## 九、提交记录

| 提交 | 内容 |
|---|---|
| `dddd94f` | 建立分支（空锚点） |
| `e70e5de` | W1：规则模型 v2 + 引擎 + DFM-27/28/33 |
| `5afeb0c` | W2：机加其余 9 项 |
| `65e687a` | W3：注塑 11 项 |
| `e61e845` | W4：钣金 8 项 |
| `b57da53` | W5：装配 7 项（38/38） |
| `7a908fa` | PERF：公式驱动重构 + CAE 认证流水线 |
| `1d534ba` | PERF：Simcenter/FloEFD 离线链路与认证门禁 |
| `7a2a44d` | 契约修复：schema 重复键 + exceptions 统一 |
| `e3e9e81` | 收尾：PERF 置信度 + 现场验收范围标注 |

---

## 附录 A：38 项 DFM 明细

> 「对应」= 是否有 Check-Mate 检查器可作对照；「置信度」来自各自证据文档的结论段。
> DFM-16 的对应项 `dfms_StandardCornerRadius` 仅为口径参考（标准半径 vs 壁厚倍率）。

| ID | 名称 | 对应 | 置信度 |
|---|---|---|---|
| DFM-01 | 干涉检测 | 有 | medium |
| DFM-02 | 最小间隙 | 无 | low |
| DFM-03 | 孔对齐 | 有 | medium |
| DFM-04 | 孔/槽对齐 | 有 | medium |
| DFM-05 | 紧固件可达性 | 有（度量不同） | low |
| DFM-06 | 紧固件间隙 | 有 | medium |
| DFM-07 | 紧固件啮合长度 | 有 | medium |
| DFM-08 | 最小壁厚 | 无 | low |
| DFM-09 | 均匀壁厚 | 无 | low |
| DFM-10 | 壁厚变化 | 无 | low |
| DFM-11 | 加强筋设计 | 无 | low |
| DFM-12 | 模具壁厚 | 无 | low |
| DFM-13 | 拔模角 | 有（阈值不同） | medium |
| DFM-14 | 倒扣 | 有 | medium |
| DFM-15 | 凸台设计 | 无 | low |
| DFM-16 | 圆角半径 | 参考（口径不同） | low |
| DFM-17 | 多抽芯方向 | 无 | low |
| DFM-18 | 尖角 | 有（阈值不同） | medium |
| DFM-19 | 最小弯曲半径 | 有（口径不同） | medium |
| DFM-20 | 孔到边缘距离 | 有（阈值不同） | medium |
| DFM-21 | 孔间距 | 有（阈值不同） | medium |
| DFM-22 | 孔径与料厚比 | 有（一致） | high |
| DFM-23 | 槽的最小宽度 | 有 | medium |
| DFM-24 | 折弯与切口距离 | 有 | medium |
| DFM-25 | 翻边高度 | 有（阈值不同） | medium |
| DFM-26 | 冲压凸台高度 | 有（口径不同） | low |
| DFM-27 | 深孔 | 有（阈值不同） | high |
| DFM-28 | 深窄槽 | 有（阈值不同） | medium |
| DFM-29 | 平底盲孔 | 有（一致） | high |
| DFM-30 | 刀具可达性 | 有（粒度不同） | low |
| DFM-31 | 特征尺寸与刀具标准 | 有（系列不同） | medium |
| DFM-32 | 底部圆角一致性 | 有 | medium |
| DFM-33 | 顶部圆角 | 有（方向相反） | low |
| DFM-34 | 内部倒角 | 有（取向不同） | low |
| DFM-35 | 深圆角转角 | 有（公式不同） | medium |
| DFM-36 | 角度铣削面 | 有 | medium |
| DFM-37 | 窄通道 | 有（阈值不同） | medium |
| DFM-38 | 孔的入刀/出刀面 | 有（判据不同） | low |
