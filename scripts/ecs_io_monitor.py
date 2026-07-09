#!/usr/bin/env python3
"""ECS IO 监控 — 每60秒检查一次磁盘IO，超标时通过 Telegram 预警。

纯读 /proc/diskstats（内核计数器），不产生额外磁盘IO。
CPU占用 < 0.1%，内存 < 15MB。
"""

import time
import os
import urllib.request
import json
import sys

# ===== 配置 =====
DISK = "vda"                    # 监控的磁盘
IOPS_WARN = 1500                # IOPS 预警阈值（读+写/s）
IOPS_CRITICAL = 2500            # IOPS 严重阈值
CHECK_INTERVAL = 60             # 检查间隔（秒）
COOLDOWN = 300                  # 告警冷却（秒），同一级别不重复发
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_IDS = os.environ.get("TELEGRAM_CHAT_IDS", "7305690438,6050796462")

# ===== 初始化 =====
STAT_FILE = "/proc/diskstats"
last_warn_at = 0
last_crit_at = 0

def get_disk_iops():
    """读取 vda 的累计 IO 次数，返回 (reads, writes)"""
    with open(STAT_FILE) as f:
        for line in f:
            parts = line.strip().split()
            if parts[2] == DISK:
                reads = int(parts[3])   # field 4: reads completed
                writes = int(parts[7])  # field 8: writes completed
                return reads, writes
    return None, None

def send_telegram(msg):
    """通过 Telegram Bot 发送告警"""
    if not TELEGRAM_TOKEN:
        print("[WARN] TELEGRAM_BOT_TOKEN not set, skipping alert")
        return
    for chat_id in TELEGRAM_CHAT_IDS.split(","):
        chat_id = chat_id.strip()
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = json.dumps({"chat_id": chat_id, "text": msg}).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            print(f"[ERROR] Telegram send failed: {e}")

def main():
    global last_warn_at, last_crit_at

    # 第一轮读数（建立基线）
    prev_r, prev_w = get_disk_iops()
    if prev_r is None:
        print(f"[ERROR] Disk '{DISK}' not found in {STAT_FILE}")
        sys.exit(1)

    print(f"[INFO] IO monitor started — watching {DISK}, check every {CHECK_INTERVAL}s")
    print(f"[INFO] Warn: {IOPS_WARN} IOPS, Critical: {IOPS_CRITICAL} IOPS, Cooldown: {COOLDOWN}s")

    while True:
        time.sleep(CHECK_INTERVAL)
        now_r, now_w = get_disk_iops()
        if now_r is None:
            continue

        # 计算每秒 IOPS（差值 / 间隔秒数）
        delta_r = now_r - prev_r
        delta_w = now_w - prev_w
        iops = (delta_r + delta_w) / CHECK_INTERVAL
        prev_r, prev_w = now_r, now_w

        now_ts = time.time()

        # 判断告警级别
        if iops >= IOPS_CRITICAL:
            if now_ts - last_crit_at > COOLDOWN:
                msg = (
                    f"🔴 ECS IO CRITICAL\n"
                    f"IOPS: {iops:.0f}/s (阈值 {IOPS_CRITICAL})\n"
                    f"读: {delta_r} 写: {delta_w} (过去{CHECK_INTERVAL}秒)\n"
                    f"时间: {time.strftime('%Y-%m-%d %H:%M:%S CST')}"
                )
                send_telegram(msg)
                last_crit_at = now_ts
                print(f"[CRIT] {msg.replace(chr(10), ' | ')}")

        elif iops >= IOPS_WARN:
            if now_ts - last_warn_at > COOLDOWN:
                msg = (
                    f"🟡 ECS IO WARNING\n"
                    f"IOPS: {iops:.0f}/s (阈值 {IOPS_WARN})\n"
                    f"读: {delta_r} 写: {delta_w} (过去{CHECK_INTERVAL}秒)\n"
                    f"时间: {time.strftime('%Y-%m-%d %H:%M:%S CST')}"
                )
                send_telegram(msg)
                last_warn_at = now_ts
                print(f"[WARN] {msg.replace(chr(10), ' | ')}")

if __name__ == "__main__":
    main()
