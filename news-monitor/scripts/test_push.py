"""快速测试手机推送 — 展示新的分析师笔记 + ETF 映射格式"""
import asyncio, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

import aiohttp
from bot.formatters import format_pushover_alert, format_fast_alert, _build_ticker_etf_line


async def test_telegram():
    """发一条 Telegram 测试消息（含分析师笔记 + ETF 映射）"""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("❌ TELEGRAM_BOT_TOKEN 未配置")
        return False

    async with aiohttp.ClientSession(trust_env=True) as session:
        url = f"https://api.telegram.org/bot{token}/getUpdates"
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                data = await resp.json()
        except Exception as e:
            print(f"❌ Telegram 连接失败: {e}")
            return False

        if not data.get("ok") or not data.get("result"):
            print("❌ Telegram: 没有找到活跃对话。")
            print("   请先在 Telegram App 里给你的 Bot 发一条消息（随便发什么都行），然后重新运行本脚本。")
            return False

        chat_id = data["result"][-1]["message"]["chat"]["id"]
        print(f"   找到 chat_id: {chat_id}")

    # 模拟一条真实新闻，展示新格式
    test_item = {
        "id": 9999,
        "title": "Nvidia cuts Q3 revenue guidance amid export restrictions",
        "source": "Bloomberg",
        "url": "https://www.bloomberg.com",
        "tickers_found": "NVDA, AMD",
        "macro_tags": "CHIPS, AI",
    }

    # 模拟分析师笔记
    analyst_note = (
        "英伟达下调Q3营收指引，幅度超出我们预期，"
        "主因对华出口限制收紧。我们认为短期半导体板块将承压，"
        "但AI投资主线基本面未变。建议关注今晚股价反应——"
        "若跌幅超5%反而是较好的入场窗口。"
    )

    text = format_fast_alert(test_item, analyst_note=analyst_note,
                             event_category="corporate",
                             impact_score=78, confidence=82)
    print("  推送内容预览:")
    print("  " + "-" * 48)
    for line in text.split("\n"):
        print(f"  {line}")
    print("  " + "-" * 48)

    async with aiohttp.ClientSession(trust_env=True) as session:
        send_url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "disable_notification": False}
        try:
            async with session.post(send_url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    print("✅ Telegram 测试消息已发送（新格式）")
                    return True
                else:
                    body = await resp.text()
                    print(f"❌ Telegram 发送失败: {resp.status} {body}")
                    return False
        except Exception as e:
            print(f"❌ Telegram 发送失败: {e}")
            return False


async def test_pushover():
    """发一条 Pushover 测试消息（含分析师笔记 + ETF 映射）"""
    token = os.environ.get("PUSHOVER_APP_TOKEN", "")
    user = os.environ.get("PUSHOVER_USER_KEY", "")

    if not token or not user:
        print("⚠️  Pushover 未配置，跳过")
        return None

    test_item = {
        "id": 9999,
        "title": "Nvidia cuts Q3 revenue guidance amid export restrictions",
        "source": "Bloomberg",
        "url": "https://www.bloomberg.com",
        "tickers_found": "NVDA, AMD",
        "macro_tags": "CHIPS, AI",
    }

    analyst_note = (
        "英伟达下调Q3营收指引，幅度超出我们预期，"
        "主因对华出口限制收紧。我们认为短期半导体板块将承压，"
        "但AI投资主线基本面未变。"
    )

    title, body = format_pushover_alert(
        test_item,
        title_cn="英伟达因出口限制下调Q3营收指引",
        analyst_note=analyst_note,
        event_category="corporate",
        impact_score=78,
        confidence=82,
    )

    print("  Pushover 推送内容:")
    print(f"  标题: {title}")
    print(f"  正文: {body[:100]}...")

    payload = {
        "token": token, "user": user,
        "title": title, "message": body,
        "priority": 0,
        "sound": "pushover",
    }

    async with aiohttp.ClientSession() as session:
        url = "https://api.pushover.net/1/messages.json"
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status == 200:
                print("✅ Pushover 测试消息已发送（新格式）")
                return True
            else:
                body_text = await resp.text()
                print(f"❌ Pushover 发送失败: {resp.status} {body_text}")
                return False


async def main():
    print("=" * 50)
    print("  📱 手机推送测试 — 新格式")
    print("=" * 50)
    print()
    print("  模拟新闻: NVDA 下调Q3营收指引")
    print("  分析师笔记 + ETF 映射")
    print()

    results = await asyncio.gather(test_telegram(), test_pushover())

    print()
    print("---")
    tg_ok, po_ok = results
    if tg_ok:
        print("✅ Telegram 正常（新格式）")
    elif tg_ok is False:
        print("❌ Telegram 失败")
    else:
        print("— Telegram 未测试")

    if po_ok:
        print("✅ Pushover 正常（新格式）")
    elif po_ok is False:
        print("❌ Pushover 失败")
    else:
        print("— Pushover 未配置")

    print()
    if tg_ok and po_ok:
        print("🎉 双通道都正常！")
    print()
    print("  预期推送效果:")
    print("  ┌─────────────────────────────────────┐")
    print("  │ 📰 【NVDA, AMD】彭博社               │")
    print("  │ Nvidia cuts Q3 revenue guidance...  │")
    print("  │                                     │")
    print("  │ 💥 冲击: 78分 | 置信度: 82%          │")
    print("  │                                     │")
    print("  │ 英伟达下调Q3营收指引，幅度超出我们     │")
    print("  │ 预期，主因对华出口限制收紧...         │")
    print("  │                                     │")
    print("  │ 🎯 相关标的: NVDA(英伟达) AMD(...)   │")
    print("  │   板块ETF: QQQ(纳指100) SMH(半导体)...│")
    print("  │ 🔗 https://www.bloomberg.com         │")
    print("  └─────────────────────────────────────┘")


if __name__ == "__main__":
    asyncio.run(main())
