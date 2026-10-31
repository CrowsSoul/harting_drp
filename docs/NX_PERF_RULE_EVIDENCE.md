# PERF v2 规则取证与算法边界

## 1. 结论

PERF-01、PERF-02 已从“树模型给一个数，再和阈值比较”改为：

1. 规则库声明输入、单位、变量公式、求解未知量和出处；
2. 受限 DSL 计算公式；
3. NX Check-Mate 风格的比较式产生 PASS/FAIL；
4. 已收敛、模型摘要匹配的 NX/Simcenter/FloEFD 结果可以覆盖公式输出；
5. 回归树只保留为误差区间标定，不再决定是否报警。

必须区分两种证据级别：

| 标记 | 含义 |
|---|---|
| `cae_solver` | 通过结果契约读取到具名求解器、版本、收敛状态和模型摘要匹配的结果 |
| `formula` | 本地降阶公式筛查，不得对外宣称是 NX 求解结果 |

截至 2026-10-30，本机已经安装并实际启动过 NX/Nastran/Thermal Flow：

- NX Open 建模 journal 成功；
- Simcenter Nastran SOL 101 冒烟算例完成并产生位移、应力；
- Thermal Flow 控制台通过安全初始化。

但这只是求解器冒烟验证，**没有产生 PERF-01/PERF-02 的认证样本**。
当前 Nastran 环境没有可核验的公司正式 SPLM 授权证据；
这些冒烟结果不得用于公司生产、规则认证或回填 `cae_solver` 结论。
只有获得公司正式 SPLM 许可证后产生的 PERF 工况结果才能进入认证样本集。

## 2. 本地 NX 2606 媒体取证

只读检查了 `Siemens.DesignCenter.2606.3002.Win64.Full.Setup.iso` 中的组件清单和
公开规则/模板资源。没有复制第三方程序或规则文件进仓库。

| 资源 | 取证内容 | 对 PERF 的影响 |
|---|---|---|
| Check-Mate `mqc_evaluate_comparison_expression.dfa` | 条件式支持 `> < >= <= == != ! && ||`；相等比较有 `equality_tolerance`；表达式非零为 Pass、零为 Fail | 作为 DSL 比较语义和边界容差的依据 |
| Check-Mate `measure_minimum_dist.dfa` / `measure_angle_between_2lines.dfa` | Pass/Marginal/Fail 三组区间，边界使用 `LT/LE/GT/GE` | 规则允许多条件、多严重度，边界运算符必须显式落库 |
| Check-Mate `mqc_dfm_hole_to_trim.dfa` | 输入料厚、材料屈服强度、内外板角色和采样精度 | 性能规则也必须保存物理输入与求解设置，而非只存一个阈值 |
| Check-Mate `mqc_check_buried_features.dfa` | 无对象、参数为空时记录明确日志，不伪造通过 | PERF 缺材料、缺接触元数据、未收敛时 skip |
| Simcenter 3D `margin_solution.xmd` / `MS_*.xml` | 安全裕度由显式方法文件定义，如 allowable、bearing、bolt、buckling | PERF 规则使用公式 ID 和 method 出处，不把结果写成孤立数字 |
| NX Thermal Flow/TMG `advprm_thermal.xml` | 热求解包含温度相关导热、低温滤波、辐射温度上限和收敛相关参数 | 电热模型保留温度相关电阻率、辐射和收敛残差 |
| NX Nastran `contact.ddl` | `BCONP/BCTSET` 定义接触目标、源、摩擦、搜索距离和罚函数；`BFRIC/BCTPARA` 定义摩擦与接触参数 | PERF-02 CAE 工况使用面-面罚函数接触和库仑摩擦 |
| NX Nastran `heat.dat` / `thermal.dat` | 热分析包含辐射边、环境绝对温度和热载荷 | 热结果契约要求环境、辐射、焦耳热和收敛证据 |

这些资源证明的是 NX 的判定和求解**口径**。第三方实现代码没有复制。

## 3. PERF-01 公式

公式库位于 `rules/perf_formula_v2.json#PERF-01`。

核心方程：

```text
A = πr²
L = side_area / (2πr)
A_s = πdL + 2A

ρ(T) = ρ_ref · max(0.5, 1 + α(T - T_ref))
R = ρ(T)L/A + R_contact
P = I²R

P - hA_s(T - T_amb)
  - εσA_s[(T+273.15)^4 - (T_amb+273.15)^4] = 0

ΔT = T - T_amb
FAIL if ΔT >= ΔT_allow
FAIL if T >= T_allow_abs
```

`R_contact` 当前由 `contact_resistance_ohm_mm2 / A_mm2` 得到，是原仓库的本地
标定项，不是 NX 已求解值。必须用实测或 NX 接触界面结果修正。

规则边界：

| 输入 | 当前范围 / 处理 |
|---|---|
| 截面积 | 0.5–20 mm² |
| 导体长度 | 5–40 mm |
| 电流 | 1–40 A |
| 环境温度 | 0–80 °C |
| 对流系数 | 8–25 W/(m²·K) |
| 材料 | Cu、CuSn6、CuZn37、CuBe2 |
| 缺材料/圆柱面 | skip，不给假结果 |

## 4. PERF-02 公式

公式库位于 `rules/perf_formula_v2.json#PERF-02`。

```text
I_sec = b t³ / 12
k = 3 E I_sec / L³
F_n = k δ
F_in = n F_n (μ + tanθ) / (1 - μ tanθ)
F_out = n F_n μ

FAIL_EARLY if F_in >= F_in_max
FAIL_LOW_RETENTION if F_out < F_out_min
```

簧片长度、宽度、厚度、过盈量、接触点数和摩擦系数必须来自
`ModelBundle.meta.performance["PERF-02"].contact_springs`。不再从零件包围盒猜尺寸。

该公式只适用于等截面悬臂、小变形、线弹性、常数摩擦。以下必须用 NX 非线性接触
求解复核：

- 塑性、磨损、接触面积变化；
- 壳体导向、锁扣、密封圈；
- 二次插拔、插拔速度与温升；
- 接触网格敏感性和罚刚度；
- 真实簧片曲线与中性轴。

## 5. CAE 工况与结果回填

工况定义见 `rules/perf_cae_cases.json`：

- `PERF-01-ET-STEADY-001`：稳态电热，输出最高温度、温升、电阻、焦耳热、压降和收敛；
- `PERF-02-CONTACT-STATIC-001`：非线性静态接触，输出插拔反力、最大法向力、应力、穿透和收敛。

机器可读的规则取证映射见 `rules/nx_rule_evidence_v1.json`。该文件记录运算符、
边界语义、所用 NX 求解器模板和“没有复刻的专有部分”，不复制 Siemens 代码。

参数化矩阵和校准命令：

```powershell
python -m nxdrp.checkers.performance.cae_batch generate --count 20 --out runtime/perf_cae_batch.json
python -m nxdrp.checkers.performance.cae_batch ingest --batch runtime/perf_cae_batch.json --results runtime/perf_solver_results --out runtime/perf_records.json
python -m nxdrp.checkers.performance.cae_batch report --batch runtime/perf_cae_batch.json --records runtime/perf_records.json --out runtime/perf_calibration.md
python -m nxdrp.checkers.performance.cae_batch certify --batch runtime/perf_cae_batch.json --records runtime/perf_records.json --out runtime/perf_certification.md
```

默认校准门禁要求结果已收敛，且 `solver.license_mode` 为正式授权类型。
`certify` 还会要求每项至少 20 条样本、中位相对误差不超过 5%、判定一致率
不低于 95%，并检查网格敏感性记录。

每一条批次工况可进一步生成 NX 试验件和 Simcenter FEM/SIM 容器：

```powershell
python -m nxdrp.checkers.performance.cae_batch geometry-request --batch runtime/perf_cae_batch.json --case-id PERF02-CONTACT-0001 --prt runtime/perf02_0001.prt --out runtime/perf02_0001_geometry.json
python -m nxdrp.checkers.performance.nx_geometry_runner --request runtime/perf02_0001_geometry.json --response runtime/perf02_0001_geometry_response.json
```

几何 journal 只生成导体圆柱或接触梁试验件；FEM/SIM journal 只创建模板和分析
容器。材料、网格、接触、载荷、边界条件和 Solve 必须在具体获批环境中继续完成。

生成求解交接单：

```powershell
python -m nxdrp.checkers.performance.solver_case `
  --case PERF-01-ET-STEADY-001 `
  --model nxdrp/checkers/performance/data/simulated_nx_terminal.model.json `
  --out runtime/perf01_case.json
```

求解后按 `contracts/schema/perf_solver_result.schema.json` 回填结果，并把文件路径写入
规则 `params.solver_result_path`。检查器会校验检查项、模型 ID、内容摘要、来源、
单位和收敛状态；任一不符则 skip。

## 6. 仍需现场完成

当前机器已完成求解器冒烟测试；正式数据生成仍需在具备公司有效授权的
NX/Simcenter/FloEFD 环境完成：

1. 用参数化试验件跑至少 20 组电热和 20 组接触工况；
2. 保存结果契约和网格无关性证据；
3. 用求解结果标定 `R_contact`、摩擦、罚刚度和降阶公式误差；
4. 将公式误差报告写入规则版本；
5. 只有完成上述步骤后，才能把当前公式的适用范围从“筛查”升级为“认证预测”。
