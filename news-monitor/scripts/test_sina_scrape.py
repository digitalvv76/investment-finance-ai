"""Quick test: can Playwright scrape Sina finance live page?"""
import asyncio
from playwright.async_api import async_playwright


async def test():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    page = await browser.new_page()
    await page.set_extra_http_headers({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        ),
    })
    await page.goto(
        "https://finance.sina.com.cn/7x24/",
        wait_until="domcontentloaded",
        timeout=15000,
    )
    await asyncio.sleep(3)

    print(f"Title: {await page.title()}")

    # Raw link count
    raw = await page.evaluate("document.querySelectorAll('a').length")
    print(f"Total <a> tags: {raw}")

    # Count sina.com.cn links
    sina_count = await page.evaluate("""() => {
        var links = document.querySelectorAll('a');
        var c = 0;
        for (var i = 0; i < links.length; i++) {
            if (links[i].href && links[i].href.includes('sina.com.cn')) c++;
        }
        return c;
    }""")
    print(f"Links with sina.com.cn: {sina_count}")

    # The actual scraper filter
    headlines = await page.evaluate("""() => {
        var items = [];
        var seen = {};
        var links = document.querySelectorAll('a');
        for (var i = 0; i < links.length; i++) {
            var a = links[i];
            var title = (a.textContent || '').trim();
            var href = a.href || '';
            if (title.length > 15 && !seen[href] &&
                (href.includes('sina.com.cn') || href.includes('/roll/') ||
                 href.includes('/detail-'))) {
                seen[href] = true;
                items.push({title: title.substring(0, 100), url: href.substring(0, 120)});
            }
        }
        return items.slice(0, 5);
    }""")
    print(f"Matched headlines: {len(headlines)}")
    for h in headlines:
        print(f"  [{h['title']}]")
        print(f"   {h['url']}")

    # Dump a few raw link texts for diagnosis
    raw_samples = await page.evaluate("""() => {
        var links = document.querySelectorAll('a');
        var samples = [];
        for (var i = 0; i < Math.min(10, links.length); i++) {
            var a = links[i];
            samples.push({
                text: (a.textContent || '').trim().substring(0, 60),
                href: (a.href || '').substring(0, 100),
            });
        }
        return samples;
    }""")
    print("\nFirst 10 raw links:")
    for s in raw_samples:
        print(f"  [{s['text']}]")
        print(f"   → {s['href']}")

    await browser.close()
    await pw.stop()


if __name__ == "__main__":
    asyncio.run(test())
