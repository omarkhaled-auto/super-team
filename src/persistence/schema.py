"""Persistence layer database schema for cross-run violation tracking."""
from __future__ import annotations

from src.shared.db.connection import ConnectionPool

SCHEMA_VERSION = 1


def init_persistence_db(pool: ConnectionPool) -> None:
    """Initialize the persistence layer database schema.

    Follows the exact pattern from ``src.shared.db.schema``:
    ``CREATE TABLE IF NOT EXISTS`` + explicit indexes.

    Args:
        pool: Connection pool pointing at the persistence database.
    """
    conn = pool.get()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS pipeline_runs (
            run_id TEXT PRIMARY KEY,
            prd_hash TEXT,
            timestamp TEXT NOT NULL DEFAULT (datetime('now')),
            overall_verdict TEXT,
            service_count INTEGER NOT NULL DEFAULT 0,
            total_cost REAL NOT NULL DEFAULT 0.0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS violations_observed (
            violation_id TEXT PRIMARY KEY,
            run_id TEXT REFERENCES pipeline_runs(run_id),
            scan_code TEXT,
            file_path TEXT,
            line INTEGER NOT NULL DEFAULT 0,
            message TEXT,
            severity TEXT,
            service_name TEXT,
            service_tech_stack TEXT,
            was_fixed INTEGER NOT NULL DEFAULT 0,
            fix_cost REAL NOT NULL DEFAULT 0.0
        );
        CREATE INDEX IF NOT EXISTS idx_vo_scan_stack
            ON violations_observed(scan_code, service_tech_stack);
        CREATE INDEX IF NOT EXISTS idx_vo_run
            ON violations_observed(run_id);

        CREATE TABLE IF NOT EXISTS fix_patterns (
            fix_id TEXT PRIMARY KEY,
            violation_id TEXT REFERENCES violations_observed(violation_id),
            code_before TEXT NOT NULL DEFAULT '',
            code_after TEXT NOT NULL DEFAULT '',
            diff TEXT NOT NULL DEFAULT '',
            fix_description TEXT NOT NULL DEFAULT '',
            agent_prompt_excerpt TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_fp_violation
            ON fix_patterns(violation_id);

        CREATE TABLE IF NOT EXISTS scan_code_stats (
            scan_code TEXT NOT NULL,
            tech_stack TEXT NOT NULL,
            occurrence_count INTEGER NOT NULL DEFAULT 0,
            fix_success_rate REAL NOT NULL DEFAULT 0.0,
            avg_fix_cost REAL NOT NULL DEFAULT 0.0,
            promotion_candidate INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (scan_code, tech_stack)
        );
    """)
    conn.commit()

    # Seed schema_version if empty
    row = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()
    if row[0] == 0:
        conn.execute(
            "INSERT INTO schema_version (version) VALUES (?)",
            (SCHEMA_VERSION,),
        )
        conn.commit()
