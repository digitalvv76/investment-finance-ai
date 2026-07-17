#!/usr/bin/env bash
# ============================================================================
# backup_db.sh — 每日备份 SQLite + ChromaDB 到 /opt/news-monitor/backups/
# ============================================================================
# 由 cron 每天凌晨 03:00 CST 触发。保留最近 7 天。
# sqlite3 由 Docker 容器内的 Python 提供；tar 在 host 上运行。
# ============================================================================
set -euo pipefail

DATA_DIR="/var/lib/docker/volumes/docker_news_data/_data"
BACKUP_DIR="/opt/news-monitor/backups"
TIMESTAMP=$(date +%Y%m%d)
BACKUP_FILE="${BACKUP_DIR}/backup-${TIMESTAMP}.tar.gz"
CONTAINER="news-monitor"

mkdir -p "$BACKUP_DIR"

# 1. SQLite backup — 用容器内 Python sqlite3 模块
echo "[backup] SQLite backup..."
docker exec "$CONTAINER" python -c "
import sqlite3, shutil
for db in ('news.db', 'news_monitor.db'):
    src = f'/app/data/{db}'
    dst = f'/app/data/{db}.backup'
    conn = sqlite3.connect(src)
    bkp = sqlite3.connect(dst)
    conn.backup(bkp)
    bkp.close()
    conn.close()
    shutil.copy(dst, f'/app/logs/{db}.backup')
" 2>&1
# .backup 文件在 volume 里，通过 logs volume 出来（logs 也在 Docker volume 里）
# 实际路径：docker exec 写的 /app/logs/ → host 的 /var/lib/docker/volumes/docker_news_logs/_data/
LOGS_DIR="/var/lib/docker/volumes/docker_news_logs/_data"
cp "${LOGS_DIR}/news.db.backup" "${BACKUP_DIR}/news-${TIMESTAMP}.db"
cp "${LOGS_DIR}/news_monitor.db.backup" "${BACKUP_DIR}/news_monitor-${TIMESTAMP}.db"
rm -f "${LOGS_DIR}/news.db.backup" "${LOGS_DIR}/news_monitor.db.backup"

# 2. ChromaDB — 直接 tar host volume
echo "[backup] ChromaDB..."
tar -czf "${BACKUP_DIR}/chroma-${TIMESTAMP}.tar.gz" -C "${DATA_DIR}" chroma/

# 3. 打包
echo "[backup] 打包..."
tar -czf "$BACKUP_FILE" \
    -C "$BACKUP_DIR" \
    "news-${TIMESTAMP}.db" \
    "news_monitor-${TIMESTAMP}.db" \
    "chroma-${TIMESTAMP}.tar.gz"

# 4. 清理临时文件
rm -f "${BACKUP_DIR}/news-${TIMESTAMP}.db" \
      "${BACKUP_DIR}/news_monitor-${TIMESTAMP}.db" \
      "${BACKUP_DIR}/chroma-${TIMESTAMP}.tar.gz"

# 5. 保留最近 7 天
find "$BACKUP_DIR" -name 'backup-*.tar.gz' -mtime +7 -delete

# 6. 恢复验证 — 用容器内 sqlite3 解压并确认可读
RESTORE_DIR=$(mktemp -d)
tar -xzf "$BACKUP_FILE" -C "$RESTORE_DIR" 2>/dev/null
# 把解压的 db 复制到数据卷，让容器内 Python 验证
cp "${RESTORE_DIR}/news-${TIMESTAMP}.db" "${DATA_DIR}/_restore_test.db"
VERIFY_OK=$(docker exec "$CONTAINER" python -c "
import sqlite3
conn = sqlite3.connect('/app/data/_restore_test.db')
tables = conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()
print('OK' if tables else 'FAIL')
conn.close()
" 2>&1)
rm -f "${DATA_DIR}/_restore_test.db"
if echo "$VERIFY_OK" | grep -q "OK"; then
  echo "[backup] ✅ 恢复验证通过"
else
  echo "[backup] ❌ 恢复验证失败！备份文件可能损坏: ${BACKUP_FILE}" >&2
  rm -rf "$RESTORE_DIR"
  exit 1
fi
rm -rf "$RESTORE_DIR"

echo "[backup] ✅ 完成 — ${BACKUP_FILE} ($(du -h "$BACKUP_FILE" | cut -f1))"
