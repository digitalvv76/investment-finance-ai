# 🩹 踩坑记录 — 问题 → 根因 → 修复

> 每次发现并解决问题后，追加一条。下次遇到同样症状直接查这里，不要重新排查。

---

## ECS / 部署

### ECS 重启后 SSH 不通
**症状**: 重启 ECS 后 `ssh root@47.76.50.77` 连不上，VNC 能进。
**根因**: `sshd` 没设开机自启，阿里云「重置密码」只改 VNC 不管 OS。
**修复**: VNC 登录后执行：
```bash
echo 'root:<password>' | chpasswd
sed -i 's/^#PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
sed -i 's/^PasswordAuthentication no/PasswordAuthentication yes/' /etc/ssh/sshd_config
systemctl enable sshd && systemctl restart sshd
```
**验证**: `ssh root@47.76.50.77 "echo OK"`

### ECS 内存耗尽 (2GB)
**症状**: 负载 25.9，空闲内存 96MB，I/O 等待 76.5%。
**根因**: Chromium + Python + spaCy + sentence-transformers 四个大户同时跑在 2GB 机器上。
**修复**: 关闭 Web Dashboard (WEB_PORT=0)、清空 Twitter/Playwright 源、停 Nginx/snapd。结果：负载 25.9→0.07，内存 1293MB→465MB。
**长期**: 考虑升级到 4GB 后恢复 Twitter 采集。

### ECS 云盘 IOPS 过载导致服务不可用 (2026-07-08)
**症状**: 阿里云告警 "云盘读写IO延迟过长或IOPS上限"。SSH 超时，Vercel 502，容器日志为空。
**根因**: 采集任务瞬时集中爆发（爬虫+模型+浏览器+Docker存储层叠加），IOPS 冲破云盘上限。
**修复**:
1. 轻量应用服务器控制台 → 强制重启实例
2. journald 限 50MB: `journalctl --vacuum-size=50M` + `/etc/systemd/journald.conf` 配 `SystemMaxUse=50M`
3. Docker 日志轮转: `/etc/docker/daemon.json` 配 `max-size:10m max-file:3`
**预防**: 观察是否复发，若频繁则升级套餐（轻量服务器不能单独升云盘）。
**验证**: `ssh root@47.76.50.77 "docker ps"` + `curl https://class1-cyan.vercel.app/api/health`

### ECS Docker 构建时网络问题
**症状**: `docker compose build` 卡在下载/安装阶段。
**根因**: 阿里云 ECS 访问 GitHub/Docker Hub 可能受限。
**修复**: 耐心等，一般能过。实在不行配 Docker mirror。

---

## 推送 / 新闻管道

### 改了 alert_dispatcher 阈值后测试失败
**症状**: 改了 CRITICAL_PRIORITY 或 IMPORTANT_PRIORITY，跑测试挂了 7 个。
**根因**: `test_alert_dispatcher.py` 和 `test_impact_push.py` 里硬编码了阈值相关的断言。
**修复**: 改阈值时必须同步更新测试用例中的期望值。或者跑 `calibrate_thresholds.py --apply` 它会自动处理。

### 非美国政治新闻漏过推送（伊朗葬礼）
**症状**: 伊朗国葬新闻触发了 Pushover 推送。
**根因**: StrategicDetector 命中 "government" 关键词后绕过了 geo_market_filter。伊朗在非美政治名单里，但没有写"葬礼/国葬"等事件关键词。
**修复**: FastLane 里加了 `geo_mult > 0.2` 检查——非美政治事件即使命中战略检测也不能绕过地理过滤。

### Telegram 推送突然变英文
**症状**: 之前推送过中文，后来变成纯英文。
**根因**: Pushover 修改时不小心改动了 Telegram formatter，translator 模块重构时 Telegram bot 漏接了 translator。
**修复**: 确保 `bot/telegram_bot.py` 的 `push_alert()` 调用了 `get_translator().translate()`。

### 深度分析链接显示错误新闻 (2026-07-06)
**症状**: Pushover 卡片点击"🔍 深度分析"后，手机浏览器打开的页面显示不相关的标题/来源。
**根因**:
1. `WEB_DASHBOARD_URL` 设为 HTTP 裸 IP (`http://47.76.50.77:8080`)，手机上不可靠
2. Vercel (`class1-cyan.vercel.app`) 没有配置 `/api/*` 代理到 ECS
3. 没有 HTTPS → 部分手机浏览器拦截或降级
**修复**:
1. `vercel.json` 添加 rewrite: `/api/:path*` → `http://47.76.50.77:8080/api/:path*`
2. ECS `WEB_DASHBOARD_URL` 改为 `https://class1-cyan.vercel.app`
3. Docker 重建
**预防**: 新增任何需要手机浏览器打开的 web API 端点时，必须同步更新 Vercel rewrite 规则。原则：手机端只用 HTTPS 域名，所有 API 通过 Vercel 代理到 ECS。

### requirements.txt 漏了依赖
**症状**: ECS 部署后 `import yfinance` 失败。
**根因**: 在本地 `pip install yfinance` 后忘了 `pip freeze > requirements.txt`。
**修复**: 手动加了 `yfinance` 到 requirements.txt。以后加任何依赖先更新 requirements.txt。

---

## 开发 / 测试

### ChromaDB 测试在 Windows 上报错
**症状**: 6-7 个 ChromaDB 相关测试报 "file lock" 或 "permission" 错误。
**根因**: Windows 文件锁定机制与 ChromaDB 的 SQLite 后端冲突，无法修复。
**处理**: `dev_checklist.py` 已容忍 ChromaDB 错误，不计入测试失败。`session_startup.py` 报告为已知问题。

### main.py 语法错误 `def_collect`
**症状**: `AttributeError: 'NewsMonitor' object has no attribute 'def_collect'`
**根因**: 手误把 `def _collect_impact_outcomes` 写成了 `def_collect_impact_outcomes`。
**修复**: `def_collect` → `def _collect` (加空格)。

### 新增模块后 session_startup.py 警告
**症状**: 启动时看到 "unregistered module" 警告。
**根因**: `config/module_registry.json` 没更新——新增 web/* 和 translator 模块后没注册。
**修复**: 新增模块时同步更新 `module_registry.json`，写清楚 tests/related_scripts/also_tests。

### 修改 config/sources.yaml 后采集失败
**症状**: RSS 采集报错，部分源返回空。
**根因**: Yahoo Finance RSS 被封锁、Investing.com 加了 Cloudflare、Bloomberg RSS 死链。直接用别人推荐的 RSS URL 不一定能从中国/ECS 访问。
**修复**: 每个源都要实测。当前已验证可用的源：CNBC/WSJ/MarketWatch/Seeking Alpha/CNBC Economy。

---

## Twitter / Playwright

### Twitter 采集全部失败
**症状**: 试了 8 种方案全部不可用。
| 方案 | 失败原因 |
|------|----------|
| Nitter RSS (16实例) | Cloudflare 封杀 |
| Twitter v1.1 API | 已废弃 |
| GraphQL API | guest token 被禁用 |
| Playwright 直接抓取 | 强制登录墙 |
| snscrape | Python 3.12 不兼容 |
| twikit | 加密协议不兼容 |
| Chrome cookie 提取 | App-Bound Encryption 加密 |
| ✅ Playwright + auth_token Cookie | **唯一可用方案** |

**最终方案**: user X 账号 auth_token → `.env` (TWITTER_AUTH_TOKEN)，Playwright 注入 Cookie 绕过登录。

### Playwright 浏览器没装
**症状**: `playwright._impl._errors.Error: Executable doesn't exist`
**修复**: `playwright install chromium`

---

## 凭证 / 环境变量

### .env 和 settings.json 不同步
**症状**: 加了新 API key 到 `.env`，但代码里读不到。
**根因**: `settings.json` 的 env 段没有同步更新。
**修复**: 编辑 `.env` 后运行 `python news-monitor/scripts/sync_env_to_settings.py`。SessionStart hook 会自动检查同步状态。

### .env 从备份恢复后格式问题
**症状**: 恢复的 `.env` 文件包含 `export ` 前缀，Windows 不认。
**修复**: 从 `.claude/backups/state/<latest>/.env` 恢复时，注意去掉 `export ` 前缀。

---

## Telegram

### chat_id 丢失 → Telegram 推送静默失败
**症状**: HTTP 200 但手机收不到，或 `push_alert()` 静默返回无报错。
**根因**: `preferences` 表里 `telegram_chat_id` 为空。Docker 重建时数据库 volume 可能被重置。
**修复**: 
1. 手动写入：`INSERT INTO preferences VALUES ('telegram_chat_id', '7305690438', datetime('now'))` 
2. 现在启动时自动检测——`_auto_detect_chat_id()` 会调 Telegram API 找回
**预防**: 
- Docker volume `news_data` 持久化数据库
- 启动时自动运行 `_auto_detect_chat_id()`
- 每次收到 `/start` 自动更新 chat_id

## Git / 部署

### HISTORY.md 漏写导致下次会话不知道做了什么
**症状**: 每次会话开始只看 HISTORY.md，如果上次没写，上下文就丢了。
**根因**: 开发太投入忘了追加。没有自动化检查。
**预防**: SessionStart hook 现在会检查 git log vs HISTORY.md 的同步状态，缺了会告警。

### GitHub push 被网络阻断
**症状**: `git push origin main` 超时或连接拒绝。
**修复**: 用 SSH 替代 HTTPS：`git remote set-url origin git@github.com:digitalvv76/investment-finance-ai.git`。或者等网络恢复。

### git push 前没跑测试
**症状**: 改了代码直接 push，到 ECS 上才报错。
**根因**: 跳过了 commit hook。
**预防**: `pre_commit_check.py` 在每次 `git commit` 时自动跑被修改模块的测试。紧急情况用 `[skip-tests]` 标记可以跳过。

---

## LLM / DeepSeek

### DeepSeek API 超时
**症状**: ImpactEvaluator 卡住，日志 "timed out"。
**根因**: DeepSeek API 偶尔响应慢或不可用。
**修复**: 加了 30s SDK timeout + 45s asyncio hard timeout。自动 fallback 到 Anthropic（如果配置了 ANTHROPIC_API_KEY）。

### DeepSeek 翻译乱码或漏译
**症状**: 中文翻译输出空白或与原文无关。
**根因**: DeepSeek 偶尔不遵循翻译指令，返回原文或随机内容。
**修复**: `translator.py` 加了长度检查，翻译结果如果和原文一样长或为空，回退到英文标题。

---

> **使用方式**: 遇到问题 → 解决后立即追加一条到这里。下次看 SESSION.md 之前先扫一眼最近 3 条。
