# AutoCrear → IEC 60664-1 → SAF 规则映射

## 1. 目的与边界

本文件记录 V2 电气安规插件的证据链。目标是复现可互操作的判定口径，不复制 AutoCrear
代码、资源或私有规则数值。AutoCrear 静态分析用于确认规则框架；正式阈值只取自项目中
已转录并注明表号的 `rules/iec_60664_1_profiles.json`。

分析对象为 `AutoCrearCMD.exe`，SHA-256：
`fe01139737307e071963837680299bbd1d503a9cab0f1a0103eeb78699c74fd6`。
原始取证记录位于工作区 `autocrear_analysis/REA_INITIAL_FINDINGS.md`。

## 2. 已确认映射

| AutoCrear 结构证据 | 正式规则来源 | SAF 实现 | 状态 |
|---|---|---|---|
| `Clearance`、`Max Voltage Difference`、`Clearance Distance` | IEC 60664-1:2020 Table F.1、F.2 | SAF-01：额定电压/过电压类别 → 冲击耐受电压 → 间隙 | 已实现 |
| `AltitudeCorrection` | IEC 60664-1:2020 Table A.2 | SAF-01：对“要求间隙”乘修正系数；支持显式 `altitude_correction_factor` | 框架已确认并实现，数值由 IEC 表提供 |
| `Creepage`、第二组 `Max Voltage Difference` | IEC 60664-1:2020 5.3.2、Table F.5 | SAF-02：逐网络对使用工作电压差查表 | V2 已实现 |
| `CtiClass`、`I/II/IIIa/IIIb` | IEC 60664-1:2020 5.3.2.4 | SAF-02：由 CTI 推导材料组，或使用显式材料组 | 已实现 |
| `Inner/Coating/Outer` | AutoCrear 标准表结构；IEC 污染等级由规则显式给出 | 保存为 `insulation_environment` 审计字段 | 已确认是独立表列；待浩亭提供各列数值 |
| `Creepage Start` | AutoCrear 工作簿解析结构 | 无运行时规则 | 已确认是 `Creepage` 区块起始位置校验，不是几何起点 |
| `Groove Width` | AutoCrear 槽宽选档逻辑；具体数值仍来自外部标准表 | 曲面图最短路；仅按显式边元数据处理槽/筋/倒角 | 选档算法已恢复，槽几何适用条件仍待样例验证 |
| `ViolationTolerance::Interpretation` + 数值字段 | 4 字节枚举 + 8 字节数值；当前 AutoCrearCMD 只序列化并传递该对象，最终要求值函数未消费它 | 严格以 `measured_mm >= threshold_mm` 判定 | 已确认当前版本不应用该容差；不臆造枚举公式 |

AutoCrear 标准表解析函数的字段顺序证据：
`ev_cc93790c59e8be36312c4040c7ca3edbba61818c68f7da618c4382a75e0c5f07`。
类型与规则层证据：
`ev_cf6fc38ced04c85166aa40f4fdd32936e4ae43da93d850575549ab1b892a237b`。

2026-11-01 增量证据：

- 环境/材料列选择：`ev_3eafe1b7d908d3e8704b09fa479f945afb352f0201ff322cd773eb0c8b5bb0c7`；
- 槽宽选档：`ev_e7084c4f7a75da4c1088f6e8320a3d76c364ad25e7ba9575ecf7079e65617f2d`；
- 最大电压差计算：`ev_9a2cbb684d95434caa7d336196a1fe6dd4ec541f39d0652d6aeed289d10d0058`；
- 海拔/要求值乘数注释模式：`ev_f2f91a5b916236068e772e02e1ccd7952cc4e70345d559a77276e1e4f25c5059`、
  `ev_e2712db64f9af9e889ebe2631730c7815b3923631884bc46ac868dea93758c96`；
- 容差对象字段布局：`ev_61df5855d75d9d8fed32c58403a5627cec2f77e25c8c3c55e03b7ca420b11150`。
- 容差随标准表条目进入规则结果：`ev_241e28edddce57041faa37aa552726503d069c52837855d835c7a760abff6179`；
- 规则结果唯一构造入口及完整调用者集合：`ev_d602fcc548aad7a4d9c69961376159041e2e37c636125a1e3296929dd2294aeb`、
  `ev_e0805a870de7f83045c6b2f6616984d8e584c33220009414ccdd7c5aa2367acf`；
- 两个最终要求值函数只读取基础要求值和可选倍率：
  `ev_ad2258f59236949cb1de4ca1489d77026c780c25eb7507d347427d869724d1f7`、
  `ev_d8efde12e28ed76bd34273d0b418e07c287e4a4d1c286917f16f90f22df61182`。

### 2.1 已恢复的 AutoCrear 选择规则

1. 环境/材料不是距离倍率。AutoCrear 在标准表中选择独立列：`Inner`、`Outer`、
   `Coating`，或 CTI 对应的 `I/II/IIIa/IIIb`。
2. CTI 分档为：`CTI >= 600 → I`、`400 <= CTI < 600 → II`、
   `175 <= CTI < 400 → IIIa`、`CTI < 175 → IIIb`。旧适配器在 CTI 无效时会退到
   IIIb；本项目默认仍遵守“缺数据跳过”，不会静默猜测，除非将来增加显式兼容模式。
3. 槽宽由两个电气实体的最大电压差选档：按最大电压差上限升序查找，取首个
   `voltage_difference <= upper_bound` 的槽宽；超过全部上限时取最后一档。
4. 旧配置通过注释行
   `Permanent Voltage: Requirements multiplied by <factor>` 表达要求值乘数。乘数作用于
   要求距离而不是实测几何距离；相关实体出现不一致乘数时不会强行合并。
5. `ViolationTolerance` 是随选中标准表列一起传递的 16 字节附加对象，但当前
   `AutoCrearCMD.exe` 的完整静态调用链没有把其枚举或数值用于最终要求距离或合格比较。
   因而当前版本可复现的行为是“不应用该容差”，而不是某个未证实的绝对/相对放宽公式。

## 3. V2 判定流程

1. 从模型元数据读取显式电气网络、面、零件和 `potential_v`；数据不足时跳过，不猜测。
2. 使用显式 `network_pairs`，否则对不同电位网络两两配对。
3. SAF-01 用 NX 精确最短距离；只有显式开启时才允许包围盒粗筛，并标低置信度。
4. SAF-02 对每个网络对独立解析工作电压，优先级为：
   测量记录 → 配对记录 → 网络电位绝对差 → 规则全局值（仅 `rule` 模式）。
5. SAF-02 按该网络对的电压、污染等级和 CTI/材料组查 Table F.5，再与曲面最短路比较。
6. SAF-03 按最不利原则归集；SAF-04 在标准阈值上增加显式工程裕量。

## 4. 结果可追溯字段

每条 SAF-01/02 finding 至少包含：

- `face_ids`、`part_refs`、三维位置或 `path_points`；
- `measured_value`、`threshold_value`、测量方法与置信度；
- `extra.source_standard`：标准版本、表号和实际选中的列；
- `extra.rule_inputs`：电压及其来源、污染等级、CTI/材料组、环境类别、海拔等；
- 可执行的目标尺寸和所需增量。

## 5. 不得伪造的内容

- `Inner/Coating/Outer` 已确认是独立标准表列，但没有浩亭提供的列数值，当前不能自动换算。
- `ViolationTolerance` 的枚举成员名称无法从该二进制恢复；更重要的是，当前版本的最终
  要求值调用链没有消费该字段。不得凭类型名加入绝对或相对“放宽”公式。
- `Groove Width` 的电压选档已恢复，但槽的几何识别、何时计入爬电路径仍需最小工程样例验证。
- 没有 AutoCrear 可运行许可证时，不能声称已经达到与 AutoCrear 逐项一致；只能声称规则框架已取证、
  IEC 查表与项目测试可复现。

## 6. 验证

```powershell
python -m unittest nxdrp.checkers.electrical_safety.test_safety -v
python -m unittest discover -s tests
python -m nxdrp check nxdrp/checkers/electrical_safety/electrical_safety_mock.model.json `
  -r rules/dfm_default.json --only SAF-01,SAF-02,SAF-03,SAF-04 -o safety_findings.json
```

重点检查 `safety_findings.json` 中不同网络对是否出现不同的 `threshold_value`，并核对
`extra.rule_inputs.working_voltage_source` 与 `extra.source_standard`。
