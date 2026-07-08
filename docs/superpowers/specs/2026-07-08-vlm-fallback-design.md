# VLM Visual Extraction Fallback — Design Spec

**Date**: 2026-07-08
**Phase**: V2 Phase 4b
**Scope**: `collector/web_scraper.py` + `config/prompts/vlm_extract.txt`

## Problem

`web_scraper.py` uses hardcoded CSS selectors and JS evaluate() to extract headlines from 4 sources (Sina, WallstreetCN, CNBC, MarketWatch). These selectors break every time the source site redesigns, requiring manual fixes. Historical breakage: 5+ fixes in one week (July 7).

## Design

### Architecture

```
_scrape_*(page):
  try CSS/JS extraction (existing)
    if results >= min_threshold → return results, reset fail counter
    if results < min_threshold → increment fail counter

  if fail_counter >= 3:
    try VLM extraction:
      screenshot_bytes = page.screenshot(memory)
      response = anthropic.messages.create(
        model="claude-haiku-4-5-20251001",
        messages=[{image: screenshot_bytes, prompt: VLM_EXTRACT_PROMPT}]
      )
      headlines = parse_json(response)
      return headlines
```

### VLM: Claude Haiku

- Already configured (`ANTHROPIC_API_KEY` in .env)
- Vision-capable, ~$0.005/image, ~3s latency
- System prompt: `config/prompts/vlm_extract.txt`

### Trigger Logic

- Per-source fail counter (in-memory dict, keyed by source name)
- Counter resets on any successful CSS extraction
- VLM triggered on counter >= 3 consecutive empty/near-empty results
- VLM runs for 1 hour, then forces CSS retry (cool-down)
- VLM failure falls through to empty list (no crash)

### VLM Output Schema

```json
[{"title": "...", "url": "https://...", "snippet": "..."}]
```

Directly compatible with existing `_scrape_*` return format.

### ECS Impact

| Resource | Delta |
|----------|-------|
| CPU | 0 (API call) |
| Memory | +500KB (screenshot buffer, released after call) |
| Disk IOPS | 0 (no disk write) |
| Network | +200-500KB upload per VLM call |

### Cost Estimate

- Normal month: $0-3 (CSS works most of the time)
- Worst month: $15-30 (all 4 sources down, with cool-down)

## Files Changed

| File | Change |
|------|--------|
| `news-monitor/collector/web_scraper.py` | +VLM extraction method + fail counter + cool-down logic (~80 lines) |
| `news-monitor/config/prompts/vlm_extract.txt` | VLM system prompt (~20 lines) |
| `news-monitor/tests/test_web_scraper.py` | +VLM fallback tests (mock API) |

## Non-Goals

- Does NOT replace CSS selectors — VLM is fallback only
- Does NOT change the downstream pipeline
- Does NOT add new dependencies (uses existing `anthropic` SDK)
- Does NOT add VLM to Twitter/RSS/Playwright fetchers
