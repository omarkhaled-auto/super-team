# NetworkX Exhaustive Research Document

> **Source:** Context7 documentation queries against `/websites/networkx_stable` (6060 snippets, High reputation) and `/networkx/networkx` (650 snippets, High reputation)
> **Date:** 2026-02-23
> **Purpose:** Week 8 Graph RAG Exploration -- comprehensive NetworkX reference

---

## Table of Contents

1. [Graph Types and Usage](#1-graph-types-and-usage)
2. [Node and Edge Attribute System](#2-node-and-edge-attribute-system)
3. [Graph Algorithms for Code/Service Relationship Graphs](#3-graph-algorithms-for-codeservice-relationship-graphs)
4. [Serialization and Persistence](#4-serialization-and-persistence)
5. [Subgraph and Context Extraction](#5-subgraph-and-context-extraction)
6. [Heterogeneous Graphs](#6-heterogeneous-graphs)
7. [Performance and Scaling](#7-performance-and-scaling)
8. [Integration with Vector Stores and Graph RAG Patterns](#8-integration-with-vector-stores-and-graph-rag-patterns)
9. [Deprecations and Removals](#9-deprecations-and-removals)

---

## 1. Graph Types and Usage

### 1.1 The Four Core Graph Classes

NetworkX provides four graph classes based on two independent properties:

| Class | Directed? | Multi-edges? | Use Case |
|-------|-----------|-------------|----------|
| `nx.Graph` | No | No | Simple undirected relationships |
| `nx.DiGraph` | Yes | No | Directed dependencies, call graphs |
| `nx.MultiGraph` | No | Yes | Multiple relationship types between same pair |
| `nx.MultiDiGraph` | Yes | Yes | Directed + multiple edge types |

```python
import networkx as nx

G = nx.Graph()          # Undirected, simple
G = nx.DiGraph()        # Directed, simple
G = nx.MultiGraph()     # Undirected, allows parallel edges
G = nx.MultiDiGraph()   # Directed, allows parallel edges
```

### 1.2 Key Properties from Documentation

- **Directed ("Di" prefix):** "We make this distinction because many classical graph properties are defined differently for directed graphs." Edge pairs `(u, v)` are ordered.
- **Multi-edges ("Multi" prefix):** "Multiple edges requires a different data structure." Edges are distinguished by an additional `key` attribute.
- **All graph classes allow any hashable object as a node.** This includes strings, tuples, integers, and more. `None` is NOT allowed as a node.

### 1.3 Converting Between Graph Types

```python
# Convert undirected to directed (creates two directed edges per undirected edge)
G = nx.Graph([(1, 2), (2, 3)])
H = nx.DiGraph(G)
list(H.edges())  # [(1, 2), (2, 1), (2, 3), (3, 2)]

# Convert directed to undirected
H = nx.Graph(G)  # Collapses (u,v) and (v,u) into single undirected edge
```

### 1.4 Initialization from Various Data Sources

```python
# From edge list
G = nx.Graph([(1, 2), (2, 3), (3, 4)])

# From dict-of-dicts (adjacency)
G = nx.Graph({0: {1: {"weight": 1}}, 1: {2: {"weight": 2}}})

# With graph-level attributes
G = nx.Graph(name="my graph", day="Friday")
G.graph  # {'name': 'my graph', 'day': 'Friday'}
```

### 1.5 When Directionality Matters for Algorithms

For **Graph RAG on code/service graphs**, `DiGraph` is almost always the right choice because:
- Call relationships are directional (A calls B)
- Import/dependency relationships are directional
- Data flow has direction
- `topological_sort` requires `DiGraph`
- `ancestors` / `descendants` are meaningful on directed graphs
- `pagerank` converts undirected to directed internally (two edges per undirected edge)

**Recommendation for Graph RAG:** Use `nx.DiGraph` as the primary type. If you need multiple relationship types between the same pair of nodes (e.g., "calls", "imports", "inherits"), use `nx.MultiDiGraph` -- but be aware that MultiGraph adds complexity to many algorithms.

---

## 2. Node and Edge Attribute System

### 2.1 Internal Data Structure

From the docs: "The graph internal data structures are based on an adjacency list representation and implemented using Python dictionary datastructures. The graph adjacency structure is implemented as a Python dictionary of dictionaries; the outer dictionary is keyed by nodes to values that are themselves dictionaries keyed by neighboring node to the edge attributes associated with that edge."

This is a **dict-of-dicts-of-dicts** structure:
```
G._adj = {
    node_u: {
        node_v: {attr_key: attr_value, ...},
        ...
    },
    ...
}
```

This design enables **O(1) node lookup, O(1) edge lookup, O(degree) neighbor iteration**.

### 2.2 Graph-Level Attributes

```python
G = nx.Graph(day="Friday", season="summer")
G.graph['day']     # 'Friday'
G.graph['custom'] = 'value'  # Add attribute after creation
```

### 2.3 Node Attributes

**Adding nodes with attributes:**
```python
G.add_node(1, weight=10, color="red")
G.add_nodes_from([3], time="2pm")
```

**Accessing node attributes:**
```python
G.nodes[1]['weight']   # 10
G.nodes[1]             # {'weight': 10, 'color': 'red'}
```

**Iterating with data:**
```python
list(G.nodes(data=True))
# [(1, {'weight': 10, 'color': 'red'}), (3, {'time': '2pm'})]
```

**Important:** Each node has its own attribute dictionary. Different nodes CAN have entirely different attribute schemas. There is no schema enforcement -- this is a feature for heterogeneous graphs.

### 2.4 Edge Attributes

**Adding edges with attributes:**
```python
G.add_edge(1, 2, weight=4.7)
G.add_edges_from([(3, 4), (4, 5)], color="red")
G.add_edges_from([(1, 2, {"color": "blue"}), (2, 3, {"weight": 8})])
```

**Accessing edge attributes (multiple equivalent ways):**
```python
G[1][2]['weight']           # Via adjacency dict
G.edges[1, 2]['weight']    # Via edges view
G.edges[1, 2]['color']     # 'blue'
```

**Modifying edge attributes:**
```python
G[1][2]["weight"] = 4.0
G.edges[1, 2]["weight"] = 4  # Both work
```

**Warning from docs:** `G.edges[1, 2]` returns a read-only dict-like structure for the view level, but attribute assignment through `G.edges[1, 2]['weight'] = 4` works. For multigraphs: `MG.edges[u, v, key][name] = value`.

**Iterating edges with data:**
```python
list(G.edges(data=True))
# [(1, 2, {'weight': 4.7, 'color': 'blue'}), ...]
```

### 2.5 Efficient Querying by Attribute Value

NetworkX does NOT have built-in indexed attribute queries. You must iterate and filter:

```python
# Find all nodes with a specific attribute value
heavy_nodes = [n for n, d in G.nodes(data=True) if d.get('weight', 0) > 5]

# Find all edges with a specific attribute
red_edges = [(u, v) for u, v, d in G.edges(data=True) if d.get('color') == 'red']
```

For efficient attribute-based querying in a Graph RAG system, you should maintain a **separate index** (e.g., a dict mapping attribute values to node sets) alongside the graph.

### 2.6 node_link_data and node_link_graph

These are the primary JSON serialization functions:

**`node_link_data(G, *, source, target, name, key, edges, nodes)` -- Graph to dict:**

```python
from pprint import pprint
G = nx.Graph([("A", "B")])
data = nx.node_link_data(G, edges="edges")
pprint(data)
# {'directed': False,
#  'edges': [{'source': 'A', 'target': 'B'}],
#  'graph': {},
#  'multigraph': False,
#  'nodes': [{'id': 'A'}, {'id': 'B'}]}
```

**Parameters (all keyword-only except G):**
- `source` (str, default="source") -- key name for source node in edge dicts
- `target` (str, default="target") -- key name for target node in edge dicts
- `name` (str, default="id") -- key name for node ID in node dicts
- `key` (str, default="key") -- key name for edge key (multigraphs only)
- `edges` (str) -- key name for edges list in output dict
- `nodes` (str, default="nodes") -- key name for nodes list in output dict

**DEPRECATION WARNING:** The `link` parameter is deprecated since 3.4, will be removed in 3.6. Use `edges` instead. If neither `edges` nor `link` is specified, a `FutureWarning` is raised and the default is `"links"` (will change to `"edges"` in 3.6).

**`node_link_graph(data, *, directed, multigraph, source, target, name, key, edges, nodes)` -- dict to Graph:**

```python
data = {
    "directed": False,
    "multigraph": False,
    "graph": {},
    "nodes": [{"id": "A"}, {"id": "B"}],
    "edges": [{"source": "A", "target": "B"}]
}
H = nx.node_link_graph(data, edges="edges")
```

**Key behavior:** All node and edge attributes are preserved in the serialized format. Attribute keys are converted to strings to comply with JSON.

---

## 3. Graph Algorithms for Code/Service Relationship Graphs

### 3.1 Shortest Path

```python
# Single shortest path (returns list of nodes)
path = nx.shortest_path(G, source=0, target=4)

# All shortest paths between two nodes
paths = list(nx.all_shortest_paths(G, source=0, target=4))

# All simple paths (may be exponential -- use cutoff!)
paths = list(nx.all_simple_paths(G, source=0, target=3, cutoff=2))

# Dijkstra (weighted)
length = nx.single_source_dijkstra_path_length(G, source=0)
# Returns dict: {node: distance, ...}
# Supports cutoff parameter to limit search depth

# Bellman-Ford (supports negative weights, detects negative cycles)
pred, dist = nx.bellman_ford_predecessor_and_distance(G, 0)

# A* (with heuristic)
length = nx.astar_path_length(G, source, target, heuristic=my_heuristic)
```

**`all_simple_paths` for Graph RAG:** Extremely useful for finding all connection paths between two code entities. Always use `cutoff` parameter to prevent combinatorial explosion:
```python
# Find all paths between two services, max 4 hops
paths = list(nx.all_simple_paths(G, "service_a", "service_b", cutoff=4))
```

**Finding paths to multiple targets (DAG pattern):**
```python
G = nx.DiGraph([(0, 1), (2, 1), (1, 3), (1, 4)])
roots = (v for v, d in G.in_degree() if d == 0)
leaves = [v for v, d in G.out_degree() if d == 0]
all_paths = []
for root in roots:
    paths = nx.all_simple_paths(G, root, leaves)  # Pass iterable of targets
    all_paths.extend(paths)
```

### 3.2 Traversal: BFS and DFS

**BFS Tree:**
```python
T = nx.bfs_tree(G, source=1)
# Returns: nx.DiGraph (oriented tree)
# Parameters: G, source, reverse=False, depth_limit=None, sort_neighbors=None
list(T.edges())  # [(1, 0), (1, 2)]

# With depth limit (critical for Graph RAG context windows)
T = nx.bfs_tree(G, source=3, depth_limit=3)
```

**DFS Tree:**
```python
T = nx.dfs_tree(G, source=0, depth_limit=2)
# Returns: nx.DiGraph (oriented tree)
list(T.edges())  # [(0, 1), (1, 2)]
```

**BFS/DFS Edges (generators):**
```python
# Iterate edges in BFS order
for u, v in nx.bfs_edges(G, source=0, depth_limit=3):
    print(f"{u} -> {v}")

# Iterate edges in DFS order
for u, v in nx.dfs_edges(G, source=0, depth_limit=3):
    print(f"{u} -> {v}")
```

**BFS/DFS Predecessors:**
```python
# BFS predecessors: returns iterator of (node, predecessor) tuples
sorted(nx.bfs_predecessors(G, source=2))
# [(3, 2), (4, 3), (5, 3), (6, 5), (7, 4)]

# DFS predecessors: returns dict {node: [predecessors]}
pred = nx.dfs_predecessors(G, source=0)
sorted(pred.items())
# [(1, [0]), (2, [1]), (3, [2]), (4, [3])]
```

### 3.3 Ancestors and Descendants

```python
DG = nx.path_graph(5, create_using=nx.DiGraph)

# All nodes reachable FROM node 2
sorted(nx.descendants(DG, 2))  # [3, 4]

# Include the node itself
sorted(nx.descendants(DG, 2) | {2})  # [2, 3, 4]

# All nodes that CAN REACH node 2
sorted(nx.ancestors(DG, 2))  # [0, 1]
```

**For Graph RAG:** `ancestors` finds all upstream dependencies/callers. `descendants` finds all downstream dependents/callees. Both use BFS internally.

### 3.4 Centrality Measures

**Degree Centrality:**
```python
G = nx.Graph([(0, 1), (0, 2), (0, 3), (1, 2), (1, 3)])
nx.degree_centrality(G)
# {0: 1.0, 1: 1.0, 2: 0.6666..., 3: 0.6666...}
# Normalized by (n-1) where n = number of nodes
# For multigraphs, values CAN exceed 1.0
```

Returns: `dict` mapping node to centrality value (float).

**Betweenness Centrality:**
```python
bc = nx.betweenness_centrality(G, normalized=True, weight=None)
# Parameters:
#   G: graph
#   normalized: bool (default True) -- normalize by 2/((n-1)(n-2)) for graphs
#   weight: None or string -- edge attribute for weighted shortest paths
#   k: int or None -- sample k nodes for approximation (faster for large graphs)
# Returns: dict {node: centrality_value}
```

**Betweenness Centrality Subset (targeted):**
```python
# Only consider paths between specific source and target sets
bc = nx.betweenness_centrality_subset(
    G,
    sources=[node_a, node_b],
    targets=[node_c, node_d],
    normalized=False,
    weight=None
)
```

**PageRank:**
```python
G = nx.DiGraph(nx.path_graph(4))
pr = nx.pagerank(G, alpha=0.9)
# Parameters:
#   G: NetworkX graph (undirected auto-converted to directed)
#   alpha: float (default=0.85) -- damping factor
#   personalization: dict or None -- personalization vector {node: value}
#   max_iter: int (default=100) -- max power iteration steps
#   tol: float (default=1e-6) -- convergence tolerance (stops at len(G)*tol)
#   nstart: dict or None -- starting values
#   weight: str (default='weight') -- edge weight attribute name
#   dangling: dict or None -- outedges for dangling nodes
# Returns: dict {node: pagerank_value}
# Raises: PowerIterationFailedConvergence if doesn't converge
```

**For Graph RAG:** PageRank identifies the most "important" nodes in the code graph. Betweenness centrality finds nodes that serve as critical bridges/intermediaries.

### 3.5 Community Detection

**Louvain Community Detection:**
```python
G = nx.petersen_graph()
communities = nx.community.louvain_communities(G, seed=123)
# Returns: list of sets, e.g., [{0, 4, 5, 7, 9}, {1, 2, 3, 6, 8}]

# Parameters:
#   G: NetworkX graph
#   weight: str or None (default="weight") -- edge weight attribute
#   resolution: float (default=1) -- <1 favors larger communities, >1 favors smaller
#   threshold: float (default=0.0000001) -- modularity gain threshold
#   max_level: int or None (default=None) -- max algorithm levels
#   seed: int or None -- for reproducibility
```

**Louvain Partitions (multi-level):**
```python
# Get partitions at each level of the hierarchy
for partition in nx.community.louvain_partitions(G):
    print(partition)

# Get only the final partition efficiently
from collections import deque
partitions = nx.community.louvain_partitions(G)
final_partition = deque(partitions, maxlen=1).pop()
```

**Asynchronous Label Propagation:**
```python
communities = list(nx.community.asyn_lpa_communities(G, weight=None, seed=42))
# Returns: iterable of sets of nodes
# Parameters:
#   G: Graph
#   weight: str or None -- edge weight attribute
#   seed: int or None
```

**For Graph RAG:** Community detection groups related code entities (modules, services, components) into clusters. The `resolution` parameter in Louvain controls granularity.

### 3.6 Cycle Detection

**find_cycle:**
```python
# Find a single cycle via DFS
try:
    cycle = nx.find_cycle(G, orientation="original")
except nx.NetworkXNoCycle:
    print("No cycle found")

# Parameters:
#   G: graph
#   source: node or list of nodes (optional)
#   orientation: None | 'original' | 'reverse' | 'ignore'
# Returns: list of edge tuples [(u, v, direction), ...]
# Raises: NetworkXNoCycle if no cycle exists
```

**simple_cycles:**
```python
# Find ALL simple cycles (can be very expensive!)
cycles = list(nx.simple_cycles(G))
```

**For Graph RAG:** Circular dependencies in code. Use `find_cycle` for quick detection, `simple_cycles` only on small subgraphs.

### 3.7 Topological Sort (DAGs)

```python
DG = nx.DiGraph([(1, 2), (2, 3)])

# Generator of nodes in topological order
list(nx.topological_sort(DG))  # [1, 2, 3]

# Reverse topological order
list(reversed(list(nx.topological_sort(DG))))  # [3, 2, 1]

# Topological generations (nodes at same "level")
for generation in nx.topological_generations(DG):
    print(generation)
# [1]  -- first generation
# [2]  -- second generation
# [3]  -- third generation

# Check if graph is a DAG
nx.is_directed_acyclic_graph(DG)  # True
```

**Raises:**
- `NetworkXError` if graph is undirected
- `NetworkXUnfeasible` if graph contains a cycle

**For Graph RAG:** Topological sort gives execution/dependency order. `topological_generations` shows build layers.

### 3.8 Connected Components

**Undirected graphs:**
```python
components = list(nx.connected_components(G))
# Returns: generator of sets of nodes

# Check connectivity
nx.is_connected(G)  # True/False

# Largest component
largest_cc = max(nx.connected_components(G), key=len)
```

**Directed graphs -- Strongly Connected Components (SCCs):**
```python
G = nx.cycle_graph(4, create_using=nx.DiGraph())
sccs = list(nx.strongly_connected_components(G))
# Returns: generator of sets of nodes
# Uses Tarjan's algorithm with Nuutila's modifications (nonrecursive)

# Sorted by size, largest first
sorted(nx.strongly_connected_components(G), key=len, reverse=True)
```

**Directed graphs -- Weakly Connected Components:**
```python
wccs = list(nx.weakly_connected_components(G))
# Weakly connected = connected when ignoring edge direction
# Not implemented for undirected graphs

# Sorted by size
[len(c) for c in sorted(nx.weakly_connected_components(G), key=len, reverse=True)]
```

**For Graph RAG:** SCCs identify tightly coupled code clusters. Weakly connected components find isolated subsystems.

---

## 4. Serialization and Persistence

### 4.1 write_gpickle / read_gpickle -- REMOVED

**Status: REMOVED in NetworkX 3.0.**

From the migration guide: "`read_gpickle` and `write_gpickle` have been removed since NetworkX 3.0."

**Replacement -- use Python's built-in pickle:**
```python
import pickle

G = nx.path_graph(4)

# Write
with open('graph.gpickle', 'wb') as f:
    pickle.dump(G, f, pickle.HIGHEST_PROTOCOL)

# Read
with open('graph.gpickle', 'rb') as f:
    G = pickle.load(f)
```

### 4.2 node_link_data / node_link_graph -- JSON Format

This is the recommended approach for JSON serialization:

```python
import json
import networkx as nx

G = nx.Graph([("A", "B")])
G.nodes["A"]["type"] = "service"
G.edges["A", "B"]["weight"] = 1.5

# Serialize to JSON string
data = nx.node_link_data(G, edges="edges")
json_str = json.dumps(data)

# Deserialize from JSON string
data_back = json.loads(json_str)
H = nx.node_link_graph(data_back, edges="edges")
```

**Output format:**
```json
{
    "directed": false,
    "multigraph": false,
    "graph": {},
    "nodes": [
        {"id": "A", "type": "service"},
        {"id": "B"}
    ],
    "edges": [
        {"source": "A", "target": "B", "weight": 1.5}
    ]
}
```

**Custom attribute naming for JavaScript compatibility:**
```python
data = nx.node_link_data(
    H, edges="links", source="from", target="to", nodes="vertices"
)
# {'directed': True, 'graph': {}, 'multigraph': False,
#  'links': [{'from': 1, 'to': 0}],
#  'vertices': [{'id': 0}, {'id': 1}]}
```

**Note:** Attribute keys are converted to strings for JSON compliance.

**JSON as default encoder:**
```python
# Can also pass node_link_data as a default encoder
s = json.dumps(G, default=nx.node_link_data)
```

### 4.3 GraphML (XML Format)

```python
# Write
nx.write_graphml(G, path='output_graph.graphml')
# Optional: encoding='utf-8', prettyprint=True

# Read
G = nx.read_graphml('graph.graphml')
# Optional: node_type=int, edge_key_type=str, force_multigraph=True
```

**GraphML features from docs:**
- XML-based format
- Supports graph properties and application-specific data
- Handles gzip and bz2 compressed files
- Type conversion for nodes and edges
- Does NOT support: mixed graphs, hypergraphs, nested graphs, or ports

### 4.4 GEXF Format

```python
# Write
nx.write_gexf(G, "test.gexf")

# With visualization data
G.nodes[0]["viz"] = {
    "size": 54,
    "position": {"x": 0, "y": 1},
    "color": {"r": 0, "g": 0, "b": 256}
}
nx.write_gexf(G, "test_viz.gexf")
```

### 4.5 Format Tradeoffs

| Format | Pros | Cons | Best For |
|--------|------|------|----------|
| **JSON (node_link)** | Human-readable, web-compatible, custom keys | Larger file size, string keys only | APIs, web apps, Graph RAG |
| **GraphML** | Standard XML, tool interop, typed attributes | Verbose, slower parse | Tool exchange (Gephi, etc.) |
| **Pickle** | Fast, preserves Python objects exactly | Not portable, security risk, not human-readable | Internal caching |
| **GEXF** | Visualization metadata support | XML overhead | Visualization tools |

### 4.6 Persisting to SQLite

**Context7 did NOT return specific documentation for SQLite persistence patterns.** This is not a built-in NetworkX feature.

Recommended approach for Graph RAG:
```python
import sqlite3
import json

def save_graph_to_sqlite(G, db_path, table_name="graphs"):
    """Save graph as JSON in SQLite."""
    conn = sqlite3.connect(db_path)
    data = json.dumps(nx.node_link_data(G, edges="edges"))
    conn.execute(f"CREATE TABLE IF NOT EXISTS {table_name} (id TEXT PRIMARY KEY, data TEXT)")
    conn.execute(f"INSERT OR REPLACE INTO {table_name} VALUES (?, ?)", ("main", data))
    conn.commit()
    conn.close()

def load_graph_from_sqlite(db_path, table_name="graphs"):
    """Load graph from SQLite."""
    conn = sqlite3.connect(db_path)
    row = conn.execute(f"SELECT data FROM {table_name} WHERE id=?", ("main",)).fetchone()
    conn.close()
    if row:
        return nx.node_link_graph(json.loads(row[0]), edges="edges")
    return None
```

### 4.7 Incremental Update Persistence

**Context7 did NOT return specific documentation for incremental persistence.**

NetworkX graphs are mutable in-memory structures. For incremental persistence in Graph RAG, recommended patterns:

1. **Full re-serialization:** Simple, works well for graphs under ~100K nodes
2. **Event log + snapshot:** Log mutations, periodically snapshot full graph
3. **Node/edge-level storage:** Store nodes and edges as individual rows in SQLite, reconstruct with `from_pandas_edgelist` or manual `add_node`/`add_edge`

---

## 5. Subgraph and Context Extraction

### 5.1 ego_graph -- N-Hop Neighborhood Extraction

This is the **single most important function for Graph RAG context extraction**.

```python
H = nx.ego_graph(G, n, radius=1, center=True, undirected=False, distance=None)
```

**Parameters:**
- `G` -- NetworkX Graph or DiGraph
- `n` -- center node
- `radius` (number, default=1) -- include all neighbors within this distance
- `center` (bool, default=True) -- include center node in result
- `undirected` (bool, default=False) -- for DiGraphs, if True use both in- and out-neighbors
- `distance` (key, default=None) -- edge attribute to use as distance (e.g., `'weight'`)

**Key behaviors from docs:**
- For directed graphs, produces the **"out" neighborhood (successors)** by default
- To get predecessors: `nx.ego_graph(D.reverse(), node, radius=N)`
- To get both directions: `undirected=True`
- **Node, edge, and graph attributes are copied** to the returned subgraph
- Returns a **copy** (not a view) via `G.subgraph(sp).copy()`

**Internal implementation (from source):**
```python
# Without custom distance: uses single_source_shortest_path_length with cutoff
sp = nx.single_source_shortest_path_length(G, n, cutoff=radius)

# With custom distance: uses single_source_dijkstra with cutoff
sp, _ = nx.single_source_dijkstra(G, n, cutoff=radius, weight=distance)

H = G.subgraph(sp).copy()
if not center:
    H.remove_node(n)
return H
```

**Graph RAG usage patterns:**
```python
# Get 2-hop context around a function node
context_graph = nx.ego_graph(code_graph, "my_function", radius=2)

# Get bidirectional context (callers + callees) for a service
context_graph = nx.ego_graph(
    service_graph, "auth_service", radius=2, undirected=True
)

# Get upstream dependencies only (predecessors)
upstream = nx.ego_graph(dep_graph.reverse(), "my_module", radius=3)
```

### 5.2 Subgraph Induced by Node Set

```python
# Returns a VIEW (not a copy) -- reflects changes to original graph
H = G.subgraph([0, 1, 3])
# Only includes edges where BOTH endpoints are in the node set

# For a mutable copy:
H = G.subgraph([0, 1, 3]).copy()
```

**`nx.induced_subgraph`:**
```python
H = nx.induced_subgraph(G, [0, 1, 3])
# Same as G.subgraph() but as a standalone function
# Returns a VIEW
```

**Edge-induced subgraph:**
```python
H = G.edge_subgraph([(0, 1), (3, 4)])
list(H.nodes)  # [0, 1, 3, 4]
list(H.edges)  # [(0, 1), (3, 4)]
# Returns a VIEW (read-only, use .copy() for mutable)
```

### 5.3 Paths Between Two Nodes with Intermediate Nodes

```python
# All simple paths between two nodes (with length limit)
paths = list(nx.all_simple_paths(G, source="node_a", target="node_b", cutoff=5))

# Shortest path
path = nx.shortest_path(G, source="node_a", target="node_b")

# All shortest paths
paths = list(nx.all_shortest_paths(G, source="node_a", target="node_b"))

# Extract subgraph containing all nodes on paths between two nodes
all_path_nodes = set()
for path in nx.all_simple_paths(G, "node_a", "node_b", cutoff=4):
    all_path_nodes.update(path)
path_subgraph = G.subgraph(all_path_nodes).copy()
```

### 5.4 subgraph_view -- Filtered Views (Zero-Copy)

```python
# Filter nodes
def filter_node(n):
    return n != 5  # Exclude node 5

view = nx.subgraph_view(G, filter_node=filter_node)
view.nodes()  # All nodes except 5

# Filter edges
def filter_edge(n1, n2):
    return G[n1][n2].get("cross_me", True)

view = nx.subgraph_view(G, filter_edge=filter_edge)

# Combined filters
view = nx.subgraph_view(G, filter_node=filter_node, filter_edge=filter_edge)
```

**Key properties:**
- Returns a **read-only view** (no copy)
- Filter functions are called **lazily** as elements are queried -- no upfront cost
- Changes to the original graph G are reflected in the view
- Works with all graph types (Graph, DiGraph, MultiGraph, MultiDiGraph)

**Graph RAG usage -- filter by node type:**
```python
# View only "function" nodes
func_view = nx.subgraph_view(
    code_graph,
    filter_node=lambda n: code_graph.nodes[n].get('type') == 'function'
)

# View only "calls" edges
calls_view = nx.subgraph_view(
    code_graph,
    filter_edge=lambda u, v: code_graph[u][v].get('relation') == 'calls'
)
```

### 5.5 K-Core Subgraph

```python
# Extract k-core (largest subgraph where every node has degree >= k)
core = nx.k_core(G, k=3)
# Not implemented for multigraphs or graphs with self-loops

# K-shell (nodes with core number exactly k)
shell = nx.k_shell(G, k=1)
```

---

## 6. Heterogeneous Graphs

### 6.1 Multiple Node Types / Edge Types in NetworkX

NetworkX does NOT have a dedicated heterogeneous graph class. Instead, heterogeneity is achieved through **node and edge attributes**:

```python
G = nx.DiGraph()

# Different node types via 'type' attribute
G.add_node("auth_service", type="service", language="python")
G.add_node("login_func", type="function", module="auth")
G.add_node("users_table", type="database_table", schema="public")

# Different edge types via 'relation' attribute
G.add_edge("auth_service", "login_func", relation="contains")
G.add_edge("login_func", "users_table", relation="reads_from")
G.add_edge("auth_service", "users_table", relation="depends_on")
```

### 6.2 Filtering Traversal by Node/Edge Type

Using `subgraph_view` for type-based filtering:

```python
# View of only service nodes
service_view = nx.subgraph_view(
    G,
    filter_node=lambda n: G.nodes[n].get('type') == 'service'
)

# View of only "calls" relationships
calls_view = nx.subgraph_view(
    G,
    filter_edge=lambda u, v: G[u][v].get('relation') == 'calls'
)

# Combined: only function-to-function call edges
func_calls = nx.subgraph_view(
    G,
    filter_node=lambda n: G.nodes[n].get('type') == 'function',
    filter_edge=lambda u, v: G[u][v].get('relation') == 'calls'
)
```

### 6.3 Using MultiDiGraph for Multiple Relationship Types

When the same pair of nodes has multiple relationship types:

```python
MG = nx.MultiDiGraph()
MG.add_edge("service_a", "service_b", key="calls", weight=10)
MG.add_edge("service_a", "service_b", key="shares_db", database="orders")

# Access specific edge by key
MG.edges["service_a", "service_b", "calls"]["weight"]  # 10

# Iterate all edges between two nodes
for u, v, key, data in MG.edges(keys=True, data=True):
    print(f"{u} --[{key}]--> {v}: {data}")
```

### 6.4 Bipartite Graphs

NetworkX supports bipartite graph algorithms:

```python
from networkx.algorithms import bipartite

B = nx.Graph()
B.add_edges_from([("a", 1), ("b", 1), ("a", 2), ("b", 2)])

# Project onto one node set
G = bipartite.projected_graph(B, ["a", "b"])
list(G.edges())  # [('a', 'b')]

# Weighted projection
G = bipartite.weighted_projected_graph(B, ["a", "b"])

# Multigraph projection (edge per shared neighbor)
G = bipartite.projected_graph(B, ["a", "b"], multigraph=True)
```

### 6.5 Related Libraries for Heterogeneous Graphs

**Context7 did not return documentation on StellarGraph, PyG, or DGL integration.** Based on common patterns:

- **StellarGraph:** Wraps NetworkX graphs for GNN-based operations on heterogeneous graphs
- **PyTorch Geometric (PyG):** Has `HeteroData` for heterogeneous graphs
- **DGL:** Has `DGLHeteroGraph`

For Graph RAG purposes, NetworkX's attribute-based approach is sufficient for most use cases. The `subgraph_view` filtering pattern handles type-aware traversal without needing specialized libraries.

---

## 7. Performance and Scaling

### 7.1 Internal Data Structure Performance

The dict-of-dicts-of-dicts structure provides:

| Operation | Time Complexity |
|-----------|----------------|
| Add node | O(1) |
| Add edge | O(1) |
| Remove node | O(degree(n)) |
| Remove edge | O(1) |
| Check node existence | O(1) |
| Check edge existence | O(1) |
| Get neighbors | O(1) to access, O(degree) to iterate |
| Get node attributes | O(1) |
| Get edge attributes | O(1) |

### 7.2 Practical Size Limits

**Context7 did not return specific documentation on size limits.** Based on the data structure:

- **Memory:** Each node and edge consumes Python dict overhead. Rough estimates:
  - Bare node: ~300-500 bytes
  - Bare edge: ~200-400 bytes
  - With attributes: add ~100-200 bytes per attribute
- **Practical in-memory limits:**
  - ~1M nodes, ~10M edges: comfortable on 16GB RAM
  - ~10M nodes, ~100M edges: requires 64GB+ RAM
  - Beyond that: consider graph databases (Neo4j) or out-of-core backends

### 7.3 Algorithm Complexity Scaling

| Algorithm | Time Complexity | Notes |
|-----------|----------------|-------|
| `shortest_path` (BFS) | O(V + E) | Unweighted |
| `shortest_path` (Dijkstra) | O((V + E) log V) | Weighted |
| `all_simple_paths` | O(V! / (V-k)!) worst case | USE CUTOFF! |
| `pagerank` | O(iterations * E) | Power iteration |
| `betweenness_centrality` | O(V * E) | Exact |
| `betweenness_centrality(k=k)` | O(k * E) | Approximation |
| `louvain_communities` | O(V * log V) typical | Heuristic |
| `topological_sort` | O(V + E) | DAGs only |
| `connected_components` | O(V + E) | BFS-based |
| `strongly_connected_components` | O(V + E) | Tarjan's |
| `ego_graph` | O(V + E) worst case | Bounded by radius |

### 7.4 Best Practices for Large Graphs

1. **Use generators, not lists:** Many functions return generators. Don't `list()` them unless needed.
2. **Use views, not copies:** `G.subgraph()` returns a view. Only `.copy()` when you need mutation.
3. **Use `cutoff` parameters:** `all_simple_paths(cutoff=N)`, `bfs_tree(depth_limit=N)`, `ego_graph(radius=N)`.
4. **Approximate centrality:** Use `betweenness_centrality(k=100)` instead of exact computation.
5. **Avoid `simple_cycles` on large graphs:** Exponential in the worst case.
6. **Use `subgraph_view` instead of filtering + rebuilding:** Zero-copy, lazy evaluation.

### 7.5 Backend Dispatch System (NetworkX 3.x)

NetworkX 3.x introduced a backend dispatch system for GPU/parallel acceleration:

```python
# Explicit backend for a single call
result = nx.betweenness_centrality(G, k=10, backend="parallel")
result = nx.pagerank(G, backend="cugraph")

# Configuration-based automatic dispatch
nx.config.backend_priority.algos = ['cugraph', 'parallel']
nx.config.fallback_to_nx = True

# Environment variable configuration
# NETWORKX_BACKEND_PRIORITY_ALGOS=cugraph
# NETWORKX_BACKEND_PRIORITY_GENERATORS=cugraph
# NETWORKX_FALLBACK_TO_NX=True

# Create backend graph directly
backend_graph = nx.Graph(backend='my_backend')
```

Available backends include:
- **cugraph:** NVIDIA GPU acceleration
- **parallel:** CPU parallel processing
- **graphblas:** GraphBLAS-based acceleration

---

## 8. Integration with Vector Stores and Graph RAG Patterns

### 8.1 Overview

**Context7 did not return specific documentation on NetworkX + vector store integration or Graph RAG patterns.** This section is based on architectural patterns derived from the documented NetworkX APIs.

### 8.2 Node Embedding Pattern

```python
# Each node in the graph has associated text that gets embedded
G = nx.DiGraph()
G.add_node("auth_service",
    type="service",
    description="Handles user authentication and JWT token management",
    file_path="src/services/auth.py",
    embedding_id="chroma_id_123"  # Reference to vector store
)

# Edge stores relationship metadata
G.add_edge("auth_service", "user_repository",
    relation="depends_on",
    description="Auth service queries user repo for credentials"
)
```

### 8.3 Graph Traversal to Context Window Pattern

The core Graph RAG pattern: use graph structure to select which documents to include in the LLM context window.

```python
def get_graph_context(G, query_node, radius=2, max_tokens=4000):
    """
    Extract relevant context from graph neighborhood.

    1. Get N-hop neighborhood via ego_graph
    2. Rank nodes by relevance (centrality, distance)
    3. Collect text/descriptions up to token budget
    """
    # Step 1: Get neighborhood
    subgraph = nx.ego_graph(G, query_node, radius=radius, undirected=True)

    # Step 2: Rank by distance from query node
    distances = nx.single_source_shortest_path_length(subgraph, query_node)

    # Step 3: Sort nodes by distance (closest first), then by PageRank
    pr = nx.pagerank(subgraph)
    ranked_nodes = sorted(
        subgraph.nodes(),
        key=lambda n: (distances.get(n, float('inf')), -pr.get(n, 0))
    )

    # Step 4: Collect context
    context_parts = []
    for node in ranked_nodes:
        node_data = subgraph.nodes[node]
        context_parts.append(f"[{node_data.get('type', 'unknown')}] {node}: {node_data.get('description', '')}")

    return "\n".join(context_parts)
```

### 8.4 Hybrid Graph + Vector Search Pattern

```python
def hybrid_retrieval(G, query_embedding, vector_store, top_k=5, expansion_radius=1):
    """
    1. Vector search finds semantically similar nodes
    2. Graph expansion adds structurally related nodes
    3. Combined context sent to LLM
    """
    # Step 1: Vector similarity search
    results = vector_store.query(query_embedding, n_results=top_k)
    seed_nodes = [r['node_id'] for r in results]

    # Step 2: Graph expansion
    expanded_nodes = set(seed_nodes)
    for node in seed_nodes:
        if node in G:
            neighborhood = nx.ego_graph(G, node, radius=expansion_radius)
            expanded_nodes.update(neighborhood.nodes())

    # Step 3: Extract subgraph
    context_subgraph = G.subgraph(expanded_nodes).copy()

    # Step 4: Rank expanded nodes
    pr = nx.pagerank(context_subgraph)
    return sorted(expanded_nodes, key=lambda n: -pr.get(n, 0))
```

### 8.5 Community-Based Retrieval Pattern

```python
def community_retrieval(G, query_node):
    """
    Find the community containing the query node,
    then return all community members as context.
    """
    communities = nx.community.louvain_communities(G, seed=42)

    for community in communities:
        if query_node in community:
            # Return subgraph of the community
            return G.subgraph(community).copy()

    # Fallback: ego graph
    return nx.ego_graph(G, query_node, radius=2)
```

### 8.6 Path-Based Context for "How does X relate to Y?"

```python
def relationship_context(G, node_a, node_b, max_path_length=5):
    """
    Find all paths between two entities and extract
    the connecting context.
    """
    # Find all simple paths (bounded)
    paths = list(nx.all_simple_paths(G, node_a, node_b, cutoff=max_path_length))

    if not paths:
        # Try undirected
        U = G.to_undirected()
        paths = list(nx.all_simple_paths(U, node_a, node_b, cutoff=max_path_length))

    # Collect all intermediate nodes
    all_nodes = set()
    for path in paths:
        all_nodes.update(path)

    # Build context subgraph
    context_subgraph = G.subgraph(all_nodes).copy()

    return {
        "paths": paths,
        "subgraph": context_subgraph,
        "intermediate_nodes": all_nodes - {node_a, node_b}
    }
```

### 8.7 Dependency Chain Context

```python
def dependency_context(G, target_node):
    """
    Get full upstream dependency chain for understanding
    what a node depends on.
    """
    # All ancestors (upstream dependencies)
    upstream = nx.ancestors(G, target_node)
    upstream.add(target_node)

    # All descendants (downstream dependents)
    downstream = nx.descendants(G, target_node)

    # Topological sort of the dependency subgraph
    dep_subgraph = G.subgraph(upstream).copy()
    if nx.is_directed_acyclic_graph(dep_subgraph):
        build_order = list(nx.topological_sort(dep_subgraph))
    else:
        build_order = list(upstream)

    return {
        "upstream": upstream,
        "downstream": downstream,
        "build_order": build_order,
        "dep_subgraph": dep_subgraph
    }
```

---

## 9. Deprecations and Removals

### 9.1 Removed in NetworkX 3.0

| Removed API | Replacement |
|------------|-------------|
| `write_gpickle(G, path)` | `pickle.dump(G, f, pickle.HIGHEST_PROTOCOL)` |
| `read_gpickle(path)` | `pickle.load(f)` |
| `to_numpy_matrix()` | `to_numpy_array()` (returns `numpy.ndarray`) |
| `from_numpy_matrix()` | `from_numpy_array()` |
| All `scipy.sparse.spmatrix` returns | Now return `scipy.sparse._sparray` |

### 9.2 Deprecated in NetworkX 3.4 (to be removed in 3.6)

| Deprecated | Replacement |
|-----------|-------------|
| `node_link_data(G, link="links")` | `node_link_data(G, edges="edges")` |
| `node_link_graph(data, link="links")` | `node_link_graph(data, edges="edges")` |

**Critical note:** If you call `node_link_data()` without specifying `edges=`, a `FutureWarning` is raised. The current default is `"links"` but will change to `"edges"` in 3.6. **Always pass `edges="edges"` explicitly** to be forward-compatible.

### 9.3 Migration from 2.x to 3.0 Summary

From the migration guide: "The focus of 3.0 release is on addressing years of technical debt, modernizing our codebase, improving performance, and making it easier to contribute."

Key changes:
- All NumPy matrix objects replaced with array objects
- All SciPy sparse matrix objects replaced with sparse array objects
- Pickle functions removed (use stdlib pickle)
- Various deprecated utility functions removed

### 9.4 Backend Dispatch (New in 3.x)

The `@nx._dispatchable` decorator is used throughout the codebase to enable backend dispatch. This is a new feature, not a deprecation, but is important to be aware of:
- Functions decorated with `@nx._dispatchable` can be dispatched to alternative backends
- The `backend=` keyword argument is available on these functions
- Edge attributes can be declared via `@nx._dispatchable(edge_attrs="weight")`

---

## Appendix A: Quick Reference -- Most Useful Functions for Graph RAG

| Category | Function | Signature | Returns |
|----------|----------|-----------|---------|
| **Context Extraction** | `ego_graph` | `ego_graph(G, n, radius=1, center=True, undirected=False, distance=None)` | Graph (copy) |
| **Context Extraction** | `subgraph` | `G.subgraph(nodes)` | Graph (view) |
| **Context Extraction** | `subgraph_view` | `subgraph_view(G, filter_node=, filter_edge=)` | Graph (read-only view) |
| **Pathfinding** | `shortest_path` | `shortest_path(G, source, target)` | list of nodes |
| **Pathfinding** | `all_simple_paths` | `all_simple_paths(G, source, target, cutoff=None)` | generator of lists |
| **Traversal** | `bfs_tree` | `bfs_tree(G, source, depth_limit=None)` | DiGraph |
| **Traversal** | `descendants` | `descendants(G, source)` | set of nodes |
| **Traversal** | `ancestors` | `ancestors(G, source)` | set of nodes |
| **Ranking** | `pagerank` | `pagerank(G, alpha=0.85)` | dict {node: score} |
| **Ranking** | `degree_centrality` | `degree_centrality(G)` | dict {node: score} |
| **Ranking** | `betweenness_centrality` | `betweenness_centrality(G, k=None, weight=None)` | dict {node: score} |
| **Clustering** | `louvain_communities` | `louvain_communities(G, resolution=1, seed=None)` | list of sets |
| **Structure** | `topological_sort` | `topological_sort(G)` | generator of nodes |
| **Structure** | `connected_components` | `connected_components(G)` | generator of sets |
| **Structure** | `strongly_connected_components` | `strongly_connected_components(G)` | generator of sets |
| **Structure** | `find_cycle` | `find_cycle(G, orientation=None)` | list of edges |
| **Serialization** | `node_link_data` | `node_link_data(G, edges="edges")` | dict |
| **Serialization** | `node_link_graph` | `node_link_graph(data, edges="edges")` | Graph |

## Appendix B: Graph RAG Architecture Sketch

```
                    User Query
                        |
                        v
              +------------------+
              |  Query Embedding |
              +------------------+
                        |
            +-----------+-----------+
            |                       |
            v                       v
    +---------------+      +----------------+
    | Vector Store  |      | NetworkX Graph |
    | (ChromaDB)    |      | (Structure)    |
    +---------------+      +----------------+
            |                       |
            v                       v
    Top-K Similar          ego_graph / ancestors /
    Nodes (semantic)       descendants / paths
            |                       |
            +-----------+-----------+
                        |
                        v
              +------------------+
              | Merge & Rank     |
              | (PageRank,       |
              |  distance,       |
              |  centrality)     |
              +------------------+
                        |
                        v
              +------------------+
              | Context Window   |
              | Assembly         |
              +------------------+
                        |
                        v
              +------------------+
              | LLM Generation   |
              +------------------+
```

---

*End of NetworkX Research Document*
