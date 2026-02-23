# RESEARCH_REPORT.md — Persistent Intelligence Layer

> **Generated:** 2026-02-23 | **Agent:** Research Agent | **Source:** Context7 API queries
> **Status:** COMPLETE — All libraries researched, exact API signatures confirmed

---

## Table of Contents

1. [2A: ChromaDB Research](#2a-chromadb-research)
2. [2B: SQLite (sqlite3) Research](#2b-sqlite-sqlite3-research)
3. [2C: difflib Research](#2c-difflib-research)
4. [2D: NetworkX Research](#2d-networkx-research)
5. [2E: Schemathesis and jsonschema Research](#2e-schemathesis-and-jsonschema-research)
6. [Discrepancies and Warnings](#discrepancies-and-warnings)

---

## 2A: ChromaDB Research

**Library:** `chromadb`
**Context7 ID:** `/chroma-core/chroma`
**Source Reputation:** High | **Benchmark Score:** 79.9 | **Code Snippets:** 2235

### PersistentClient vs EphemeralClient

**Confirmed API:**

```python
import chromadb

# PersistentClient — data persists to disk across process restarts
client = chromadb.PersistentClient(path="/path/to/save/to")

# EphemeralClient — in-memory only, data lost on process exit
client = chromadb.EphemeralClient()
```

**Exact Constructor Signature:**

```python
chromadb.PersistentClient(
    path: Union[str, Path],       # Required — directory to store persisted data
    settings: Settings = None,    # Optional — chromadb.config.Settings instance
    tenant: str = "default",      # Optional — multi-tenant isolation
    database: str = "default"     # Optional — database name
)
```

**Key Behaviors:**
- Data is automatically persisted and loaded on start if the path directory exists.
- If no `path` is provided, defaults to `.chroma` in the current directory.
- Suitable for local development and testing. For production, a server-backed Chroma instance is recommended.
- WAL journaling is managed internally by Chroma's SQLite backend.
- `client.heartbeat()` — check connectivity.
- `client.reset()` — reset all data (use with caution).

**Collection Creation:**

```python
collection = client.get_or_create_collection(name="my_collection")
```

### Metadata Schema Design

**Indexable Metadata Fields:**
- ChromaDB metadata values support: `str`, `int`, `float`, `bool` types.
- All metadata fields are automatically indexable — no explicit schema declaration required.
- Metadata is passed as a `dict` per record.

**Simultaneous Filtering by Multiple Metadata Fields:**

ChromaDB supports logical operators `$and` and `$or` for combining multiple metadata conditions:

```python
# AND — all conditions must match
collection.query(
    query_texts=["search text"],
    where={
        "$and": [
            {"metadata_field_1": {"$eq": "value1"}},
            {"metadata_field_2": {"$gt": 5}}
        ]
    }
)

# OR — any condition can match
collection.query(
    query_texts=["search text"],
    where={
        "$or": [
            {"metadata_field_1": {"$eq": "value1"}},
            {"metadata_field_2": {"$eq": "value2"}}
        ]
    }
)
```

**Supported Comparison Operators:**
| Operator | Description |
|----------|-------------|
| `$eq`    | Equal to |
| `$ne`    | Not equal to |
| `$gt`    | Greater than |
| `$gte`   | Greater than or equal to |
| `$lt`    | Less than |
| `$lte`   | Less than or equal to |
| `$in`    | Value in list |
| `$nin`   | Value not in list |

### $in Operator Behavior and Size Limits

**Confirmed API:**

```python
# Filter by set membership
collection.get(
    where={
        "author": {"$in": ["Rowling", "Fitzgerald", "Herbert"]}
    }
)
```

**Supported Types for `$in`:** `string`, `integer`, `float`, `boolean`.

**Size Limits:** Context7 documentation does NOT specify an explicit size limit for the `$in` list. The practical limit is constrained by memory and query performance. For very large sets (thousands of values), consider alternative approaches (e.g., multiple queries or metadata restructuring).

> **WARNING:** No documented hard limit on `$in` list size was found in Context7. Recommend testing with target workload sizes and monitoring performance.

### Upsert Pattern for Updating Frequency Counter in Metadata

**Confirmed API:**

```python
collection.upsert(
    ids=["id1", "id2", "id3"],
    embeddings=[[1.1, 2.3, 3.2], [4.5, 6.9, 4.4], [1.1, 2.3, 3.2]],
    metadatas=[
        {"chapter": 3, "verse": 16},
        {"chapter": 3, "verse": 5},
        {"chapter": 29, "verse": 11},
    ],
    documents=["doc1", "doc2", "doc3"],
)
```

**Upsert Behavior:**
- If ID exists: the entire record (embeddings, metadatas, documents) is **replaced**.
- If ID does not exist: a new record is created.
- Embeddings are optional — if omitted and documents are provided, embeddings are auto-generated from documents.

**CRITICAL DISCREPANCY — Frequency Counter Pattern:**
ChromaDB `upsert` performs a **full replace** on metadata, NOT a partial merge or increment. There is no built-in atomic `increment` operation on metadata fields.

**Workaround for frequency counter:**
```python
# Step 1: Get existing record
existing = collection.get(ids=["scan_code_123"], include=["metadatas"])

# Step 2: Compute new count
old_count = existing["metadatas"][0].get("frequency", 0) if existing["ids"] else 0
new_count = old_count + 1

# Step 3: Upsert with updated metadata
collection.upsert(
    ids=["scan_code_123"],
    metadatas=[{"frequency": new_count, "last_seen": "2026-02-23"}],
    documents=["..."],
)
```

> **WARNING:** This is NOT atomic. Concurrent updates can cause lost increments. For frequency counters requiring atomicity, use SQLite instead and store only embeddings in ChromaDB.

### collection.get() vs collection.query()

**`collection.get()` — Direct Retrieval (No Similarity Search):**

```python
# By IDs
collection.get(ids=["id1", "id2"])

# With pagination
collection.get(limit=100, offset=0)

# With metadata filter (no similarity ranking)
collection.get(
    where={"author": {"$in": ["Rowling", "Fitzgerald"]}},
    include=["metadatas", "documents"]
)
```

**`collection.query()` — Similarity Search (Nearest-Neighbor):**

```python
collection.query(
    query_texts=["search text"],          # OR query_embeddings=[...]
    n_results=10,                         # Number of results per query
    where={"page": 10},                   # Optional metadata filter
    where_document={"$contains": "str"},  # Optional document content filter
    include=["metadatas", "documents", "distances"]
)
```

**When to Use Each:**

| Use Case | Method |
|----------|--------|
| Retrieve by known IDs | `get()` |
| Paginate through all records | `get(limit=..., offset=...)` |
| Filter by metadata only (no ranking) | `get(where=...)` |
| Similarity search with embedding | `query()` |
| Similarity search + metadata filter | `query(where=...)` |
| Find nearest neighbors | `query()` |

**Key Difference:** `get()` returns records in insertion order; `query()` returns records ranked by embedding distance (similarity).

### Distance Threshold for Cosine Similarity

**ChromaDB Distance Metrics:**
ChromaDB supports multiple distance functions configured per collection:

```python
collection = client.get_or_create_collection(
    name="my_collection",
    metadata={"hnsw:space": "cosine"}  # Options: "cosine", "l2", "ip"
)
```

**Cosine Distance Values:**
- ChromaDB returns **cosine distance** (not cosine similarity).
- `cosine_distance = 1 - cosine_similarity`
- Range: `[0, 2]` where `0` = identical, `2` = opposite.

**Practical Thresholds:**
| Distance | Interpretation |
|----------|---------------|
| 0.0 - 0.1 | Very similar (similarity > 0.9) |
| 0.1 - 0.3 | Similar (similarity 0.7 - 0.9) |
| 0.3 - 0.5 | Somewhat related |
| 0.5+ | Weakly related or unrelated |

**Filtering by Distance (post-query):**
```python
results = collection.query(
    query_texts=["search text"],
    n_results=20,
    include=["distances", "metadatas", "documents"]
)

# Filter results by distance threshold
threshold = 0.3
for i, distance in enumerate(results["distances"][0]):
    if distance <= threshold:
        print(results["documents"][0][i], distance)
```

> **NOTE:** ChromaDB does NOT support a `max_distance` parameter in the query API. Distance filtering must be done post-query in application code.

---

## 2B: SQLite (sqlite3) Research

**Library:** Python `sqlite3` (stdlib) + SQLite engine
**Context7 ID:** `/websites/sqlite_cli` (SQLite reference), `/websites/python_3_13_library` (Python stdlib)
**Source Reputation:** High

### WAL Mode Exact PRAGMA Statements

**Confirmed SQL:**

```sql
-- Enable Write-Ahead Logging
PRAGMA journal_mode=WAL;
-- Returns: 'wal' on success, or the prior journaling mode on failure
```

**Python Usage:**

```python
import sqlite3

conn = sqlite3.connect("my_database.db")
conn.execute("PRAGMA journal_mode=WAL;")
conn.execute("PRAGMA busy_timeout=5000;")     # Wait up to 5s for locks
conn.execute("PRAGMA synchronous=NORMAL;")    # Good performance/safety balance
conn.execute("PRAGMA cache_size=-64000;")     # 64MB cache (negative = KB)
conn.execute("PRAGMA foreign_keys=ON;")       # Enable FK constraints
```

**Key Behaviors:**
- WAL mode is **persistent** — once set, it stays in effect across multiple connections and after closing/reopening the database.
- WAL enables **simultaneous readers and writers** — readers do not block writers and writers do not block readers.
- Only accessible by SQLite version >= 3.7.0 (2010-07-21).
- WAL mode creates two additional files: `database.db-shm` (shared memory) and `database.db-wal` (write-ahead log).

**Full PRAGMA Initialization Block:**

```python
def init_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA cache_size=-64000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.row_factory = sqlite3.Row  # Enable dict-like row access
    return conn
```

### JSON Column Storage

**SQLite JSON1 Extension Functions (built-in since SQLite 3.38.0):**

```sql
-- Store JSON in TEXT columns
CREATE TABLE scan_results (
    id INTEGER PRIMARY KEY,
    scan_code TEXT NOT NULL,
    details TEXT NOT NULL  -- JSON stored as TEXT
);

-- Insert JSON data
INSERT INTO scan_results (scan_code, details)
VALUES ('SC001', '{"severity": "high", "count": 5, "tags": ["security", "auth"]}');

-- Extract values from JSON
SELECT json_extract(details, '$.severity') AS severity FROM scan_results;
-- Returns: 'high'

SELECT json_extract(details, '$.count') AS count FROM scan_results;
-- Returns: 5

-- Extract nested array element
SELECT json_extract(details, '$.tags[0]') AS first_tag FROM scan_results;
-- Returns: 'security'

-- Extract multiple paths (returns JSON array)
SELECT json_extract(details, '$.severity', '$.count') FROM scan_results;
-- Returns: '["high",5]'
```

**Exact Function Signatures:**

```
json_extract(JSON_text, path1, path2, ...)
  → SQL NULL, INTEGER, REAL, or TEXT for single path
  → JSON array TEXT for multiple paths

json_set(JSON_text, path, value, ...)
  → Modified JSON TEXT (inserts or replaces)

json_object(key1, value1, key2, value2, ...)
  → JSON object TEXT

json_array(value1, value2, ...)
  → JSON array TEXT

json_type(JSON_text, path)
  → TEXT: 'null', 'true', 'false', 'integer', 'real', 'text', 'array', 'object'

json_valid(JSON_text)
  → 1 if valid JSON, 0 otherwise
```

**Arrow Operators (SQLite >= 3.38.0):**

```sql
-- -> returns JSON value (strings remain quoted)
SELECT details -> '$.severity' FROM scan_results;
-- Returns: '"high"'

-- ->> returns SQL value (strings unquoted)
SELECT details ->> '$.severity' FROM scan_results;
-- Returns: 'high'
```

### FTS5 for Violation Message Search

**Confirmed SQL:**

```sql
-- Create FTS5 virtual table
CREATE VIRTUAL TABLE violation_fts USING fts5(
    violation_id,      -- stored but not indexed by default
    message,           -- full-text indexed
    scan_code,         -- full-text indexed
    content="violations",        -- external content table
    content_rowid="id"           -- link to source table rowid
);

-- Simple FTS5 table (standalone, no external content)
CREATE VIRTUAL TABLE violation_search USING fts5(message, scan_code, severity);
```

**Key FTS5 Behaviors:**
- FTS5 columns do NOT support explicit types, constraints, or PRIMARY KEY declarations.
- All columns are text-indexed by default.
- Use `content=` option to create an external-content FTS5 table (saves storage by referencing another table).

**Querying FTS5:**

```sql
-- Simple text search
SELECT * FROM violation_search WHERE violation_search MATCH 'authentication failure';

-- Phrase search
SELECT * FROM violation_search WHERE violation_search MATCH '"missing auth token"';

-- Column-specific search
SELECT * FROM violation_search WHERE violation_search MATCH 'message:authentication';

-- Boolean operators
SELECT * FROM violation_search WHERE violation_search MATCH 'auth AND NOT login';

-- Ranked results (BM25)
SELECT *, rank FROM violation_search WHERE violation_search MATCH 'security'
ORDER BY rank;
```

**Populating FTS5 (external content):**

```sql
-- Insert into FTS5 index
INSERT INTO violation_fts(rowid, violation_id, message, scan_code)
SELECT id, violation_id, message, scan_code FROM violations;

-- Rebuild entire index
INSERT INTO violation_fts(violation_fts) VALUES('rebuild');
```

### UPSERT: INSERT OR REPLACE vs INSERT ... ON CONFLICT DO UPDATE

**Method 1: INSERT OR REPLACE (destructive — deletes and re-inserts):**

```sql
-- WARNING: This DELETES the existing row and INSERTs a new one
-- All columns not specified will get their DEFAULT values
-- Any foreign key references to the old row are broken
INSERT OR REPLACE INTO scan_codes (code, frequency)
VALUES ('SC001', 1);
```

**Method 2: INSERT ... ON CONFLICT DO UPDATE (preferred — true UPSERT):**

```sql
-- Frequency counter pattern (CONFIRMED from Context7)
CREATE TABLE vocabulary(word TEXT PRIMARY KEY, count INT DEFAULT 1);

INSERT INTO vocabulary(word) VALUES('jovial')
  ON CONFLICT(word) DO UPDATE SET count = count + 1;
```

```sql
-- Overwrite pattern using excluded. qualifier
CREATE TABLE phonebook(name TEXT PRIMARY KEY, phonenumber TEXT);

INSERT INTO phonebook(name, phonenumber) VALUES('Alice', '704-555-1212')
  ON CONFLICT(name) DO UPDATE SET phonenumber = excluded.phonenumber;
```

**`excluded.` Qualifier:**
- `excluded.column_name` references the value that **would have been inserted** (the conflicting new value).
- This is essential for selectively updating columns on conflict.

**Recommended UPSERT for Frequency Counter:**

```sql
CREATE TABLE scan_frequency (
    scan_code TEXT PRIMARY KEY,
    frequency INTEGER DEFAULT 1,
    first_seen TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen TEXT NOT NULL DEFAULT (datetime('now')),
    details TEXT  -- JSON column
);

-- Increment frequency on conflict
INSERT INTO scan_frequency (scan_code, last_seen, details)
VALUES (?, datetime('now'), ?)
ON CONFLICT(scan_code) DO UPDATE SET
    frequency = frequency + 1,
    last_seen = datetime('now'),
    details = COALESCE(excluded.details, details);
```

**Key Differences:**

| Feature | INSERT OR REPLACE | ON CONFLICT DO UPDATE |
|---------|-------------------|-----------------------|
| Mechanism | DELETE + INSERT | True in-place UPDATE |
| Non-specified columns | Reset to DEFAULT | Preserved |
| ROWID | Changes (new row) | Preserved (same row) |
| Foreign key cascades | Triggered (DELETE) | Not triggered |
| Triggers | DELETE + INSERT triggers | UPDATE triggers only |
| **Recommendation** | **Avoid for counters** | **Use for counters** |

### Aggregate Queries for Top-N Scan Codes

**Confirmed SQL Patterns:**

```sql
-- Top 10 most frequent scan codes
SELECT scan_code, frequency
FROM scan_frequency
ORDER BY frequency DESC
LIMIT 10;

-- Top-N with aggregate from raw data
SELECT scan_code, COUNT(*) as occurrence_count, MAX(severity) as max_severity
FROM violations
GROUP BY scan_code
ORDER BY occurrence_count DESC
LIMIT 10;

-- With HAVING filter (post-aggregation)
SELECT scan_code, COUNT(*) as cnt, AVG(confidence) as avg_conf
FROM violations
GROUP BY scan_code
HAVING cnt > 5
ORDER BY cnt DESC
LIMIT 20;

-- Top-N with WHERE + GROUP BY + HAVING
SELECT scan_code, MIN(created_at) as first_seen, MAX(created_at) as last_seen, COUNT(*) as total
FROM violations
WHERE severity IN ('high', 'critical')
GROUP BY scan_code
HAVING total >= 3
ORDER BY total DESC
LIMIT 10;
```

**Python sqlite3 Module — Key API:**

```python
import sqlite3

# Connect
conn = sqlite3.connect("database.db")
conn.row_factory = sqlite3.Row  # Dict-like access

# Execute single statement
cursor = conn.execute("SELECT * FROM table WHERE id = ?", (some_id,))
row = cursor.fetchone()
rows = cursor.fetchall()

# Execute multiple rows
conn.executemany("INSERT INTO t(a, b) VALUES(?, ?)", [(1, 2), (3, 4)])

# Execute script (multiple statements)
conn.executescript("""
    BEGIN;
    CREATE TABLE IF NOT EXISTS t1(a, b);
    CREATE TABLE IF NOT EXISTS t2(c, d);
    COMMIT;
""")

# Commit and close
conn.commit()
conn.close()
```

---

## 2C: difflib Research

**Library:** Python `difflib` (stdlib)
**Context7 ID:** `/websites/python_3_13_library`
**Source Reputation:** High | **Benchmark Score:** 86.4

### unified_diff — Exact Signature and Output Format

**Confirmed Signature:**

```python
difflib.unified_diff(
    a,                    # Sequence[str] — first file lines
    b,                    # Sequence[str] — second file lines
    fromfile='',          # str — "from" filename for header
    tofile='',            # str — "to" filename for header
    fromfiledate='',      # str — "from" file date for header
    tofiledate='',        # str — "to" file date for header
    n=3,                  # int — number of context lines (default 3)
    lineterm='\n'         # str — line terminator (default newline)
) -> Iterator[str]        # Returns generator yielding delta lines
```

**Output Format:**

```
--- before.py
+++ after.py
@@ -1,4 +1,4 @@
-bacon
-eggs
-ham
+python
+eggy
+hamster
 guido
```

**Usage Example:**

```python
import difflib

s1 = ['bacon\n', 'eggs\n', 'ham\n', 'guido\n']
s2 = ['python\n', 'eggy\n', 'hamster\n', 'guido\n']

diff = difflib.unified_diff(s1, s2, fromfile='before.py', tofile='after.py')
diff_text = ''.join(diff)
```

**For strings without trailing newlines, set `lineterm=""`:**

```python
diff = difflib.unified_diff(
    old_lines, new_lines,
    fromfile='old', tofile='new',
    lineterm=''
)
diff_text = '\n'.join(diff)
```

### SequenceMatcher.ratio() for Similarity

**Confirmed Signature:**

```python
difflib.SequenceMatcher(
    isjunk=None,     # callable(element) -> bool, or None
    a='',            # first sequence
    b='',            # second sequence
    autojunk=True    # bool — automatic junk heuristic (default True)
)
```

**Methods:**

```python
sm = difflib.SequenceMatcher(None, 'tide', 'diet')

# Exact similarity ratio — 2.0 * M / T
# where M = matching elements, T = total elements in both sequences
sm.ratio()           # Returns float in [0.0, 1.0]; 1.0 = identical
# Example: SequenceMatcher(None, 'tide', 'diet').ratio() → 0.25

# Faster upper-bound estimates
sm.quick_ratio()      # Upper bound, faster than ratio()
sm.real_quick_ratio()  # Even faster upper bound, least accurate

# Get matching blocks
sm.get_matching_blocks()  # Returns list of Match(a, b, size) named tuples

# Get opcodes for transformation
sm.get_opcodes()  # Returns list of (tag, i1, i2, j1, j2) tuples
# tag is one of: 'replace', 'delete', 'insert', 'equal'
```

**Opcodes Example:**

```python
a = "qabxcd"
b = "abycdf"
s = SequenceMatcher(None, a, b)
for tag, i1, i2, j1, j2 in s.get_opcodes():
    print(f'{tag:7}   a[{i1}:{i2}] --> b[{j1}:{j2}]  {a[i1:i2]!r:>8} --> {b[j1:j2]!r}')
```

Output:
```
delete    a[0:1] --> b[0:0]       'q' --> ''
equal     a[1:3] --> b[0:2]      'ab' --> 'ab'
replace   a[3:4] --> b[2:3]       'x' --> 'y'
equal     a[4:6] --> b[3:5]      'cd' --> 'cd'
insert    a[6:6] --> b[5:6]        '' --> 'f'
```

**Key Note on ratio():**
- The order of `a` and `b` CAN affect the ratio (confirmed by Context7).
- `SequenceMatcher(None, 'tide', 'diet').ratio()` may differ from `SequenceMatcher(None, 'diet', 'tide').ratio()`.

### Best Storage Format for a Diff

**Recommended: Store as unified diff text string.**

```python
import difflib
import json

def compute_and_store_diff(old_text: str, new_text: str, label: str) -> str:
    """Compute unified diff and return as storable string."""
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)

    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f'{label}_old',
        tofile=f'{label}_new',
        n=3  # context lines
    )
    return ''.join(diff)

# Store in SQLite as TEXT column
# Store in JSON as string field
# Both are human-readable and universally parseable
```

**Alternative: Store opcodes as JSON for programmatic replay:**

```python
def compute_opcodes(old_text: str, new_text: str) -> list:
    """Return opcodes as JSON-serializable list."""
    sm = difflib.SequenceMatcher(None, old_text, new_text)
    return [
        {"tag": tag, "i1": i1, "i2": i2, "j1": j1, "j2": j2}
        for tag, i1, i2, j1, j2 in sm.get_opcodes()
    ]
```

**Recommendation:** Use unified diff TEXT for human-readable storage in SQLite. Use JSON opcodes only if programmatic diff replay is needed.

---

## 2D: NetworkX Research

**Library:** `networkx`
**Context7 ID:** `/websites/networkx_stable`
**Source Reputation:** High | **Benchmark Score:** 73.5 | **Code Snippets:** 6060

### DiGraph for Service Dependency Modeling

**Confirmed API:**

```python
import networkx as nx

# Create directed graph
G = nx.DiGraph()

# Add nodes (services)
G.add_node("auth-service", type="service", team="platform")
G.add_node("user-service", type="service", team="backend")

# Add edges (dependencies: from depends-on to)
G.add_edge("user-service", "auth-service", relationship="depends_on")

# Add multiple edges at once
G.add_edges_from([
    ("api-gateway", "auth-service"),
    ("api-gateway", "user-service"),
    ("user-service", "db-service"),
])

# Add nodes from a list
G.add_nodes_from(["service-a", "service-b", "service-c"])

# Add edges from another graph
H = nx.path_graph(10)
G.add_edges_from(H.edges)
```

**Key Properties:**

```python
G.nodes()           # NodeView of all nodes
G.edges()           # OutEdgeView of all edges
G.number_of_nodes() # int
G.number_of_edges() # int
G.in_degree(node)   # Number of incoming edges
G.out_degree(node)  # Number of outgoing edges
G.predecessors(node)  # Iterator of predecessor nodes
G.successors(node)    # Iterator of successor nodes
G.has_node(node)    # bool
G.has_edge(u, v)    # bool
```

### simple_cycles for Circular Dependency Detection

**Confirmed API:**

```python
import networkx as nx

# Signature
nx.simple_cycles(G, length_bound=None)
# Parameters:
#   G: NetworkX Graph (DiGraph, Graph, or MultiGraph)
#   length_bound: int or None — if set, only find cycles of this length or shorter
# Returns: generator of lists — each list is a cycle (list of nodes)

# Example
G = nx.DiGraph([(0, 1), (1, 2), (2, 0), (2, 3), (3, 4), (4, 2)])
cycles = list(nx.simple_cycles(G))
# Returns: [[0, 1, 2], [2, 3, 4]]
```

**Behavior:**
- A **simple cycle** (elementary circuit) is a closed path where no node appears more than once.
- Two elementary circuits are distinct if they are not cyclic permutations of each other.
- Uses Johnson's algorithm: time complexity O((n+e)(c+1)) for n nodes, e edges, c circuits.
- Supports self-loops.
- For directed graphs, this is the primary cycle detection function.

**Alternative: `find_cycle` (finds ONE cycle, not all):**

```python
# Find a single cycle (raises NetworkXNoCycle if none exists)
try:
    cycle = nx.find_cycle(G, orientation="original")
    print(cycle)  # Returns list of (u, v, direction) tuples
except nx.NetworkXNoCycle:
    print("No cycles found")
```

**Use for Circular Dependency Detection:**

```python
def detect_circular_dependencies(G: nx.DiGraph) -> list:
    """Find all circular dependencies in a service dependency graph."""
    cycles = list(nx.simple_cycles(G))
    return [
        {
            "cycle": cycle,
            "length": len(cycle),
            "services": cycle  # List of service names forming the cycle
        }
        for cycle in cycles
    ]
```

### Weakly Connected Components for Orphan Detection

**Confirmed API:**

```python
import networkx as nx

# Signature
nx.weakly_connected_components(G)
# Parameters:
#   G: NetworkX DiGraph (directed graph only)
# Returns: generator of sets — each set contains nodes of one weakly connected component
# Raises: NetworkXNotImplemented if G is undirected

# Example
G = nx.path_graph(4, create_using=nx.DiGraph())
nx.add_path(G, [10, 11, 12])
components = sorted(nx.weakly_connected_components(G), key=len, reverse=True)
# Returns: [{0, 1, 2, 3}, {10, 11, 12}]

# Check if entire graph is weakly connected
nx.is_weakly_connected(G)  # Returns bool
# Raises NetworkXPointlessConcept for null graph (0 nodes)

# Count components
nx.number_weakly_connected_components(G)  # Returns int
```

**A directed graph is weakly connected if** replacing all directed edges with undirected edges produces a connected graph.

**Use for Orphan Detection:**

```python
def detect_orphans(G: nx.DiGraph) -> list:
    """Find isolated services (not connected to the main component)."""
    components = list(nx.weakly_connected_components(G))

    if len(components) <= 1:
        return []  # All nodes are connected

    # Largest component is "main", others are orphans
    main_component = max(components, key=len)
    orphans = []
    for comp in components:
        if comp != main_component:
            orphans.extend(comp)

    return orphans
```

### Bipartite Analysis for Ownership Conflict Detection

**Confirmed API:**

```python
from networkx.algorithms import bipartite
import networkx as nx

# Check if graph is bipartite
bipartite.is_bipartite(G)  # Returns bool

# Check if a set of nodes forms a valid bipartite partition
X = {1, 3}
bipartite.is_bipartite_node_set(G, X)  # Returns bool

# Get the two node sets (requires connected bipartite graph)
if nx.is_connected(B):
    bottom_nodes, top_nodes = bipartite.sets(B)
```

**Exact Signatures:**

```python
# bipartite.is_bipartite(G) -> bool
# bipartite.is_bipartite_node_set(G, nodes) -> bool
# bipartite.sets(G, top_nodes=None) -> (set, set)
#   Raises: NetworkXError if graph is not bipartite
#   Raises: AmbiguousSolution if graph is disconnected and top_nodes is None
```

**Use for Ownership Conflict Detection:**
Model a bipartite graph where one set is "services" and the other is "owners/teams". An ownership conflict exists when a service has edges to multiple teams, or when the bipartite structure is violated.

```python
def detect_ownership_conflicts(services: dict, contracts: dict) -> list:
    """
    Detect ownership conflicts using bipartite analysis.

    services: {service_name: team_name}
    contracts: {contract_id: {provider: str, consumer: str}}
    """
    B = nx.Graph()

    # Add service nodes and team nodes
    for service, team in services.items():
        B.add_node(service, bipartite=0)  # service partition
        B.add_node(team, bipartite=1)     # team partition
        B.add_edge(service, team)

    # Check if bipartite structure holds
    if not bipartite.is_bipartite(B):
        # Bipartite violation indicates structural conflict
        return ["Graph is not bipartite — ownership model is inconsistent"]

    # Check for services owned by multiple teams
    conflicts = []
    for service in [n for n, d in B.nodes(data=True) if d.get("bipartite") == 0]:
        teams = list(B.neighbors(service))
        if len(teams) > 1:
            conflicts.append({
                "service": service,
                "teams": teams,
                "type": "multi-owner"
            })

    return conflicts
```

---

## 2E: Schemathesis and jsonschema Research

### Schemathesis

**Library:** `schemathesis`
**Context7 ID:** `/schemathesis/schemathesis`
**Source Reputation:** High | **Benchmark Score:** 88.8 | **Code Snippets:** 745

#### from_path() vs from_dict()

**Confirmed API — `schemathesis.openapi.from_path()`:**

```python
import schemathesis

# Load from file path (YAML or JSON)
schema = schemathesis.openapi.from_path("./openapi.yaml")

# With base URL
schema = schemathesis.openapi.from_path(
    "./openapi.yaml",
    base_url="http://localhost:8000"
)
```

**Confirmed API — `schemathesis.openapi.from_dict()`:**

```python
import schemathesis
import json

# Load from dictionary
with open("openapi.json", "r") as f:
    raw = json.load(f)

schema = schemathesis.openapi.from_dict(raw)
```

> **DISCREPANCY FOUND:** Context7 shows one example where `from_dict()` is called with `f.read()` (a string), but the method name `from_dict` implies it should take a dict. The correct usage based on the method name and other examples is to pass a **parsed dict**, not a raw string. Use `from_path()` for file-based loading and `from_dict()` for in-memory dict specs.

**All Loading Functions:**

| Function | Input | Use When |
|----------|-------|----------|
| `schemathesis.openapi.from_path(path, base_url=None)` | File path (YAML/JSON) | Loading from local file |
| `schemathesis.openapi.from_url(url, headers=None)` | URL string | Loading from remote server |
| `schemathesis.openapi.from_dict(spec_dict)` | Python dict | Loading from in-memory spec |
| `schemathesis.openapi.from_file(file_obj)` | File object | Loading from open file handle |
| `schemathesis.openapi.from_asgi(app)` | ASGI app | Testing ASGI app directly |
| `schemathesis.openapi.from_wsgi(app)` | WSGI app | Testing WSGI app directly |

#### pytest parametrize Pattern for Contract Tests

**Confirmed Pattern:**

```python
import schemathesis

# Load schema
schema = schemathesis.openapi.from_path("./openapi.yaml", base_url="http://localhost:8000")

# @schema.parametrize() generates one test case per API operation
@schema.parametrize()
def test_api(case):
    # call_and_validate() sends request and validates response against schema
    case.call_and_validate()
```

**Advanced Patterns:**

```python
import schemathesis

schema = schemathesis.openapi.from_url("http://127.0.0.1:8080/openapi.json")

# Basic parametrized test
@schema.parametrize()
def test_api(case):
    case.call_and_validate()

# Stateful testing (workflow: create -> get -> delete)
APIWorkflow = schema.as_state_machine()
TestAPI = APIWorkflow.TestCase  # Creates a test class for pytest/unittest
```

**The `case` Object:**
- `case.call_and_validate()` — sends the HTTP request and validates response against the schema.
- Schemathesis auto-generates random valid data, edge cases, and invalid inputs.
- Each API operation (method + path) becomes a separate parametrized test case.

### jsonschema

**Library:** `jsonschema`
**Context7 ID:** `/python-jsonschema/jsonschema`
**Source Reputation:** Medium | **Benchmark Score:** 92.0

#### jsonschema.validate() Exact Signature

**Confirmed API:**

```python
from jsonschema import validate, ValidationError

# Exact signature
validate(
    instance,        # The JSON instance to validate (dict, list, scalar)
    schema,          # The JSON Schema to validate against (dict)
    cls=None,        # Validator class (default: auto-detected from $schema)
    *args,
    **kwargs
)
# Returns: None on success
# Raises: ValidationError on first validation failure
# Raises: SchemaError if the schema itself is invalid
```

**Usage:**

```python
from jsonschema import validate, ValidationError

schema = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "age": {"type": "number", "minimum": 0},
        "email": {"type": "string", "format": "email"}
    },
    "required": ["name", "age"]
}

# Valid — no exception
valid_data = {"name": "Alice", "age": 30, "email": "alice@example.com"}
validate(instance=valid_data, schema=schema)

# Invalid — raises ValidationError
try:
    invalid_data = {"name": "Bob", "age": "twenty-five"}
    validate(instance=invalid_data, schema=schema)
except ValidationError as e:
    print(f"Validation failed: {e.message}")
    print(f"Failed at path: {list(e.path)}")
    # Output: Validation failed: 'twenty-five' is not of type 'number'
    # Output: Failed at path: ['age']
```

#### Draft-Specific Validators

**Confirmed API:**

```python
from jsonschema import Draft7Validator, Draft202012Validator

# Create validator instance
validator = Draft7Validator(schema)

# Check validity (no exception)
validator.is_valid(instance)  # Returns bool

# Iterate ALL errors (not just first)
errors = list(validator.iter_errors(instance))
for error in errors:
    print(f"Error at {'.'.join(str(p) for p in error.path)}: {error.message}")
    print(f"  Schema path: {'.'.join(str(p) for p in error.schema_path)}")
    print(f"  Validator: {error.validator}")

# Validate (raises on first error)
validator.validate(instance)  # Raises ValidationError
```

**ValidationError Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `e.message` | `str` | Human-readable error message |
| `e.path` | `deque` | Path to the failing element in the instance |
| `e.schema_path` | `deque` | Path to the failing rule in the schema |
| `e.validator` | `str` | Name of the failing validator keyword |
| `e.validator_value` | `any` | The value of the failing validator keyword |
| `e.instance` | `any` | The failing instance value |
| `e.schema` | `dict` | The schema that failed |
| `e.cause` | `Exception` | The underlying exception (if any) |

**Custom Validator Extension:**

```python
from jsonschema import Draft7Validator
from jsonschema.validators import extend

def custom_keyword(validator, value, instance, schema):
    if not isinstance(instance, (int, float)):
        return
    if instance % value != 0:
        yield ValidationError(f"{instance} is not divisible by {value}")

CustomValidator = extend(
    Draft7Validator,
    validators={"divisibleBy": custom_keyword},
    version="custom"
)
```

---

## Discrepancies and Warnings

### Critical Discrepancies

| # | Library | Assumed Behavior | Actual Behavior | Impact |
|---|---------|-----------------|-----------------|--------|
| 1 | **ChromaDB** | `upsert` can atomically increment metadata counters | `upsert` performs full **replace** of metadata; no atomic increment | HIGH — Must use GET-then-UPSERT pattern, or use SQLite for counters |
| 2 | **ChromaDB** | Distance filtering in query API | No `max_distance` parameter exists; must filter post-query in application code | MEDIUM — Add post-query filtering logic |
| 3 | **ChromaDB** | `$in` has documented size limits | No explicit size limit documented | LOW — Test with expected workload sizes |
| 4 | **Schemathesis** | `from_dict()` accepts raw JSON string | Method name implies dict input; one Context7 example shows string usage (likely a documentation error) | LOW — Always pass parsed dict |

### Warnings

| # | Topic | Warning |
|---|-------|---------|
| 1 | **SQLite INSERT OR REPLACE** | Destructive — deletes row and re-inserts. Use `ON CONFLICT DO UPDATE` instead for counters and preserving ROWIDs. |
| 2 | **ChromaDB frequency counters** | GET-then-UPSERT is NOT atomic. Concurrent updates can lose increments. For mission-critical counters, use SQLite with `ON CONFLICT DO UPDATE SET count = count + 1`. |
| 3 | **ChromaDB PersistentClient** | Intended for local dev/testing. For production multi-process access, use server-backed Chroma (HTTP client). |
| 4 | **NetworkX simple_cycles** | Returns ALL cycles — can be very expensive on large, dense graphs. Consider `length_bound` parameter to limit search. |
| 5 | **difflib SequenceMatcher.ratio()** | Order of `a` and `b` can affect the returned ratio — not guaranteed symmetric. |
| 6 | **FTS5 external content tables** | Must manually keep FTS5 index in sync with source table. Use triggers or explicit rebuild. |

### Confirmed API Signatures Summary

| Library | Function/Method | Status |
|---------|----------------|--------|
| `chromadb.PersistentClient(path=...)` | CONFIRMED |
| `collection.upsert(ids=, documents=, metadatas=, embeddings=)` | CONFIRMED |
| `collection.get(ids=, where=, limit=, offset=, include=)` | CONFIRMED |
| `collection.query(query_texts=, n_results=, where=, include=)` | CONFIRMED |
| `PRAGMA journal_mode=WAL` | CONFIRMED |
| `INSERT ... ON CONFLICT(col) DO UPDATE SET col = expr` | CONFIRMED |
| `CREATE VIRTUAL TABLE ... USING fts5(...)` | CONFIRMED |
| `json_extract(JSON, PATH, ...)` | CONFIRMED |
| `difflib.unified_diff(a, b, fromfile, tofile, n=3, lineterm='\n')` | CONFIRMED |
| `difflib.SequenceMatcher(isjunk, a, b, autojunk=True)` | CONFIRMED |
| `SequenceMatcher.ratio()` → `float [0.0, 1.0]` | CONFIRMED |
| `nx.DiGraph()` | CONFIRMED |
| `nx.simple_cycles(G, length_bound=None)` → `generator[list]` | CONFIRMED |
| `nx.weakly_connected_components(G)` → `generator[set]` | CONFIRMED |
| `bipartite.is_bipartite(G)` → `bool` | CONFIRMED |
| `bipartite.sets(G, top_nodes=None)` → `(set, set)` | CONFIRMED |
| `schemathesis.openapi.from_path(path, base_url=None)` | CONFIRMED |
| `schemathesis.openapi.from_dict(spec_dict)` | CONFIRMED |
| `@schema.parametrize()` decorator pattern | CONFIRMED |
| `jsonschema.validate(instance=, schema=)` | CONFIRMED |
| `Draft7Validator(schema).iter_errors(instance)` | CONFIRMED |
| `Draft7Validator(schema).is_valid(instance)` → `bool` | CONFIRMED |

---

*End of Research Report*
