# 富途 OpenD 充分利用方案 — V1 设计 → V2 实施

> 状态: V1 方案设计完成，待 V2 评审实施 | 日期: 2026-07-16

## 现状

富途 OpenD 已在 ECS 运行（`/opt/OpenD`，systemd 自启），当前仅用了两个 API：

| 已用 | 用途 | 频率 |
|------|------|:---:|
| `get_capital_flow` | 资金流采集，替代东财 | 每日 × 2 窗口 |
| `request_history_kline` | K 线收盘价，替代 yfinance | 每日 |
| `get_search_news` | 新闻采集，35 关键词轮转 | 每分钟 |

**利用率 < 5%。** Futu OpenD 有 100+ API，大量高价值数据闲置。

---

## 方案：三阶段挖掘

### Phase 1 — 实时行情快照（盘前/盘中脉搏）

**价值**：每天开盘前知道哪些持仓股盘前异动、哪些板块领涨领跌。现在完全盲区。

**API**: `get_market_snapshot` — 单次调用可查询多只股票实时报价

**数据**：
```python
# 每只股票返回:
{
    "last_price": 185.32,       # 最新价
    "open_price": 182.10,       # 开盘价
    "high_price": 186.50,       # 日内最高
    "low_price": 181.80,        # 日内最低
    "prev_close_price": 184.00, # 昨收
    "change_rate": 0.0072,      # 涨跌幅
    "volume": 52300000,         # 成交量
    "turnover": 9680000000,     # 成交额
    "turnover_rate": 1.8,       # 换手率
    "bid_price": 185.30,        # 买一
    "ask_price": 185.34,        # 卖一
    "pe_ratio": 45.2,           # 市盈率
    "market_cap": 2.85e12,      # 总市值
}
```

**实现**：

```python
# news-monitor/collector/market_snapshot.py
class MarketSnapshotCollector:
    """盘前/盘中实时行情采集器。
    
    两窗口:
    - 盘前 09:25 ET (开盘前5分钟): 扫描全部 ~71 只持仓+关注股
    - 盘中 14:30 ET (收盘前30分钟): 扫描异动股(涨跌>2%+放量)
    """
    
    async def pre_market_snapshot(self):
        """盘前: 全量扫描, 推送异动摘要"""
        snapshots = await self._fetch_snapshots(self._watchlist)
        movers = [s for s in snapshots if abs(s.change_rate) > 0.02]
        if movers:
            await self._push_pre_market_summary(movers)
    
    async def intraday_snapshot(self):
        """盘中: 只推极端异动 (>5% + 放量>2x)"""
        snapshots = await self._fetch_snapshots(self._watchlist)
        extreme = [s for s in snapshots if abs(s.change_rate) > 0.05 
                   and s.volume > s.avg_volume * 2]
        if extreme:
            await self._push_intraday_alert(extreme)
```

**推送格式**：
```
📊 盘前异动 (09:25 ET)
🔴 NVDA -3.2%  (盘前放量 1.8x)
🟢 PLTR +4.1%  (盘前放量 2.3x)
🟢 RKLB +2.8%
---
📈 板块: SOXX +0.8%, XLF -0.3%
```

**工作量**: ~150 行 + 10 测试，2 小时

---

### Phase 2 — 板块轮动追踪（资金去哪儿了）

**价值**：黄仁勋日本行推机器人的时候，如果能同时看到日本机器人板块 ETF 的资金流向，信号完整度翻倍。

**API**: 
- `get_plate_list` — 行业/概念板块列表（美股板块如 AI、半导体、云计算等）
- `get_plate_stock` — 板块成分股
- `get_capital_flow` — 板块资金流（与个股相同的特大单/大单/中单/小单分解）

**数据**：
```python
# 板块资金流 — 与个股相同的框架
{
    "plate_name": "AI人工智能",
    "super_big_net": 12.5e8,    # 特大单净流入 12.5亿
    "big_net": 3.2e8,           # 大单净流入
    "change_rate": 2.1,         # 板块涨跌幅
    "leading_stocks": ["NVDA", "AMD", "PLTR"],
}
```

**实现**：

```python
# news-monitor/collector/sector_rotation.py
class SectorRotationCollector:
    """板块资金流 + 轮动信号。
    
    收盘后采集 20-30 个关键板块的资金流, 与个股信号形成验证。
    板块强 + 个股强 = 确认; 板块弱 + 个股强 = 独立行情需警惕。
    """
    
    SECTORS = [
        ("AI人工智能", "US"),
        ("半导体", "US"),
        ("云计算", "US"),
        ("机器人", "US"),
        ("量子计算", "US"),
        ("核能", "US"),
        ("航天国防", "US"),
        ("金融科技", "US"),
        ("电动车", "US"),
        ("生物科技", "US"),
        # ... 20-30个关键板块
    ]
    
    async def collect_post_market(self):
        """收盘后: 板块资金流 + 排名 + 个股信号交叉验证"""
        plates = await self._fetch_plate_flows(self.SECTORS)
        top = sorted(plates, key=lambda p: p.super_big_net, reverse=True)[:5]
        bottom = sorted(plates, key=lambda p: p.super_big_net)[:5]
        
        # 交叉验证: 板块资金流 vs 个股信号
        cross = await self._cross_validate(plates)
        
        await self._push_sector_summary(top, bottom, cross)
```

**推送格式**：
```
🔥 板块资金流 TOP5 (07/16 收盘)
1. AI人工智能    特大单+12.5亿  📈+2.1%  NVDA/AMD/PLTR
2. 半导体        特大单+8.3亿   📈+1.8%  AVGO/LRCX/KLAC
3. 机器人        特大单+4.2亿   📈+3.5%  RKLB/OKLO
...
⚠️ 板块 vs 个股背离:
- PLTR 个股强流入 但 AI板块资金中性 → 独立行情, 非板块驱动
```

**工作量**: ~200 行 + 15 测试，3 小时

---

### Phase 3 — 经纪商队列（钱是谁的）

**价值**：特大单只看金额，经纪商队列看**谁**在买卖。机构（如 Goldman/JPMorgan 自营）的买卖方向是最硬核的 smart money 信号。这是富途独有的数据优势——Yahoo/Bloomberg 没有这个。

**API**: `get_broker_queue` — 实时经纪商买卖队列（港股支持，美股需确认 Futu 美股的 broker 数据可用性）

**数据**：
```python
# 经纪商买卖队列
{
    "ticker": "NVDA",
    "bid_brokers": [
        {"name": "Goldman Sachs", "volume": 50000, "orders": 12},
        {"name": "Morgan Stanley", "volume": 35000, "orders": 8},
    ],
    "ask_brokers": [
        {"name": "Retail Aggregate", "volume": 20000, "orders": 45},
    ],
    "bid_ask_ratio": 4.25,  # >2 = 机构买入意愿强
}
```

**实现**：

```python
# news-monitor/collector/broker_tracker.py
class BrokerTracker:
    """经纪商队列追踪 — 识别机构动向。
    
    不是实时推送(数据量大), 而是每日收盘后分析:
    - 哪些持仓股的买盘集中在机构侧?
    - 哪些持仓股机构在悄悄出货?
    - 与资金流背离信号交叉验证
    """
    
    async def analyze_daily(self):
        """收盘后: 逐个分析持仓股经纪商数据"""
        signals = []
        for ticker in self._watchlist:
            queue = await self._fetch_broker_queue(ticker)
            if queue is None:
                continue
            
            ratio = queue.bid_ask_ratio
            if ratio > 3.0:
                signals.append((ticker, "机构强势买入", ratio))
            elif ratio < 0.3:
                signals.append((ticker, "机构大量卖出", ratio))
        
        # 与资金流信号交叉验证
        await self._cross_validate_with_fund_flow(signals)
        await self._push_broker_signals(signals)
```

⚠️ **前置验证**：Futu 美股的 broker queue 数据可用性需先测试。如果美股不支持，此阶段仅覆盖港股。

**工作量**: ~180 行 + 12 测试，3 小时（含前置验证）

---

## 汇总

| 阶段 | 功能 | 数据 | 推送渠道 | 工作量 |
|:---:|------|------|:---:|:---:|
| P1 | 盘前/盘中实时快照 | 涨跌幅+成交量+换手率 | TG + Pushover(极端) | 2h |
| P2 | 板块轮动追踪 | 板块资金流+排名 | TG 静音 | 3h |
| P3 | 经纪商队列 | 机构买卖方向 | TG 静音(与资金流交叉) | 3h |
| **合计** | | | | **1 天** |

### 与现有系统的关系

```
Futu OpenD ──┬── 资金流 (已有) ──→ 背离信号 ──→ Pushover/TG
             ├── K线 (已有) ──→ 价格数据 ──→ 资金流分析
             ├── 新闻 (已有) ──→ 调度器 ──→ 筛选→评估
             ├── P1 实时快照 (新) ──→ 盘前异动 ──→ Pushover/TG
             ├── P2 板块数据 (新) ──→ 轮动信号 ──→ TG + 交叉验证
             └── P3 经纪商 (新) ──→ 机构踪迹 ──→ TG + 资金流交叉
```

### 验收标准

- P1: 盘前 09:25 收到异动推送（涨跌>2%+放量），Playwright 验证
- P2: 收盘后收到板块资金流 TOP5/BOTTOM5，Playwright 验证
- P3: 收盘后收到机构买卖信号（与资金流交叉验证），Playwright 验证（需先确认美股 broker queue 可用性）

### ⚠️ P0 前置：防封禁加固

东财因调用太频繁被封。富途虽不会轻易封客户，但需加一层保护：

```python
# futu_fetcher.py — fetch_multi() 加请求间隔
# 当前: semaphore(5) 5并发瞬间发出，无间隔
# 修复: 每只股票请求后 asyncio.sleep(0.3)，71只≈21秒完成

async def _fetch_one(ticker):
    async with sem:
        result = await self.fetch(ticker, days=days)
        await asyncio.sleep(0.3)  # ← 防限流
        return ticker, result
```

同样逻辑适用于 P1-P3 新增的任何批量请求。**所有批量调用统一间隔 0.3s。**

### 已知风险

| 风险 | 缓解 |
|------|------|
| 富途限流（类似东财封禁） | P0 统一 0.3s 请求间隔 + semaphore 限并发 |
| P3 美股 broker queue 不可用 | 先测试，不可用则 P3 仅港股 |
| 快照 71 只股票可能超时 | 分批 20 只/批，asyncio.gather |
| 推送过多打扰用户 | P1 盘前推 TG + 极端推手机，盘中只推 >5%+放量 |
