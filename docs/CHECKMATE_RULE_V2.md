# 规则模型 v2：Check-Mate 风格"公式 + 比较规则"

> 适用分支：`feat/nx-checkmate-cae-rule-replication`（V2 主线 C）
> 状态：**38/38 DFM 全部迁移完成**（W1~W5）——规则契约 v2 + 表达式引擎 + 全量规则公式化

## 一、为什么改

V1 的判定 = 阈值参数 + checker 里写死的公式/比较/severity 联动。V2 把**比较层**搬进规则库：

- 公式、限值、比较算子、severity 分级、豁免都写在 `rules/*.json` 里，可审计、可对标 Check-Mate；
- checker 只保留**几何测量**（怎么从模型算出测量量），不再决定"多少算不合格"；
- 老规则没有 `expression` 时 checker 走旧路径，行为不变（迁移期双跑对账）。

## 二、Rule 契约新增字段

`nxdrp/contracts/core.py` 的 `Rule`：

| 字段 | 类型 | 含义 |
|---|---|---|
| `expression` | dict | 判定配置；空 = 走旧 params 路径 |
| `unit` | str | Finding.unit 的默认来源（case 可覆盖） |
| `rounding` | int \| None | 回填 measured/threshold 的小数位；None = 模块默认 |
| `exceptions` | list[dict] | 豁免子句 |
| `reference` | str | 判定口径出处（Check-Mate 路径/标准条款） |
| `has_expression` | 属性 | 双路径开关：`expression.cases` 非空 |

空值字段不写进 JSON（`Rule.to_dict` 省略），所以 44 条老规则的 JSON 形态保持不变。
`RuleBook.validate()` 在加载时对 `expression` 做静态校验（语法、函数白名单、severity、rounding），坏规则直接拒绝。

## 三、expression 结构与语义

```json
"expression": {
  "cases": [
    {"when": "meas.ratio > params.very_deep_hole_ratio", "severity": "P1",
     "measured": "meas.ratio", "threshold": "params.very_deep_hole_ratio",
     "note": "超深孔"},
    {"when": "meas.ratio > params.deep_hole_ratio", "severity": "P2",
     "measured": "meas.ratio", "threshold": "params.deep_hole_ratio"}
  ]
},
"exceptions": [
  {"when": "meas.exempt_edge == 1", "skip": true, "note": "装配贴合面豁免"}
],
"unit": "比值",
"rounding": 2,
"reference": "…出处…"
```

- **cases 按顺序求值，首个命中生效**；无一命中 = 不产出 Finding（对应"恰在阈值不报"的回归契约）；
  多级 severity 用顺序表达（>10→P1 放前、>4→P2 放后）。
- `when` 必须是布尔表达式；`measured` / `threshold` 是数值表达式——
  **阈值本身可以是公式**（如 DFM-19 的 `params.min_bend_radius_ratio * meas.thickness`）。
- `exceptions` 在 case 命中后按序求值：`skip: true` 抑制该条，`severity_override` 降级；
  豁免依据缺数据时**不豁免**（宁可报）。
- `rounding` 只作用于回填 Finding 的 measured/threshold，**不参与判定**。

## 四、DSL 语法

```
expr    := or_expr
or_expr := and_expr ('or' and_expr)*
and_expr:= not_expr ('and' not_expr)*
not_expr:= 'not' not_expr | cmp
cmp     := add (('>'|'<'|'>='|'<='|'=='|'!=') add)?     # 不允许连续比较
add     := mul (('+'|'-') mul)*
mul     := unary (('*'|'/') unary)*
unary   := '-' unary | power
power   := primary ('^' unary)?                          # 右结合，2^3^2 = 512
primary := NUMBER[mm|m|inch|deg|mm2|mm²]
         | FUNC '(' expr, ... ')'
         | '(' expr ')'
         | ('params'|'meas') '.' NAME
```

- **变量只有** `params.x`（合并后的规则参数）与 `meas.x`（checker 组装的测量量）两种写法；
- **函数白名单**：`min` / `max` / `abs` / `round(x[,n])`（四舍五入）/ `if(cond,a,b)`（惰性，只算命中分支）/
  `table(dict,key)`（材料查表）/ `nearest(list,x)`（到标准系列最近元，DFM-31/34/36 用；空列表视为缺数据跳过）；
- **单位**（轻量）：长度 mm/m/inch、角度 deg、面积 mm2、无单位=比值；
  加减比较需同量纲（无量纲字面量按另一侧单位解释），乘除按量纲白名单（长度×长度→面积、长度/长度→比值），
  结果统一归一到 mm/deg/mm2；变量单位可在 `expression.units` 里声明（`{"meas.radius": "mm"}`），未声明视为无量纲；
- **不做任何动态代码执行**（无 eval/exec），解析结果缓存在进程内。

### 失败语义

| 异常 | 触发 | checker 约定 |
|---|---|---|
| `ExprParseError` | 规则写错 | 加载 `RuleBook.validate()` 时拒绝 |
| `ExprRuleError` | expression 结构不对 / 无 cases | 同上 |
| `ExprMissingSymbol` | 缺 meas/params 变量、值为 None、查表键不在表内 | **跳过该特征**（`case.when` 缺数据 → 跳过该 case 继续下一条） |
| `ExprTypeError` | 类型错误（布尔参与算术、未知函数、除零） | 不捕获，管线记 checker `error` |
| `ExprUnitError` | 量纲冲突且不在换算白名单 | 同上 |

## 五、与框架的集成

- **管线不改**：`pipeline.py` 照旧把 `merged_params` 交给 checker；
- `CheckContext.evaluate(measurements) -> list[CaseVerdict]`（`nxdrp/checkers/base.py`）：
  按 `ctx.rule.expression` 求值，返回 0 或 1 条判定（severity/measured/threshold/unit 已按规则处理）；
- checker 写法：

```python
from nxdrp.expr import ExprMissingSymbol

def check(self, ctx):
    if ctx.rule.has_expression:
        try:
            for v in ctx.evaluate({"ratio": ratio}):
                ...  # v.severity / v.measured / v.threshold / v.unit
        except ExprMissingSymbol:
            continue          # 缺数据跳过，不猜
    else:
        ...旧的"填参数、比阈值"原样保留...
```

- 机加 `emit_finding` 的舍入改为 `ctx.rule.rounding or 4`，checker 传原始值即可。

## 六、新增/迁移一条规则的步骤

1. 在 `rules/dfm_default.json` 对应 `Rule` 上加 `expression` / `unit` / `rounding` / `reference`
   （`reference` 写 Check-Mate 出处与证据文档路径，见 `docs/checkmate_evidence/`）；
2. 把 checker 里的比较层替换为 `ctx.evaluate(...)`，几何测量保留，旧路径移入 `else`；
3. 在 `tests/test_expr_machining.py` 模式上加：边界/单位/舍入/severity 升级/豁免用例，
   以及"新旧双路径同模型同结果"断言；
4. 跑 `python tools/checkmate/reconcile_verdicts.py --model mockdata/models --no-expression-for <ID>` 对账；
5. 跑 `python -m unittest discover -s tests` 全绿。

## 七、相关文件

- 引擎：`nxdrp/expr/`（tokenizer / parser / evaluator / units / cases / errors）
- 集成：`nxdrp/checkers/base.py`（`ctx.evaluate`）、`nxdrp/checkers/machining/_machining_common.py`（舍入）
- 迁移实现：`nxdrp/checkers/machining/dfm27~38*.py`（12 项）与 `nxdrp/checkers/examples/dfm31_*.py`、`dfm32_*.py`
- 测试：`tests/test_expr_engine.py`、`tests/test_expr_rule_v2.py`、`tests/test_expr_machining.py`
- 取证：`docs/checkmate_evidence/`、`tools/checkmate/`
