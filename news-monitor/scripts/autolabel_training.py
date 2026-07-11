#!/usr/bin/env python3
"""自动标注训练样本 — 原型 (V1, 2026-07-10)

思路：系统每天自动"出题"（新闻），几小时后市场就给出"答案"（涨跌）。
本脚本翻历史新闻 → 用真实行情补上事后涨跌 → 生成带 ground-truth 强度的 JSONL。
这样训练集能自己长大，且与目标 100% 对齐。

用法:
    python scripts/autolabel_training.py --db data/news.db --limit 50 --out data/training/auto-labeled.jsonl

⚠️ 数据质量注意:
  - `tickers_found` 有子串误标(见记忆 tickers-found-unreliable)——原型取首个 ticker 并核实存在，
    真正跑量应改用 LLM ticker_hint 或先清洗。
  - 本地 news.db 只是 dev 库(带 ticker 仅 40 条)。真实跑量对生产库(ECS)。
  - 反应用"新闻当日(或次交易日) prev_close→close 的日涨跌"近似，未做盘中精确对齐。
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from datetime import datetime, timedelta

# 涨跌幅(绝对值,%) → 强度 1-5。阈值按 训练资料.docx 的真实反应校准:
# Marvell +32.5/quantum +30~33 → 5; Nokia +20/IBM +12/Rigetti +15 → 4;
# QCOM +8 intraday / +4.7 → 3; +2 → 2; <1.5 → 1。做空向(负)同样按绝对值给强度。
_INTENSITY_BANDS = [(15.0, 5), (7.0, 4), (3.0, 3), (1.5, 2), (0.0, 1)]


def move_to_intensity(move_pct):
    """真实涨跌幅(%) → 强度 1-5。None → None(无行情,不标)。绝对值定强度,符号另记方向。"""
    if move_pct is None:
        return None
    a = abs(float(move_pct))
    for threshold, score in _INTENSITY_BANDS:
        if a >= threshold:
            return score
    return 1


def _first_ticker(tickers_found: str) -> str | None:
    """取首个 ticker(原型简化;真实应用 ticker_hint)。"""
    if not tickers_found:
        return None
    t = tickers_found.split(",")[0].strip().upper()
    return t or None


def _parse_dt(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("T", " ")[:19].replace("Z", ""))
    except (ValueError, TypeError):
        return None


def fetch_reaction(ticker: str, news_dt: datetime) -> dict | None:
    """新闻发布后标的的真实日涨跌: 新闻当日(或次交易日) prev_close→close。
    返回 {move_pct, react_date, close, prev_close} 或 None(无数据/停牌/代码错)。"""
    import yfinance as yf
    start = (news_dt - timedelta(days=6)).date()
    end = (news_dt + timedelta(days=6)).date()
    try:
        df = yf.download(ticker, start=start, end=end, progress=False, threads=False)
    except Exception:
        return None
    if df is None or df.empty or "Close" not in df:
        return None
    closes = df["Close"].dropna()
    if len(closes) < 2:
        return None
    news_date = news_dt.date()
    # 第一根 date >= 新闻日 的 bar 作为反应日; 与其前一根比
    for i in range(1, len(closes)):
        bar_date = closes.index[i].date()
        if bar_date >= news_date:
            close = float(closes.iloc[i].item() if hasattr(closes.iloc[i], "item") else closes.iloc[i])
            prev = float(closes.iloc[i - 1].item() if hasattr(closes.iloc[i - 1], "item") else closes.iloc[i - 1])
            if prev == 0:
                return None
            return {"move_pct": round((close - prev) / prev * 100, 2),
                    "react_date": str(bar_date), "close": round(close, 2), "prev_close": round(prev, 2)}
    return None


def build(db_path: str, limit: int, out_path: str) -> int:
    import sqlite3
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id,title,source,url,tickers_found,published_at,macro_tags "
        "FROM news WHERE tickers_found<>'' ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()

    written = skipped = 0
    with open(out_path, "w", encoding="utf-8") as f:
        for r in rows:
            ticker = _first_ticker(r["tickers_found"])
            ndt = _parse_dt(r["published_at"])
            if not ticker or not ndt:
                skipped += 1
                continue
            reaction = fetch_reaction(ticker, ndt)
            if reaction is None:
                skipped += 1
                print(f"  skip #{r['id']} {ticker}: 无行情", file=sys.stderr)
                continue
            intensity = move_to_intensity(reaction["move_pct"])
            direction = "up" if reaction["move_pct"] > 0 else ("down" if reaction["move_pct"] < 0 else "flat")
            sample = {
                "news_id": r["id"],
                "title": r["title"][:160],
                "source": r["source"],
                "ticker": ticker,
                "published_at": r["published_at"],
                "react_date": reaction["react_date"],
                "move_pct": reaction["move_pct"],
                "intensity_label": intensity,      # ground truth 强度
                "direction": direction,
                "is_push_label": bool(intensity and intensity >= 3),
                "macro_tags": r["macro_tags"] or "",
                "label_source": "auto-market-reaction",
                "_caveat": "ticker取自tickers_found(可能误标);反应=日级近似",
            }
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")
            written += 1
            print(f"  ✓ #{r['id']} {ticker} {reaction['react_date']} {reaction['move_pct']:+.2f}% → ★{intensity} {direction}")
    print(f"\nWROTE {written} labeled samples → {out_path}  (skipped {skipped})")
    return written


def main():
    ap = argparse.ArgumentParser(description="自动标注训练样本原型")
    ap.add_argument("--db", default="data/news.db")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--out", default="data/training/auto-labeled.jsonl")
    args = ap.parse_args()
    build(args.db, args.limit, args.out)


if __name__ == "__main__":
    main()
