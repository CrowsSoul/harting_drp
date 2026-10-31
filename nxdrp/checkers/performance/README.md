# 智能性能预测

**负责人**：杜滨芳

> **V2 已重构（2026-10-30）**：PERF-01/02 的计算与 PASS/FAIL 由
> `rules/perf_formula_v2.json` 驱动；NX 风格比较式负责判定。回归树只保留为
> 标定区间，不再决定报警。NX 取证与边界见
> [`docs/NX_PERF_RULE_EVIDENCE.md`](../../../docs/NX_PERF_RULE_EVIDENCE.md)。
> CAE 参数化、结果回填和认证状态机见
> [`docs/CAE_PIPELINE.md`](../../../docs/CAE_PIPELINE.md)。
> 正式报告模板见
> [`docs/PERF_CAE_CERTIFICATION_TEMPLATE.md`](../../../docs/PERF_CAE_CERTIFICATION_TEMPLATE.md)。

本文件同时是模块说明和本次开发记录。任务原文在 `性能预测工作要求.md`。

## 背景

性能预测有两项：PERF-01 载流–温升、PERF-02 插拔力。工程师给出几何、材料和
工况，模块用规则公式返回性能量、标定区间和可执行建议。判定式直接从规则库读取，
代码不再写“如果大于某阈值就报警”。

## V2 计算链

1. `rules/dfm_default.json` 通过 `formula_ref` 指向公式模型；
2. `rule_engine.py` 校验并执行受限 DSL，禁止属性访问、下标和任意函数；
3. PERF-01 用二分法求稳态温度，PERF-02 用悬臂梁/摩擦公式；
4. `expression`/`decisions` 按 NX Check-Mate 比较语义产生 PASS/FAIL；
5. 若规则设置了 `solver_result_path`，只接受模型摘要匹配且已收敛的
   NX/Simcenter/FloEFD 结果；否则退回 `formula` 并明确标记。

校核命令：

```powershell
python -c "from nxdrp.checkers.performance.rule_engine import validate_formula_library; print(validate_formula_library())"
python -m nxdrp.checkers.performance.solver_case --case PERF-01-ET-STEADY-001 --model nxdrp/checkers/performance/data/simulated_nx_terminal.model.json --out runtime/perf01_case.json
```

## CAE 批量与校准入口

生成每种 PERF 20 个确定性参数化工况：

```powershell
python -m nxdrp.checkers.performance.cae_batch generate `
  --count 20 `
  --out runtime/perf_cae_batch.json
```

生成 40 个独立工况目录：

```powershell
python -m nxdrp.checkers.performance.cae_batch materialize `
  --batch runtime/perf_cae_batch.json `
  --out-dir runtime/perf_cae_workspace
```

每个目录还包含 `bindings.json`，用于填写真实材料、实体、边界面、载荷、接触和
结果查询。面角色不允许由代码猜测，必须由 CAD/网格拓扑确认：

```powershell
python -m nxdrp.checkers.performance.cae_batch validate-bindings `
  --binding runtime/perf_cae_workspace/PERF02-CONTACT-0001/bindings.json

python -m nxdrp.checkers.performance.cae_batch status `
  --workspace runtime/perf_cae_workspace
```

材料工程默认值位于 `rules/perf_material_library_v1.json`，当前状态为
`provisional`。正式认证前必须替换为供应商 TDS 中的牌号、状态和温度相关曲线。

生成 NX Simcenter FEM/SIM 容器请求：

```powershell
python -m nxdrp.checkers.performance.solver_case `
  --case PERF-02-CONTACT-STATIC-001 `
  --out runtime/perf02_case.json `
  --source-part mockdata/parts/plate_holes.prt `
  --out-dir runtime/perf02_simcenter `
  --create-solution `
  --solution-type "Nonlinear Statics" `
  --mesh `
  --element-size 0.25 `
  --nx-request-out runtime/perf02_nx_request.json
```

也可以先生成参数化试验件：

```powershell
python -m nxdrp.checkers.performance.cae_batch geometry-request `
  --batch runtime/perf_cae_batch.json `
  --case-id PERF02-CONTACT-0001 `
  --prt runtime/perf02_0001.prt `
  --out runtime/perf02_0001_geometry.json

python -m nxdrp.checkers.performance.nx_geometry_runner `
  --request runtime/perf02_0001_geometry.json `
  --response runtime/perf02_0001_geometry_response.json
```

在 NX 内执行（也可由下面的 Python 包装器调用）：

```text
D:\Siemens\Designcenter2606\NXBIN\run_journal.exe nxdrp\journals\create_simcenter_case.py
```

```powershell
python -m nxdrp.checkers.performance.nx_cae_runner `
  --request runtime/perf02_nx_request.json `
  --response runtime/perf02_nx_response.json
```

该 journal 创建并关联 FEM/SIM、设置求解环境；指定 `--mesh` 时使用自动尺寸或
指定四面体尺寸生成体积网格。它不会把尚未设置材料、载荷和边界条件的容器冒充
成可求解 CAE 工况。

求解后把符合结果契约的 JSON 放入结果目录：

```powershell
python -m nxdrp.checkers.performance.cae_batch ingest `
  --batch runtime/perf_cae_batch.json `
  --results runtime/perf_solver_results `
  --out runtime/perf_solver_records.json

python -m nxdrp.checkers.performance.cae_batch report `
  --batch runtime/perf_cae_batch.json `
  --records runtime/perf_solver_records.json `
  --out runtime/perf_calibration.md

python -m nxdrp.checkers.performance.cae_batch certify `
  --batch runtime/perf_cae_batch.json `
  --records runtime/perf_solver_records.json `
  --out runtime/perf_certification.md
```

`ingest` 默认真实认证门禁：结果必须已收敛并声明 `authorized`、`commercial`、
`floating`、`node_locked` 或 `evaluation` 授权模式。只有接口联调时才能显式增加
`--allow-unverified-for-smoke`，该批次不得用于认证结论。

`certify` 默认要求每项至少 20 条正式授权样本、中位相对误差不超过 5%、
判定一致率不低于 95%，并要求每条结果带网格敏感性证据。

## 预测

PERF-01 的输出是稳态温升 ΔT（°C）、绝对温度、电阻、焦耳热和压降。同时给出
80% 标定区间，以及让温升回到允许值以下的截面积或电流。允许温升默认 45 °C，
绝对温度默认 2000 °C 求解护栏；设计判定式在 `rules/perf_formula_v2.json`。

默认工况：电流 16 A，环境温度 25 °C，对流换热系数 15 W/(m²·K)。几何取零件上半径最小的圆柱面：截面积 A = πr²，长度由该圆柱侧面面积反推。材料用电阻率，表内四种：Cu、CuSn6、CuZn37、CuBe2。

PERF-02 的输出是插入力和拔出力（N），以及 80% 标定区间。插入力达到 20 N
报 P2，拔出力低于 1 N 报 P3。边界和严重度在公式库的 `decisions` 中。

检查项超限时写出 Finding：带 `face_ids`，建议里给出具体尺寸或电流。不超限时检查项不报警，命令行 `predict` 仍能看到数值。缺材料、缺圆柱面，或工况超出训练范围时，检查项跳过并写明缺什么。

## 方法

PERF-01 有两层计算。

集总对流保留在 `physics.delta_t_c`，仅作基线对照：

- 发热 P = I² ρ L / A
- 散热面积 = 侧面 π d L + 两端 2A
- ΔT = P / (h · 散热面积)

生产判定使用 `rules/perf_formula_v2.json#PERF-01`。它在集总对流之外加入电阻率
随温度、表面辐射和端部接触电阻，迭代求稳态温度。不能把这段本地求解称为 NX；
只有 `solver_evidence.py` 校验通过的结果才标记为 `cae_solver`。

回归树不直接决定报警。它历史上拟合「样本温升 / 集总公式」的对数，现在只用于
保留 80% 标定区间。公式点值、比较式和判定结果来自规则文件。

区间在标定集上取「实际值 / 预测值」的 10% 与 90% 分位，对应规则里的置信度 0.8。覆盖率只在测试集上统计。训练、标定、测试三份样本不混用。

端子模型由 `make_terminal` 写成 `data/simulated_nx_terminal.model.json`。结构与解析结果相同：一个带材料的圆柱面，半径和侧面面积齐全。`source` 为 `simulated_nx://terminal`。

PERF-02 的公式在 `rules/perf_formula_v2.json#PERF-02`：惯性矩
I = b t³ / 12，刚度 k = 3EI / L³，正压力 Fn = k δ，插入力和拔出力由摩擦和
引导角合成。几何从 `model.meta.performance["PERF-02"].contact_springs` 读取；
无明确接触元数据时跳过。只有旧规则显式设置 `geometry_source=part_bbox` 才启用
包围盒兼容模式。

两个模型都是标准库回归树，不依赖 numpy 或 sklearn。

## 数据来源

仓库里没有带温升或插拔力标签的样本。两组都按种子 20261029 抽了 360 条，再打乱切成三段。

| 用途 | 条数 | 用途说明 |
|---|---|---|
| 训练 | 240 | 拟合回归树 |
| 标定 | 60 | 定区间分位数 |
| 测试 | 60 | 只报误差和覆盖率 |

PERF-01 的抽取范围与规则一致：截面积 0.5–20 mm²，长度 5–40 mm，电流 1–40 A，环境温度 0–80 °C，换热系数 8–25 W/(m²·K)。四种材料轮流出现。

PERF-02 的范围：长度 6–15 mm，宽度 1–4 mm，厚度 0.2–0.6 mm，过盈 0.1–0.5 mm，摩擦 0.12–0.30。材料为 CuSn6、CuBe2、CuZn37。弹性模量分别是 110、131、100 GPa。

规则只改了 `dfm_default.json` 里 PERF-01 和 PERF-02 两条。没有运行 `tools/gen_rules.py`，避免重写整份规则库。

换一批标签时，保留特征列，替换 `delta_t_c` 或 `insertion_n`，再运行对应的 `train`。检查项不用改。

## 实验步骤

在仓库根目录按这个顺序运行样本、训练和检查：

```powershell
python -m nxdrp.checkers.performance.samples
python -m nxdrp.checkers.performance.train
python -m nxdrp.checkers.performance.make_terminal
python -m nxdrp check nxdrp/checkers/performance/data/simulated_nx_terminal.model.json --only PERF-01
python -m nxdrp check mockdata/models/board_a.model.json --only PERF-01
python -m nxdrp check nxdrp/checkers/performance/data/contact_spring.model.json --only PERF-02
python -m nxdrp.checkers.performance.evaluate
```

单条工况可以不经过模型文件直接问：

```powershell
python -m nxdrp.checkers.performance.predict --area-mm2 15.2 --length-mm 10 --material Cu
python -m nxdrp.checkers.performance.predict_insertion --length-mm 8 --width-mm 2 --thickness-mm 0.5 --material CuSn6
```

## V1 标定记录（供误差追溯）

下面保留的是 V1 回归树的历史误差和示例，不再表示当前生产判定。V2 的
PASS/FAIL 由 `rules/perf_formula_v2.json` 决定；示例数值会随规则版本变化。

测试集 60 条，未参与训练，也未参与定区间。

| 检查项 | 中位误差 | 平均误差 | 分档中位误差 | 覆盖率 |
|---|---|---|---|---|
| PERF-01 | 0.71 °C | 19.45 °C | 1–200 °C：0.83 °C | 84.2% |
| PERF-02 | 0.125 N | 0.528 N | 1–100 N：0.210 N | 80.9% |

PERF-01 的区间分位数 q_low = 0.9408，q_high = 1.1561。PERF-02 为 0.9222 和 1.1579。自查线是档内中位误差 ≤ 2 °C / 1 N，覆盖率 ≥ 70%。两组都在这条线以内。平均绝对误差 19.45 °C 被少数上千度的样本拉高，以中位数和 1–200 °C 这一档为准。

三个检查例子：

| 对象 | 结果 |
|---|---|
| 模拟 NX 端子，PERF-01 | CuSn6，直径 2 mm，长 8 mm，16 A。温升 100.0 °C（94.1–115.6）。建议截面积 5.24 mm²，或电流 10.73 A |
| board_a，PERF-01 | P02（CuSn6），16 A，25 °C。温升 96.4 °C（90.7–111.5）。建议截面积 5.09 mm²，或电流 10.93 A |
| 合成簧片，PERF-02 | 插入力 75.70 N（69.81–87.65），上限 20 N。建议簧片长度 9.35 mm |

`board_a` 的 `generator` 是 `tools.gen_mock`，`source` 是 `mock://board_a.prt`。模拟 NX 端子的 `source` 是 `simulated_nx://terminal`。

PERF-01 在测试集上按材料和截面积拆开：

| 分组 | 条数 | 中位误差 | 覆盖率 |
|---|---|---|---|
| Cu | 13 | 0.44 °C | 67% |
| CuSn6 | 18 | 1.01 °C | 75% |
| CuZn37 | 15 | 1.18 °C | 100% |
| CuBe2 | 14 | 0.31 °C | 90% |
| 截面积 0.5–2 mm² | 24 | 7.67 °C（1–200 °C 档 1.18 °C） | 76% |
| 截面积 2–5 mm² | 12 | 1.52 °C | 100% |
| 截面积 5–10 mm² | 13 | 0.14 °C | 88% |
| 截面积 10–20 mm² | 11 | 0.30 °C | 88% |

0.5–2 mm² 这一档温升高，全部样本的中位误差到 7.67 °C。只保留 1–200 °C 的点，中位误差是 1.18 °C。粗截面的误差小。

留一材料：把一种材料整段移出训练和标定，再用它自己的测试样本预测。

| 未参与训练的材料 | 中位误差 | 1–200 °C 档 | 覆盖率 |
|---|---|---|---|
| Cu | 1.15 °C | 6.86 °C | 0% |
| CuSn6 | 2.04 °C | 2.28 °C | 25% |
| CuZn37 | 0.57 °C | 0.57 °C | 90% |
| CuBe2 | 1.00 °C | 1.00 °C | 30% |

材料表里见过的四种，误差可以分开看。表外牌号检查项直接跳过。Cu 整段拿掉之后，1–200 °C 档的误差升到 6.86 °C，覆盖率为 0%。

## 问题与处理

**回归树直接拟合温升。** 第一版的目标是温升本身。验证集平均绝对误差约 104 °C，高温样本把分裂拉偏。后来改为拟合温升的对数，再改为拟合「样本温升 / 集总公式」的对数。公式加散差那一版，测试集中位误差 0.19 °C，覆盖率 80.0%。换成模拟 NX 标签后重新训练，中位误差 0.71 °C，覆盖率 84.2%。量级由公式负责，树只学两者的差别。

**区间和覆盖率用了同一批样本。** 早期是 300 条训练、60 条验证，分位数和覆盖率都在这 60 条上计算，覆盖率会偏高。当时自证的覆盖率约 77.1%。现改为 240 / 60 / 60，覆盖率只报留出的 60 条。

**PERF-02 三个用例同时失败。** 日志是 `applies() 异常: ValueError('too many values to unpack')`。`spring_spec()` 成功时只返回字典，调用处按 `(规格, 原因)` 解包。成功路径改为同时返回空字符串。单测可以复现这条错误。

**规则合并打印成功，文件没变。** 脚本用 `{编号: rule for rule in rules}` 得到一份映射，改映射不会改到原来的列表。PERF-02 的参数因此没写进 `dfm_default.json`。PERF-01 当时已经在上一次提交里，所以没露出这个问题。改为按下标写回列表后，44 条规则与工区一致。

**Mock 模型的来源需要单独标明。** `board_a.model.json` 由 `tools.gen_mock` 生成。检查用的圆柱端子另写在 `simulated_nx_terminal.model.json`，带材料 CuSn6 和圆柱面 `F_cyl`。

## 文件

| 文件 | 内容 |
|---|---|
| `physics.py` / `thermal_solver.py` | 集总对流；模拟 NX 热求解 |
| `samples.py` / `train.py` / `tree_model.py` | 360 条样本、回归树、模型卡 |
| `perf01_current_temp.py` / `predict.py` | PERF-01 检查项和命令行 |
| `simulated_nx_model.py` / `make_terminal.py` | 写出模拟 NX 圆柱端子 |
| `force_physics.py` / `force_samples.py` / `force_train.py` / `force_model.py` | PERF-02 公式、样本、训练 |
| `perf02_insertion_force.py` / `predict_insertion.py` | PERF-02 检查项和命令行 |
| `evaluate.py` | 按材料、截面积、留一材料看误差 |
| `模型卡.md` / `PERF02模型卡.md` | 范围、误差、局限 |
| `选型说明.md` / `插拔力选型说明.md` | 两项的预测内容和数据 |
| `性能预测工作要求.md` | 原始任务说明 |

## 汇报摘要

PERF-01 载流–温升：V2 已改为规则驱动的稳态电热公式，NX 风格比较式直接判定温升和绝对温度；回归树仅保留 80% 标定区间。缺材料、缺圆柱面或求解未收敛时跳过。

PERF-02 插拔力：V2 已改为规则驱动的悬臂梁加摩擦公式，几何必须来自显式接触元数据，不再用包围盒猜测。非线性接触仍需 NX Nastran/Simcenter 结果复核。

本机已完成 NX Open、Simcenter Nastran SOL 101 和 Thermal Flow 启动冒烟，
但没有生成 PERF-01/PERF-02 认证样本。当前 Nastran 许可来源为非正式授权，
冒烟结果不进入 `cae_solver` 认证数据。公式仍属于筛查级，不是 CAE 认证结果。
实际求解工况见 `rules/perf_cae_cases.json`，证据边界见 `docs/NX_PERF_RULE_EVIDENCE.md`。
