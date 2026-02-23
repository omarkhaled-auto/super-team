"""Database schema initialization for all services."""
from __future__ import annotations

from src.shared.db.connection import ConnectionPool


def init_architect_db(pool: ConnectionPool) -> None:
    """Initialize the Architect service database schema."""
    conn = pool.get()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS service_maps (
            id TEXT PRIMARY KEY,
            project_name TEXT NOT NULL,
            prd_hash TEXT NOT NULL,
            map_json TEXT NOT NULL,
            build_cycle_id TEXT,
            generated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_smap_project ON service_maps(project_name);
        CREATE INDEX IF NOT EXISTS idx_smap_prd ON service_maps(prd_hash);

        CREATE TABLE IF NOT EXISTS domain_models (
            id TEXT PRIMARY KEY,
            project_name TEXT NOT NULL,
            model_json TEXT NOT NULL,
            generated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_dmodel_project ON domain_models(project_name);

        CREATE TABLE IF NOT EXISTS decomposition_runs (
            id TEXT PRIMARY KEY,
            prd_content_hash TEXT NOT NULL,
            service_map_id TEXT REFERENCES service_maps(id),
            domain_model_id TEXT REFERENCES domain_models(id),
            validation_issues TEXT NOT NULL DEFAULT '[]',
            interview_questions TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending','running','completed','failed','review')),
            started_at TEXT NOT NULL DEFAULT (datetime('now')),
            completed_at TEXT
        );
    """)
    conn.commit()


def init_contracts_db(pool: ConnectionPool) -> None:
    """Initialize the Contract Engine database schema."""
    conn = pool.get()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS build_cycles (
            id TEXT PRIMARY KEY,
            project_name TEXT NOT NULL,
            started_at TEXT NOT NULL DEFAULT (datetime('now')),
            completed_at TEXT,
            status TEXT NOT NULL DEFAULT 'running'
                CHECK(status IN ('running','completed','failed','paused')),
            services_planned INTEGER NOT NULL DEFAULT 0,
            services_completed INTEGER NOT NULL DEFAULT 0,
            total_cost_usd REAL NOT NULL DEFAULT 0.0
        );
        CREATE INDEX IF NOT EXISTS idx_build_cycles_status ON build_cycles(status);

        CREATE TABLE IF NOT EXISTS contracts (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL CHECK(type IN ('openapi','asyncapi','json_schema')),
            version TEXT NOT NULL,
            service_name TEXT NOT NULL,
            spec_json TEXT NOT NULL,
            spec_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK(status IN ('active','deprecated','draft')),
            build_cycle_id TEXT REFERENCES build_cycles(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(service_name, type, version)
        );
        CREATE INDEX IF NOT EXISTS idx_contracts_service ON contracts(service_name);
        CREATE INDEX IF NOT EXISTS idx_contracts_type ON contracts(type);
        CREATE INDEX IF NOT EXISTS idx_contracts_status ON contracts(status);
        CREATE INDEX IF NOT EXISTS idx_contracts_build ON contracts(build_cycle_id);
        CREATE INDEX IF NOT EXISTS idx_contracts_hash ON contracts(spec_hash);

        CREATE TABLE IF NOT EXISTS contract_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contract_id TEXT NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
            version TEXT NOT NULL,
            spec_hash TEXT NOT NULL,
            build_cycle_id TEXT REFERENCES build_cycles(id) ON DELETE SET NULL,
            is_breaking INTEGER NOT NULL DEFAULT 0,
            change_summary TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_versions_contract ON contract_versions(contract_id);
        CREATE INDEX IF NOT EXISTS idx_versions_build ON contract_versions(build_cycle_id);

        CREATE TABLE IF NOT EXISTS breaking_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contract_version_id INTEGER NOT NULL
                REFERENCES contract_versions(id) ON DELETE CASCADE,
            change_type TEXT NOT NULL,
            json_path TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            severity TEXT NOT NULL DEFAULT 'error'
                CHECK(severity IN ('error','warning','info')),
            affected_consumers TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_breaking_version ON breaking_changes(contract_version_id);

        CREATE TABLE IF NOT EXISTS implementations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contract_id TEXT NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
            service_name TEXT NOT NULL,
            evidence_path TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('verified','pending','failed')),
            verified_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(contract_id, service_name)
        );
        CREATE INDEX IF NOT EXISTS idx_impl_contract ON implementations(contract_id);
        CREATE INDEX IF NOT EXISTS idx_impl_service ON implementations(service_name);
        CREATE INDEX IF NOT EXISTS idx_impl_status ON implementations(status);

        CREATE TABLE IF NOT EXISTS test_suites (
            contract_id TEXT NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
            framework TEXT NOT NULL DEFAULT 'pytest'
                CHECK(framework IN ('pytest','jest')),
            test_code TEXT NOT NULL,
            test_count INTEGER NOT NULL DEFAULT 0,
            spec_hash TEXT NOT NULL DEFAULT '',
            include_negative INTEGER NOT NULL DEFAULT 0,
            generated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(contract_id, framework, include_negative)
        );
        CREATE INDEX IF NOT EXISTS idx_tests_contract ON test_suites(contract_id);

        CREATE TABLE IF NOT EXISTS shared_schemas (
            name TEXT PRIMARY KEY,
            schema_json TEXT NOT NULL,
            owning_service TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS schema_consumers (
            schema_name TEXT NOT NULL
                REFERENCES shared_schemas(name) ON DELETE CASCADE,
            service_name TEXT NOT NULL,
            PRIMARY KEY (schema_name, service_name)
        );
    """)
    conn.commit()


def init_symbols_db(pool: ConnectionPool) -> None:
    """Initialize the Codebase Intelligence database schema."""
    conn = pool.get()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS indexed_files (
            file_path TEXT PRIMARY KEY,
            language TEXT NOT NULL
                CHECK(language IN ('python','typescript','csharp','go','unknown')),
            service_name TEXT,
            file_hash TEXT NOT NULL,
            loc INTEGER NOT NULL DEFAULT 0,
            indexed_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_files_service ON indexed_files(service_name);
        CREATE INDEX IF NOT EXISTS idx_files_language ON indexed_files(language);
        CREATE INDEX IF NOT EXISTS idx_files_hash ON indexed_files(file_hash);

        CREATE TABLE IF NOT EXISTS symbols (
            id TEXT PRIMARY KEY,
            file_path TEXT NOT NULL
                REFERENCES indexed_files(file_path) ON DELETE CASCADE,
            symbol_name TEXT NOT NULL,
            kind TEXT NOT NULL
                CHECK(kind IN ('class','function','interface','type','enum','variable','method')),
            language TEXT NOT NULL,
            service_name TEXT,
            line_start INTEGER NOT NULL,
            line_end INTEGER NOT NULL,
            signature TEXT,
            docstring TEXT,
            is_exported INTEGER NOT NULL DEFAULT 1,
            parent_symbol TEXT,
            chroma_id TEXT,
            indexed_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_path);
        CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(symbol_name);
        CREATE INDEX IF NOT EXISTS idx_symbols_kind ON symbols(kind);
        CREATE INDEX IF NOT EXISTS idx_symbols_service ON symbols(service_name);
        CREATE INDEX IF NOT EXISTS idx_symbols_language ON symbols(language);
        CREATE INDEX IF NOT EXISTS idx_symbols_parent ON symbols(parent_symbol);

        CREATE TABLE IF NOT EXISTS dependency_edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_symbol_id TEXT NOT NULL,
            target_symbol_id TEXT NOT NULL,
            relation TEXT NOT NULL
                CHECK(relation IN ('imports','calls','inherits','implements','uses')),
            source_file TEXT NOT NULL,
            target_file TEXT NOT NULL,
            line INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(source_symbol_id, target_symbol_id, relation)
        );
        CREATE INDEX IF NOT EXISTS idx_deps_source ON dependency_edges(source_symbol_id);
        CREATE INDEX IF NOT EXISTS idx_deps_target ON dependency_edges(target_symbol_id);
        CREATE INDEX IF NOT EXISTS idx_deps_source_file ON dependency_edges(source_file);
        CREATE INDEX IF NOT EXISTS idx_deps_target_file ON dependency_edges(target_file);
        CREATE INDEX IF NOT EXISTS idx_deps_relation ON dependency_edges(relation);

        CREATE TABLE IF NOT EXISTS import_references (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_file TEXT NOT NULL
                REFERENCES indexed_files(file_path) ON DELETE CASCADE,
            target_file TEXT NOT NULL,
            imported_names TEXT NOT NULL DEFAULT '[]',
            line INTEGER NOT NULL,
            is_relative INTEGER NOT NULL DEFAULT 0,
            UNIQUE(source_file, target_file, line)
        );
        CREATE INDEX IF NOT EXISTS idx_imports_source ON import_references(source_file);
        CREATE INDEX IF NOT EXISTS idx_imports_target ON import_references(target_file);

        CREATE TABLE IF NOT EXISTS graph_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            graph_json TEXT NOT NULL,
            node_count INTEGER NOT NULL DEFAULT 0,
            edge_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    conn.commit()


def init_graph_rag_db(pool: ConnectionPool) -> None:
    """Initialize the Graph RAG database schema."""
    conn = pool.get()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS graph_rag_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_data TEXT NOT NULL,
            node_count INTEGER NOT NULL,
            edge_count INTEGER NOT NULL,
            community_count INTEGER NOT NULL,
            services_indexed TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
    """)
    conn.commit()
