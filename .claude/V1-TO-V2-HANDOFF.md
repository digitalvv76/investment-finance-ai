# V1 → V2 回执：deep_lane prompt 精简 + 新闻要点

> 信道：提交进 main，V2 开工读 origin/main 即见（COLLAB-PROTOCOL §7）。
> V1 窗口 = v1-stable @ D:\class1\.claude\worktrees\v1-stable（当前 prunable，需修复）
> 来源：用户反馈 NVDA 深度分析格式问题

---

## 2026-07-14 · 改了什么

### 问题
- `b20478e` 恢复了老版 Step 1/2/3/4 格式，输出 ~1000+ 字，太冗长
- 用户要精简版 + 增加「新闻要点」段，一句话说清新闻在讲什么

### 改动（1 文件）
- `news-monitor/engine/deep_lane.py`
  - ANALYSIS_PROMPT：切回精简版（①②③④），新增「新闻要点」段在最前面，~300-350 字
  - NO_DATA_PROMPT：同步更新，保持相同结构
  - max_tokens：保持 900（精简版预算充足）

### 效果对比（同一条 NVDA 新闻 ID=4805）

**改前（Step 1/2/3/4，~1000+字）**：冗长，逐标的列价格和均线，Step 2 展开 4 个子点

**改后（新闻要点 + ①②③④，~300 字）**：
> 新闻要点：FT报道Nvidia将亚洲AI芯片客户名单缩减近半…
> ① 事件定性：…
> ② 传导路径：…
> ③ 组合映射：…
> ④ 置信度：…

### 测试
- 58 tests 绿，零破坏

### V2 待做
- [x] 已在 main `1ae02bf`（因 v1-stable 工作树损坏，直接改在 main）
- [ ] 部署 ECS：`./deploy-main.sh`
- [ ] 修 v1-stable 工作树（缺少 .git 链接，prunable）
