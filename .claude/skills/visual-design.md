---
name: visual-design
description: |-
  Visual design consistency gate. Use before writing ANY HTML/CSS/frontend code.
  Enforces reading DESIGN.md first and using the established Bloomberg dark theme palette,
  typography, and component patterns. Prevents design drift across pages.
metadata:
  type: project
  triggers:
    - design
    - UI
    - frontend
    - 页面
    - 前端
    - 视觉
    - 样式
    - html
    - css
    - style
    - new page
    - 新页面
    - component
    - 组件
---

# Visual Design Skill

## Rule (Highest Priority)

**Before writing ANY HTML/CSS, read `DESIGN.md` at `D:/class1/DESIGN.md`.**
No exceptions. No "I remember the theme." Read it every time.

This project has a unified Bloomberg Terminal Dark Theme across 5+ pages.
New pages must match. Existing pages must not drift.

---

## Workflow

### Step 1: Read DESIGN.md

Read `D:/class1/DESIGN.md` to load the current palette, typography rules, grid system, and component patterns.

### Step 2: Identify Which Patterns Apply

| Page Type | Patterns to Use |
|-----------|----------------|
| Dashboard / data-heavy | 12-col grid, panels, metric cards, TradingView chart |
| Report / analysis | Hero layout, rating badge, panel grid, mono metrics |
| Landing / marketing | Starfield bg, card grid, gradient hero |
| Utility / clock | Minimalist, large mono display |

### Step 3: Write Code

- Use CSS custom properties EXACTLY as defined (`var(--bg-primary)`, never `#0c0d14`)
- Numbers → `var(--font-mono)` font
- Labels → uppercase + letter-spacing
- No hardcoded colors (use palette vars)
- No new fonts (use Inter + JetBrains Mono stack)

### Step 4: Cross-Check

After writing, verify:
1. Does this color exist in the DESIGN.md palette? If not, add it there first.
2. Are all numbers in monospace font?
3. Are labels uppercase with letter-spacing?
4. Is the page in dark theme only? (This project has no light mode.)
5. Does it match the look-and-feel of `briefing.html`? (that's the reference page)

---

## Common Mistakes to Avoid

| Don't | Do |
|-------|-----|
| `color: #333` or `#fff` | Use `var(--text-primary)` or `var(--text-secondary)` |
| `background: white` | Use `var(--bg-panel)` or `var(--bg-secondary)` |
| `font-family: Arial` | Use Inter/Segoe UI stack or font-mono for numbers |
| Custom green `#00ff00` | Use `var(--green): #22c55e` |
| Custom red `#ff0000` | Use `var(--red): #ef4444` |
| `font-size: 12px` for labels | `font-size: 10-11px` + `text-transform: uppercase` + `letter-spacing: 1px` |
| Creating new color on the fly | Add to DESIGN.md palette first, then use |

---

## Reference Pages

| Priority | Page | Why |
|----------|------|-----|
| ★★★ | `briefing.html` | Most complete — has charts, cards, grid, status bar |
| ★★★ | `reports/nvda-report.html` | Report layout — hero, badge, panels, metrics |
| ★★ | `index.html` | Landing page — starfield, cards |
| ★★ | `news-monitor/web/static/index.html` | Dashboard — training UI, file upload |

When in doubt about how something should look, open `briefing.html` in a browser and match its style.
