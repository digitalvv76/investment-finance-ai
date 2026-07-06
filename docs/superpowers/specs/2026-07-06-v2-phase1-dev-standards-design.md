# V2 Phase 1: 开发规范 + 自动化

> **设计日期**: 2026-07-06  
> **状态**: 已确认，待执行  
> **目标**: 建立代码修改的安全网——改了A模块不会莫名其妙炸B模块，收尾不用人提醒

---

## 1. 背景

### V1 的技术债根因

V1 系统本身功能完整、ECS 运行稳定。但以下 5 个流程问题反复导致返工：

| 问题 | 根因 | 影响 |
|------|------|------|
| 改了代码不知道会不会炸 | 测试覆盖率不均，改了模块不跑对应测试 | 靠 ECS 上炸了才发现 |
| 提交历史一团乱 | 没有统一的提交信息格式 | 查历史排查问题困难 |
| 模块注册表过时 | 手动维护，忘了就漏 | 新增模块的测试/脚本依赖关系丢失 |
| 会话结束丢进度 | 关机前没有保存流程 | 下次会话一脸懵，13 条 commit 漏写 |
| 分支策略混乱 | main 既是开发线又是部署线 | v1 改动直接推向生产，无法隔离 |

### V2 的协作模式

- **用户**: 金融专家，做投资决策和业务判断
- **AI**: 全权负责技术实现、测试、提交、部署
- **规则**: 常规操作自主执行，不可逆操作确认后执行

---

## 2. 设计目标

1. **每次代码修改都有安全网** — 改模块自动跑测试，不过不给提交
2. **模块依赖关系自动维护** — 不靠人记，工具自动检查
3. **会话无痛衔接** — 结束自动保存，开始自动回顾
4. **提交历史可读可追溯** — 统一格式，一眼看出改了什么

---

## 3. 五项规范

### 3.1 分支策略

```
main          V2 日常开发（可以随意改）
v1-stable     V1 生产版本（只修紧急 bug，不加速新功能）
```

**规则**:
- V1 线上出问题 → 基于 `v1-stable` 创建 `fix/<description>` 分支 → 修好合入 → cherry-pick 回 `main`
- V2 所有开发都在 `main`
- `v1-stable` 永远和 ECS 上跑的代码一致

**自动化**: pre-push hook 阻止直接向 `v1-stable` 推送（必须走 fix 分支 + PR）

---

### 3.2 提交信息规范

**格式**: `<type>: <简短英文描述>`

| type | 含义 | 示例 |
|------|------|------|
| `feat` | 新功能 | `feat: add Finnhub per-ticker news fetcher` |
| `fix` | Bug 修复 | `fix: Vercel proxy missing /api/* rewrite` |
| `refactor` | 重构（功能不变） | `refactor: extract dedup logic from main loop` |
| `test` | 测试 | `test: add alert_dispatcher multi-user coverage` |
| `docs` | 文档 | `docs: update TROUBLESHOOTING with deep analysis fix` |
| `chore` | 杂项 | `chore: remove temp files, move screenshots to docs/` |

**所有 commit 自动追加**: `Co-Authored-By: Claude <noreply@anthropic.com>`

**自动化**: commit-msg hook 检查格式，不符合就拒绝

---

### 3.3 模块注册自动化

**V1 问题**: `module_registry.json` 需要手动维护，每次新增/修改模块容易忘

**V2 方案**: 每个模块自带 `__manifest__.json`

```json
{
  "name": "engine/alert_dispatcher.py",
  "description": "多通道告警分发 (Pushover + Telegram)",
  "tests": ["tests/test_alert_dispatcher.py"],
  "related_scripts": ["scripts/test_phone_alert.py"],
  "also_tests": []
}
```

**自动化**: SessionStart hook 扫描所有 `__manifest__.json`，和实际文件对比：
- 有文件但无 manifest → 警告
- 有 manifest 但测试文件不存在 → 警告
- manifest 中引用的脚本比源文件旧 → 警告

---

### 3.4 测试门禁

**规则**:
1. 每个被修改的模块**必须**有注册的测试（通过 `__manifest__.json`）
2. 测试必须全部通过才能提交
3. `[skip-tests]` 标记允许紧急绕过，但必须附带 `# TODO: add test` 注释

**触发**: pre-commit hook

**范围**: 只跑被改动模块对应的测试，不改的不跑（和 V1 一样，不浪费时间）

---

### 3.5 会话收尾自动化

**开始（已有，保留）**:
- SessionStart hook 自动展示：上次操作摘要 + 未提交改动 + 陈腐脚本警告

**结束（新增）**:
- 用户说"结束/关机/下班/今天就到这里"→ AI 自动执行：
  1. `git status` — 确保无未提交改动
  2. HISTORY.md — 确保本次操作已写入
  3. SESSION.md — 更新「进行中」「下一步」
  4. `git push origin main`

---

## 4. 文件变更清单

| 文件 | 动作 | 说明 |
|------|------|------|
| `news-monitor/config/module_registry.json` | 废弃 | 被 `__manifest__.json` 替代 |
| `news-monitor/*/__manifest__.json` | 新建 | 每个模块一个 manifest |
| `.claude/hooks/commit-msg` | 新建 | 提交格式检查 |
| `.claude/hooks/pre-commit` | 更新 | 加入 manifest 检查和测试门禁 |
| `.claude/hooks/pre-push` | 新建 | v1-stable 推送保护 |
| `.claude/hooks/SessionEnd` | 新建 | 关机前检查 |
| `scripts/pre_commit_check.py` | 更新 | 适配 manifest 体系 |

---

## 5. 不影响线上

Phase 1 改的全是开发流程（hooks、manifest、提交规范），**完全不影响 ECS 上运行的 V1 系统**。代码一行不改。

---

## 6. 验收标准

- [ ] 有 manifest 的模块，改了代码自动跑对应测试
- [ ] 没 manifest 的模块，提交被拒绝
- [ ] 提交信息不符合格式被拒绝
- [ ] 说"结束"自动执行保存检查
- [ ] 直接推 v1-stable 被阻止
- [ ] 所有现有模块的 `__manifest__.json` 已创建
