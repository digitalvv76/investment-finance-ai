# Design System — Investment Finance AI

All frontend pages in this project follow a unified **Bloomberg Terminal Dark Theme**.
Read this BEFORE writing any HTML/CSS.

---

## Color Palette

```css
--bg-primary:    #0c0d14;   /* Deepest background — page body */
--bg-secondary:  #13161f;   /* Secondary background — status bars, cards */
--bg-panel:      #181b26;   /* Panel background — charts, sections, hero */
--bg-hover:      #1e2130;   /* Hover state for interactive elements */
--border:        #2a2d3a;   /* Default borders */
--border-light:  #353849;   /* Lighter borders (less common) */

--text-primary:  #d1d4dc;   /* Main text */
--text-secondary:#787b86;   /* Secondary text — labels, subtitles */
--text-muted:    #5a5d6a;   /* Muted text — timestamps, minor info */

/* Semantic */
--green:  #22c55e;   /* Bullish, positive, up */
--red:    #ef4444;   /* Bearish, negative, down, warnings */
--blue:   #3b82f6;   /* Links, brand accent, info */
--purple: #8b5cf6;   /* Premium/analytics accent */
--gold:   #f59e0b;   /* Warnings, attention, important */
--cyan:   #06b6d4;   /* Crypto, alternative data */
```

### Usage Rules

- Never use pure `#000` or `#fff` — always use the palette.
- `.up` / green for bullish/positive; `.down` / red for bearish/negative.
- Blue for brand elements (`.brand span`, links).
- Gold for warnings/attention banners.

---

## Typography

### Font Stack

```css
font-family: 'Inter', 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
--font-mono: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Consolas', monospace;
```

### Rules

- **Body**: `var(--text-primary)`, Inter/Segoe UI, 14-15px base.
- **Headlines**: weight 600-800, larger sizes (22-48px).
- **Numbers**: ALWAYS `font-family: var(--font-mono)`. Prices, percentages, timestamps, scores.
- **Labels**: `text-transform: uppercase; letter-spacing: 1-1.5px; font-size: 10-13px; color: var(--text-secondary)`.
- **Chinese text**: PingFang SC / Microsoft YaHei handles CJK rendering.

---

## Layout System

### 12-Column CSS Grid

```css
display: grid;
grid-template-columns: repeat(12, 1fr);
gap: 16px;
```

Standard page layout:
- Full-width hero: `grid-column: span 12`
- Main chart: `grid-column: span 8`
- Sidebar panel: `grid-column: span 4`
- Metric cards: `grid-column: span 3` (4 per row)
- Footer/mini cards: `grid-column: span 2` (6 per row)

### Responsive Breakpoints

```css
@media (max-width: 768px) {
    /* All grid items go full-width: grid-column: span 12 */
    /* Panel padding reduces: 24px → 16px */
    /* Font sizes scale down ~20% */
}
```

### Component Patterns

**Status Bar** (top):
```css
background: var(--bg-secondary);
border-bottom: 1px solid var(--border);
padding: 10px 24px;
display: flex; justify-content: space-between; align-items: center;
```
Contains: `.brand` (left), `.clock` (right, font-mono).

**Panel** (containers):
```css
background: var(--bg-panel);
border: 1px solid var(--border);
border-radius: 10px;
padding: 24px 28px;
margin-bottom: 16px;
```
Panel title: `font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: 1.5px; color: var(--text-secondary);`

**Metric Card** (nested inside panels):
```css
background: var(--bg-secondary);
border: 1px solid var(--border);
border-radius: 8px;
padding: 16px;
```
Label: `font-size: 10px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 1px;`
Value: `font-family: var(--font-mono); font-size: 22px; font-weight: 600;`

**Live Dot** (real-time indicator):
```css
width: 8px; height: 8px;
background: var(--green);
border-radius: 50%;
animation: pulse 2s infinite;
```

**Rating Badge** (e.g., BUY/SELL):
```css
background: linear-gradient(135deg, #22c55e, #16a34a);  /* or red gradient for SELL */
border-radius: 50%;
width: 120px; height: 120px;
display: flex; flex-direction: column;
justify-content: center; align-items: center;
box-shadow: 0 0 30px rgba(34, 197, 94, 0.3);
```

---

## Charts

### TradingView Lightweight Charts

Used for all financial charts (price, indicators). Pattern:

```html
<script src="https://unpkg.com/lightweight-charts@4/dist/lightweight-charts.standalone.production.js"></script>
```

Standard config:
```js
chart = LightweightCharts.createChart(container, {
    layout: {
        background: { type: 'solid', color: '#181b26' },
        textColor: '#787b86',
    },
    grid: {
        vertLines: { color: '#2a2d3a' },
        horzLines: { color: '#2a2d3a' },
    },
    crosshair: { mode: 0 },
    timeScale: { borderColor: '#2a2d3a', timeVisible: true },
    rightPriceScale: { borderColor: '#2a2d3a' },
});
```

Line series color: `#3b82f6` (blue). Area fill: same with 0.15-0.3 opacity.

---

## Status Badges & Labels

| Badge | CSS |
|-------|-----|
| NEW | `background: var(--purple); color: #fff; font-size: 10px; padding: 2px 6px; border-radius: 4px;` |
| LIVE | Green live dot: `.live-dot { animation: pulse 2s infinite; }` |
| CRITICAL | `background: var(--red); color: #fff;` |
| WARNING | `background: var(--gold); color: #0c0d14;` |

---

## Pages using this system

| Page | Path | Key features used |
|------|------|-------------------|
| Landing | `index.html` | Starfield bg, card grid, gradient hero |
| Briefing | `briefing.html` | TradingView charts, Fear & Greed gauge, metric cards, status bar |
| NVDA Report | `reports/nvda-report.html` | Rating badge, hero layout, panel grid, mono metrics |
| Clock | `datetime.html` | Minimalist, large mono time display |
| Dashboard | `news-monitor/web/static/index.html` | Training UI, drag-drop, file upload |

---

## Before Writing Any Frontend Code

1. Read this file (`DESIGN.md`)
2. Use the CSS custom properties exactly as defined — don't invent new colors
3. If you need a color not in the palette, add it to the palette first and document here
4. All numbers in monospace font
5. All labels uppercase with letter-spacing
6. Test in dark mode only (this is a dark-theme-only project)
