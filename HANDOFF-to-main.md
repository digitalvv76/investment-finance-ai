# 交接：把 V1 会话的 3 个修复搬进 main（V2 窗口执行）

> 背景：2026-07-10 V1 窗口(v1-stable)做了一批修复；生产已按"方案A"切成 clean main（`ba83372`）。
> main 已自带看门狗 + 看门狗时区修复（`count_recent_news` 路线），**不要重复搬看门狗**。
> 本清单只搬 main 还缺的 3 个修复。**在 V2 窗口 `D:\class1`（main 工作区）执行。**

## 先决检查
```bash
cd D:/class1
git status                      # 确认工作区干净；若有未提交改动先处理，别被 cherry-pick 冲掉
git log --oneline -1            # 应为 ba83372 附近
git fetch origin && git log --oneline origin/v1-stable -8   # 确认能看到下列 hash
```

## 要搬的 3 个 commit（v1-stable → main，按时间顺序）

| 顺序 | commit | 内容 | main 现状 | 冲突预判 |
|----|--------|------|----------|---------|
| 1 | `fb0d350` | 关注股/持仓安全网（is_event=false + notable + 命中关注股 → 静音 TG） | 无（`watchlist_safety_net`/`get_tracked_tickers` 都缺） | **main.py 会冲突**（main 加了 watchdog 接线）→ 保留两者 |
| 2 | `25059ba` | 关注列表 21→74 只（真实关注池美股） | main 是旧 21 只 | watchlist-state.md / deploy.sh 可能冲突 |
| 3 | `99b588b` | 新浪财经改 zhibo 端点（roll/get 全 403） | main 仍旧 roll/get | chinese_fetcher.py 可能冲突（按 zhibo 版为准） |

**跳过** `78325e5`（看门狗）——main 已有，重复。
**可选** `2768e90`（改 `get_recent_news` 用 `datetime()+localtime`）——main 看门狗已用 `count_recent_news` 修好，此 commit 额外修正 `get_recent_news` 本身（惠及仪表盘"最近新闻"窗口，非紧急）。要更彻底就搬，否则可跳。

## 执行
```bash
cd D:/class1
git cherry-pick fb0d350        # 冲突多半在 main.py：既留 watchdog 接线，又加安全网分支+imports
# 解决后： git add -A && git cherry-pick --continue
git cherry-pick 25059ba        # watchlist-state.md 取 74 只版；deploy.sh 合并 FILES
git cherry-pick 99b588b        # chinese_fetcher.py 取 zhibo 版（SINA_ZHIBO_URL / _parse_zhibo_feed / _split_zhibo_richtext）
# 可选： git cherry-pick 2768e90
```
冲突要点：
- **main.py**：安全网代码在"推送决策"块，加 `wl_safety_net = watchlist_safety_net(event_assessment, get_tracked_tickers())` 到派发条件里；imports 加 `watchlist_safety_net` + `get_tracked_tickers`。**务必保留 main 已有的 watchdog 接线**。
- **chinese_fetcher.py**：整段 `fetch_sina_channel` 换成 zhibo 版 + 新增 `_parse_zhibo_feed`/`_split_zhibo_richtext`；`fetch_all` 里 sina 从 4 频道改为 1 次 `{"name":"7x24"}`。

## 验证（合并后）
```bash
cd D:/class1/news-monitor
python -m pytest tests/test_watchlist_safety_net.py tests/test_chinese_fetcher.py tests/test_event_driven_evaluator.py -q
# 真实 live 抓取自检（应 fetched > 0，标题正常）：
python -c "import asyncio;from collector.chinese_fetcher import ChineseNewsFetcher as F;\
print(asyncio.run(F({'max_items_per_source':10,'sina_channels':[{'name':'7x24'}]}).fetch_sina_channel({'name':'7x24'})).__len__())"
python -c "from engine.relevance import get_tracked_tickers;print(len(get_tracked_tickers()))"   # 应 74
```

## 部署（生产=main，走 git，不要 scp）
```bash
git push origin main
ssh root@47.76.50.77 "cd /opt/news-monitor && git pull && cd news-monitor/docker && docker compose up -d --build"
# 验证：
ssh root@47.76.50.77 "docker logs news-monitor --since 3m 2>&1 | grep -E '新浪财经\[7x24\]|Watchlist safety net|Watchdog:'"
# 期望：看到 '新浪财经[7x24]: N items fetched'（不再是 [科技] 403）
```

## 紧急度
生产现跑 main：**新浪 403 已回来**（`新浪财经[科技]: HTTP 403`）、关注股安全网缺失、只 21 关注股。看门狗时区 main 已自修，无误警笛风险。尽快执行以恢复中文源 + 安全网。
