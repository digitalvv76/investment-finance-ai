# -*- coding: utf-8 -*-
"""Test phone push — Pushover + Telegram with Chinese formatting.
Usage: python scripts/test_signal.py [pushover|telegram|both|critical|fast|deep]
"""
import asyncio, os, sys

# Add news-monitor to path for formatters import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "news-monitor"))

# Force UTF-8 on Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore
    except Exception:
        pass

# Load .env
env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
with open(env_path, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from bot.formatters import format_fast_alert, format_deep_analysis, _translate_source


# ---------------------------------------------------------------------------
# Realistic Chinese test items
# ---------------------------------------------------------------------------

FAST_ALERT_ITEMS = [
    {   # NVDA AI chip news
        "tickers_found": "NVDA",
        "source": "reuters",
        "title": "英伟达宣布新一代 Blackwell AI 芯片Q4量产，性能提升4倍",
        "url": "https://www.reuters.com/technology/nvidia-blackwell-q4-2026-07-04/",
        "macro_tags": "",
        "impact_assessment": {"impact_score": 75, "direction": "up"},
    },
    {   # Fed monetary policy
        "tickers_found": "SPX,QQQ",
        "source": "bloomberg",
        "title": "美联储 Warsh 暗示9月可能降息：通胀数据连续3月回落至3.1%",
        "url": "https://www.bloomberg.com/news/articles/2026-07-04/fed-warsh-signals-september-cut",
        "macro_tags": "URGENT",
        "impact_assessment": {"impact_score": 88, "direction": "up"},
    },
    {   # Government intervention
        "tickers_found": "INTC",
        "source": "wsj",
        "title": "美国商务部批准向英特尔拨款85亿美元芯片法案补贴",
        "url": "https://www.wsj.com/tech/intel-chips-act-grant-2026-07-04",
        "macro_tags": "STRATEGIC_GOV_INTERVENTION",
        "impact_assessment": {"impact_score": 82, "direction": "up"},
    },
]

DEEP_ANALYSIS_ITEM = {
    "tickers_found": "NVDA",
    "source": "reuters",
    "title": "英伟达 Blackwell Q4量产 + 台积电独家代工",
    "market_impact": "high",
    "sentiment": "bullish",
    "sentiment_score": 0.72,
    "portfolio_impact": "NVDA (权重 15%)",
    "llm_analysis": (
        "1) Blackwell Q4量产确认，性能4倍提升将引爆新一轮AI基建投资\n"
        "2) 台积电CoWoS产能已锁死至2027，供给壁垒极高\n"
        "3) 当前PE 29.86低于5年均值35，估值有安全边际\n"
        "4) 风险：美中芯片管制进一步收紧可能影响对华销售"
    ),
}


# ---------------------------------------------------------------------------
# Test functions
# ---------------------------------------------------------------------------

async def test_pushover_fast():
    """Pushover: 快速新闻推送 (中文)"""
    import aiohttp
    token = os.environ.get("PUSHOVER_APP_TOKEN", "")
    user = os.environ.get("PUSHOVER_USER_KEY", "")

    if not token or not user:
        print("[X] Pushover credentials missing.")
        return

    item = FAST_ALERT_ITEMS[1]  # Fed rate cut — most impactful
    source_cn = _translate_source(item["source"])
    title = item["title"]
    impact = item["impact_assessment"]

    msg = f"【{item['tickers_found']}】{source_cn}\n{title}\n💥 预估冲击: {impact['impact_score']}分 📈"

    async with aiohttp.ClientSession() as session:
        payload = {
            "token": token, "user": user,
            "title": "🚨 紧急快讯",
            "message": msg,
            "priority": 1,
            "sound": "persistent",
        }
        async with session.post("https://api.pushover.net/1/messages.json", json=payload) as resp:
            body = await resp.text()
            if resp.status == 200:
                print("[OK] Pushover 中文快讯: sent")
            else:
                print(f"[X] Pushover failed [{resp.status}]: {body}")


async def test_telegram_fast():
    """Telegram: 快速新闻推送 (中文格式化)"""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("[X] TELEGRAM_BOT_TOKEN missing")
        return

    chat_id = int(os.environ.get("TG_CHAT_ID", "7305690438"))
    from telegram import Bot
    bot = Bot(token=token)

    for i, item in enumerate(FAST_ALERT_ITEMS):
        msg = format_fast_alert(item)
        try:
            sent = await bot.send_message(
                chat_id=chat_id, text=msg,
                disable_notification=(i > 0),  # only first one vibrates
            )
            print(f"[OK] Telegram 中文快讯 #{i+1}: sent (msg_id={sent.message_id})")
        except Exception as e:
            print(f"[X] Telegram #{i+1} failed: {e}")
        await asyncio.sleep(0.3)


async def test_telegram_deep():
    """Telegram: 深度分析推送 (中文)"""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("[X] TELEGRAM_BOT_TOKEN missing")
        return

    chat_id = int(os.environ.get("TG_CHAT_ID", "7305690438"))
    from telegram import Bot
    bot = Bot(token=token)

    msg = format_deep_analysis(DEEP_ANALYSIS_ITEM)
    try:
        sent = await bot.send_message(chat_id=chat_id, text=msg, disable_notification=False)
        print(f"[OK] Telegram 中文深度分析: sent (msg_id={sent.message_id})")
    except Exception as e:
        print(f"[X] Telegram deep failed: {e}")


async def test_critical_chinese():
    """CRITICAL 中文紧急推送 — Pushover 警笛 + Telegram 三连推"""
    print("\n--- 中文 CRITICAL 紧急推送模拟 ---")

    import aiohttp
    token = os.environ.get("PUSHOVER_APP_TOKEN", "")
    user = os.environ.get("PUSHOVER_USER_KEY", "")
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = int(os.environ.get("TG_CHAT_ID", "7305690438"))

    # Use the most critical item (Fed)
    item = FAST_ALERT_ITEMS[1]
    source_cn = _translate_source(item["source"])

    # === Pushover 警笛 ===
    if token and user:
        async with aiohttp.ClientSession() as session:
            payload = {
                "token": token, "user": user,
                "title": "🚨 极高冲击力警报",
                "message": (
                    f"🏛️ 政府干预\n"
                    f"【{item['tickers_found']}】{source_cn}\n"
                    f"{item['title']}\n"
                    f"💥 预估冲击: 88分 | 置信度: 高\n"
                    f"[TAG:CRITICAL]"
                ),
                "priority": 2,
                "sound": "spacealarm",
                "retry": 30,
                "expire": 300,
            }
            async with session.post("https://api.pushover.net/1/messages.json", json=payload) as resp:
                body = await resp.text()
                if resp.status == 200:
                    print("[OK] Pushover 中文紧急警笛: sent — 请检查手机!")
                else:
                    print(f"[X] Pushover failed [{resp.status}]: {body}")
    else:
        print("[!] Pushover 凭证缺失")

    # === Telegram 三连推 ===
    if tg_token:
        from telegram import Bot
        bot = Bot(token=tg_token)
        try:
            # Msg 1: TAG banner
            await bot.send_message(
                chat_id=chat_id,
                text=f"🚨🚨🚨 [TAG:CRITICAL] 极高冲击力警报 🚨🚨🚨",
                disable_notification=False,
            )
            await asyncio.sleep(0.5)

            # Msg 2: Full Chinese alert
            alert_msg = format_fast_alert(item)
            await bot.send_message(
                chat_id=chat_id, text=alert_msg,
                disable_notification=False,
            )
            await asyncio.sleep(0.5)

            # Msg 3: Action hint
            await bot.send_message(
                chat_id=chat_id,
                text=">>> 📱 请立即查看详情并评估持仓影响 <<<",
                disable_notification=False,
            )
            print("[OK] Telegram 中文三连推: sent (3条, 500ms间隔)")
        except Exception as e:
            print(f"[X] Telegram 三连推 failed: {e}")
    else:
        print("[!] Telegram 凭证缺失")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "fast"
    print("=" * 55)
    print("  手机推送测试 — 中文格式化")
    print(f"  模式: {target}")
    print("=" * 55)

    if target in ("pushover", "both"):
        print("\n-- Pushover 中文快讯 --")
        await test_pushover_fast()

    if target in ("telegram", "both"):
        print("\n-- Telegram 中文快讯 --")
        await test_telegram_fast()

    if target in ("fast", "both"):
        print("\n-- Telegram 中文快讯 (3条) --")
        await test_telegram_fast()

    if target == "deep":
        print("\n-- Telegram 中文深度分析 --")
        await test_telegram_deep()

    if target == "critical":
        await test_critical_chinese()

    print("\n[Done] 测试完毕，请检查手机。")


if __name__ == "__main__":
    asyncio.run(main())
