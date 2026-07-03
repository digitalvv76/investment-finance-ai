---
name: db-migration
description: |-
  Safe database schema migration workflow. Use before ANY schema change: ALTER TABLE,
  CREATE TABLE, DROP TABLE, column add/remove/rename, index changes, or datatype changes
  in SQLite (news.db) or ChromaDB collections. Prevents destructive changes.
metadata:
  type: project
  triggers:
    - schema
    - migration
    - migrate
    - 改表
    - 迁移
    - 数据库
    - alter table
    - create table
    - drop table
    - add column
    - 改字段
---

# Database Migration Skill

## Rule (Highest Priority)

**NEVER touch the database schema without going through this checklist.**
AI must not casually ALTER TABLE, DROP TABLE, or change column types.
These are the highest-risk operations in the project.

## Pre-flight Assessment

Before any schema change, answer these questions:

### 1. Impact Analysis

| Question | Must Answer |
|----------|-------------|
| Which tables/collections are affected? | Names |
| What existing data will be affected? | Row count estimate |
| Is this backward-compatible? (additive?) | Yes/No |
| Can this be rolled back? | Yes/No + how |
| Which Python modules read/write this schema? | List of files |

### 2. Additive vs Destructive

- **Additive** (ADD COLUMN, CREATE TABLE, new index) — lower risk, but still needs migration script
- **Destructive** (DROP, ALTER column type, RENAME) — HIGH RISK. Must:
  - Create backup first: `python news-monitor/scripts/backup_state.py`
  - Copy `.db` file to `.db.bak.{date}`
  - Write rollback script BEFORE executing forward migration

### 3. Migration Script

Every schema change must have a numbered migration script:

```
news-monitor/storage/migrations/
├── 001_initial_schema.sql
├── 002_add_relevance_score.sql
├── 003_add_training_docs.sql
└── ...
```

Naming: `{NNN}_{description}.sql`

Content: Pure SQL, with both `-- UP` (forward) and `-- DOWN` (rollback) sections:

```sql
-- UP: Add curator relevance columns
ALTER TABLE news ADD COLUMN relevance_score REAL DEFAULT 5.0;
ALTER TABLE news ADD COLUMN relevance_reason TEXT DEFAULT '';

-- DOWN: Remove curator relevance columns
-- ALTER TABLE news DROP COLUMN relevance_score;
-- ALTER TABLE news DROP COLUMN relevance_reason;
```

### 4. Apply Migration

```bash
# 1. Backup
python news-monitor/scripts/backup_state.py
cp news-monitor/data/news.db news-monitor/data/news.db.bak.$(date +%Y%m%d_%H%M%S)

# 2. Apply
sqlite3 news-monitor/data/news.db < news-monitor/storage/migrations/{NNN}_{name}.sql

# 3. Verify
python -m pytest tests/ -k "db or database or storage" -q

# 4. Update models.py if needed
```

## ChromaDB Specific

ChromaDB (vector store) is embedded, not a separate server:
- Schema changes = changing `collection` name or metadata structure
- `sentence-transformers` model change = all embeddings must be regenerated
- Known issue: Windows file locking on tempfile cleanup (6 test errors, expected)

## Current Schema (as of 2026-07-03)

### SQLite: `news-monitor/data/news.db`

**Table: news**
| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | autoincrement |
| title | TEXT | required |
| url | TEXT | dedup key |
| source | TEXT | e.g. Bloomberg, CNBC |
| content_snippet | TEXT | first ~500 chars |
| published_at | TIMESTAMP | |
| captured_at | TIMESTAMP | |
| tickers_found | TEXT | comma-separated |
| macro_tags | TEXT | comma-separated |
| is_breaking | INTEGER | 0/1 |
| priority_score | REAL | |
| entities | TEXT | JSON |
| sentiment | TEXT | enum value |
| sentiment_score | REAL | |
| market_impact | TEXT | |
| llm_analysis | TEXT | |
| event_line_id | INTEGER | FK |
| relevance_score | REAL | 0-10 curator score |
| relevance_reason | TEXT | |
| status | TEXT | enum: pending/fast_pushed/deep_pushed/archived |

**Table: event_lines**
| Column | Type |
|--------|------|
| id | INTEGER PK |
| title | TEXT |
| news_ids | TEXT |
| source_count | INTEGER |
| first_seen | TIMESTAMP |
| last_updated | TIMESTAMP |
| is_active | INTEGER |

**Table: feedback**
| Column | Type |
|--------|------|
| id | INTEGER PK |
| news_id | INTEGER FK |
| reaction | TEXT |
| timestamp | TIMESTAMP |

**Table: preferences**
| Column | Type |
|--------|------|
| key | TEXT PK |
| value | TEXT |
| updated_at | TIMESTAMP |

**Table: training_docs**
| Column | Type |
|--------|------|
| id | INTEGER PK |
| source_type | TEXT | url/text/file |
| content | TEXT | |
| summary | TEXT | AI-generated |
| topic_tags | TEXT | |
| created_at | TIMESTAMP |

### ChromaDB: `news-monitor/data/chroma/`
- Collection: `news_articles`
- Embedding: `sentence-transformers` (all-MiniLM-L6-v2, 384-dim)
- Metadata: `{article_id, title, source, captured_at}`
