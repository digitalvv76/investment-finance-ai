# catalyst-cases.jsonl — 催化剂案例训练样本

**来源**：`训练资料.docx`（政府入股/补贴 11 例 + 黄仁勋言论 7 例，共 18 例）
**用途**：喂 `event_driven` 评估器做少样本校准——不只学"打几星"，更学"看到大额政府计划→往外铺哪些受益股+联动板块"。
**评级框架**：沿用 `config/prompts/event_driven_v1.txt` 的强度 1–5（5=板块暴涨→critical，3-4→important 上手机，≤2 不上手机）。

## 字段
| 字段 | 含义 |
|------|------|
| `case_id` | gov-NN / jensen-NN |
| `title` | 还原的新闻式标题 |
| `catalyst_types` | 催化剂类型数组：1政府资本 2AI巨头绑定 3领袖预言 4硬里程碑 5空头挤压（负面竞争事件为空数组，看 direction） |
| `intensity` | 1–5 星（已含用户校准） |
| `direction` | up / down / neutral |
| `beneficiaries` | 直接受益股（美股优先，韩股标 .KS） |
| `linked_tickers` | 联动/溢出受益股（建厂→设备、核能→供电等） |
| `sector_etf` | 板块 ETF |
| `market_reaction` | 文档记载的真实市场反应（强度的 ground truth） |
| `is_push` / `alert_level` | is_event & intensity≥3 → 手机；critical/important/none |
| `note` | 评级依据/坑 |

## 关键校准原则（见记忆 govt-program-rating-deepdig）
- **广度不降级**：大额政府计划(gov-07/08/09)即使无单一纯玩家也 = ★★★★ 高优先，正解是**深挖受益面**，不是嫌分散降级。
- **降级只看时效性**：旧闻(已公开数小时)才降（见 `SPEC-stale-event-downgrade.md`）。
- 唯一因"金额小+无标的"压到 ★ 的是 gov-10（煤电 $3.5亿）。
- 负面同样是强催化(jensen-07 ★★★★ down)，触发做空/规避。

**注意**：`beneficiaries`/`linked_tickers` 为知识映射（哪些股受益），非实时行情；接入时价格须实时抓取核实，勿子串臆测代码（见记忆 tickers-found-unreliable）。

---

## 负面/做空向子集 (`catalyst-cases-negative.jsonl`)

系统正面 5 类是"财富效应机会(做多)"，缺做空维度。本子集补上**负面催化剂 5 类（镜像）**：

| 代码 | 负面类型 | 镜像正面 | 触发 |
|------|---------|:--------:|------|
| **N1** | 巨头降维/进入赛道→在位者受损 | 类型2 | 做空在位者、做多进入者(零和) |
| **N2** | 政策/补贴/管制的受害方(出口管制/被排除/关税/制裁) | 类型1 | 做空高敞口标的 |
| **N3** | 领袖唱衰 / 知名空头报告(Hindenburg型) | 类型3 | 做空被点名标的 |
| **N4** | 硬里程碑失败(FDA CRL/临床失败/召回/事故) | 类型4 | 做空(单药biotech常腰斩→强度5) |
| **N5** | 基本面暴雷(财报miss/指引下调/大客户流失/剔除指数/解禁) | 类型5 | 做空(指引下调比当季miss更致命) |

**新增/差异字段**：`neg_type`(N1-N5)、`losers`(下跌→做空候选)、`beneficiaries`(同事件的受益方)、`direction:"down"`、`source`("doc"真实 / "derived-pattern"派生)。

**防编数纪律**：仅 2 条来自文档(neg-01 N1X / neg-02 英特尔公告日)带真实涨跌；其余 6 条为**模式示例**，`market_reaction` 明确标"无特定历史行情"、`losers` 用占位符——教的是**事件形状→方向/受损面**，不是具体数字。接入时真实标的涨跌必须实时抓取核实（同 deep_lane 硬门禁原则）。

**关键**：负面同样是强催化，别只训练做多。方向(direction)与时间窗口(如 neg-02 当日做空后反转)都要判。

---

## 生产校准锚点 (`source: "production"` / `label_type: "calibration_downgrade"`)

除文档(`doc`)与派生(`derived-pattern`)外，新增第三类来源：**生产真实过评/漏评样本**——从 `/health/decisions.json` 决策面板捞出的、系统评级站不住的真实案例。这类是**验收 A3 的具名回归锚点**（见 `REQ-training-eval.md`）：改评估器后此条必须回到修正标签，否则算回归。

**差异字段**：
| 字段 | 含义 |
|------|------|
| `source: "production"` | 真实生产案例（非造） |
| `prod_news_id` | 生产库 news 主键，可回溯原文 |
| `system_intensity` / `system_alert_level` | 系统**当时实际**打的分/档（保留证据） |
| `intensity` / `alert_level` | **修正后**的金标签（ground truth） |
| `label_type: "calibration_downgrade"` | 标记方向：系统过评→应降级（反之 `_upgrade`=漏评应升级） |

**已收录**：
- `cal-01`（news_id=3612）：OpenAI/谷歌被曝向五角大楼黑名单中资子公司供 AI → 系统 **intensity=5 拉手机警笛**。降级三理由：①`reportedly` 二手传闻非官方；②GOOGL/MSFT 万亿巨头，单条合规传闻难成板块级异动；③**利空事件被硬塞进按"板块暴涨"写的利好标尺顶格**。修正 = `important`（上手机不拉警笛）/intensity 3。**验收锚点：此条不得判 critical。**

**防编数纪律同样适用**：`market_reaction` 未实时核实的一律标"待核实"，接入时按 `captured_at` 实时抓取，禁子串臆测（见记忆 `tickers-found-unreliable` / deep_lane 硬门禁）。
