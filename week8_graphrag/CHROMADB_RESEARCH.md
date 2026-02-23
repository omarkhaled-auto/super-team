# ChromaDB Research Document -- Week 8: Graph RAG Exploration

> **Source:** Context7 documentation for `/chroma-core/chroma` (2235 code snippets, High reputation)
> **Date:** 2026-02-23
> **Purpose:** Exhaustive ChromaDB API reference for Graph RAG system design

---

## Table of Contents

1. [Client Initialization and Persistence](#1-client-initialization-and-persistence)
2. [Collection Design](#2-collection-design)
3. [Embedding Functions](#3-embedding-functions)
4. [Document Structure and CRUD Operations](#4-document-structure-and-crud-operations)
5. [Query Patterns](#5-query-patterns)
6. [Hybrid Search and Filtering](#6-hybrid-search-and-filtering)
7. [Multi-Collection Patterns](#7-multi-collection-patterns)
8. [Performance, Scaling, and Batch Operations](#8-performance-scaling-and-batch-operations)
9. [GraphRAG-Specific Patterns](#9-graphrag-specific-patterns)
10. [API Changes and Common Misconceptions](#10-api-changes-and-common-misconceptions)

---

## 1. Client Initialization and Persistence

ChromaDB provides **five** client types for different deployment scenarios.

### 1.1 Client Types

| Client | Purpose | Data Lifetime |
|--------|---------|---------------|
| `chromadb.Client()` | In-memory, testing/dev | Lost on exit |
| `chromadb.EphemeralClient()` | Explicit in-memory (same as Client) | Lost on exit |
| `chromadb.PersistentClient(path=...)` | Local disk persistence | Persisted to disk |
| `chromadb.HttpClient(host=..., port=...)` | Connects to remote Chroma server | Server-managed |
| `chromadb.AsyncHttpClient(host=..., port=...)` | Async version of HttpClient | Server-managed |
| `chromadb.CloudClient(tenant=..., database=..., api_key=...)` | Chroma Cloud | Cloud-managed |

### 1.2 Initialization Examples

```python
import chromadb

# 1. In-memory (testing/prototyping)
client = chromadb.Client()

# 2. Persistent (local development -- RECOMMENDED for Graph RAG dev)
client = chromadb.PersistentClient(path="./chroma_db")

# 3. HTTP client (production, connects to running Chroma server)
# Start server first: chroma run --path /db_path
client = chromadb.HttpClient(host="localhost", port=8000)

# 4. Async HTTP client
import asyncio
async def main():
    client = await chromadb.AsyncHttpClient(host="localhost", port=8000)
    collection = await client.create_collection("my_collection")
    await collection.add(documents=["hello world"], ids=["id1"])
asyncio.run(main())

# 5. Cloud client
client = chromadb.CloudClient(
    tenant="your-tenant-id",
    database="your-database",
    api_key="your-api-key"
)
# Or with environment variables (CHROMA_API_KEY, CHROMA_TENANT, CHROMA_DATABASE)
client = chromadb.CloudClient()
```

### 1.3 Client Utility Methods

```python
client.heartbeat()  # Check if server is alive
client.reset()      # Reset the database (DESTRUCTIVE)
```

### 1.4 PersistentClient Parameters

```python
# Full signature from docs:
chromadb.PersistentClient(
    path: Union[str, Path],    # Required -- directory for persisted data
    settings: Settings = None, # Optional -- from chromadb.config import Settings
    tenant: str = None,        # Optional
    database: str = None       # Optional
)
```

**Important note from docs:** PersistentClient is intended for **local development and testing**. For production, the docs recommend a server-backed Chroma instance (HttpClient).

### 1.5 Graph RAG Recommendation

For Graph RAG development:
- Use `PersistentClient` during development/testing so data survives restarts
- Use `HttpClient` or `CloudClient` for production deployments
- The `path` parameter for PersistentClient creates the directory if it doesn't exist; data is automatically saved and loaded from this path

---

## 2. Collection Design

### 2.1 Creating Collections

```python
# Basic creation -- raises ValueError if collection already exists
collection = client.create_collection(name="my_collection")

# Get or create -- idempotent, returns existing if present
collection = client.get_or_create_collection(name="my_collection")

# Get existing -- raises ValueError if not found
collection = client.get_collection(name="my_collection")
```

### 2.2 Collection Naming Constraints

From the docs, collection names have strict rules:

| Rule | Detail |
|------|--------|
| Length | Between 3 and 512 characters |
| Start/End | Must start and end with a lowercase letter or digit |
| Middle chars | Can contain dots (`.`), dashes (`-`), and underscores (`_`) |
| No double dots | Must NOT contain two consecutive dots (`..`) |
| No IP addresses | Must NOT be a valid IP address |
| Uniqueness | Must be unique within a Chroma database |

**Valid examples:** `graph-nodes`, `entity_embeddings`, `community.summaries`
**Invalid examples:** `My Collection` (uppercase, spaces), `ab` (too short), `192.168.1.1` (IP address)

### 2.3 Collection with Metadata

```python
collection = client.create_collection(
    name="my_collection",
    metadata={"description": "My first collection"}
)
```

**Note from docs:** For `get_or_create_collection`, if the collection already exists, the `metadata` parameter is **ignored**. New metadata is only applied when the collection is first created.

### 2.4 Collection with HNSW Configuration

```python
collection = client.create_collection(
    name="my-collection",
    embedding_function=some_ef,
    configuration={
        "hnsw": {
            "space": "cosine",       # Distance metric
            "ef_construction": 200   # Index build quality
        }
    }
)
```

### 2.5 Distance Metrics (Space Parameter)

| Space | Description | Default? | Best For |
|-------|-------------|----------|----------|
| `l2` | Squared L2 norm (Euclidean distance) | **Yes (default)** | Raw vector comparison |
| `cosine` | Cosine similarity | No | Text embeddings (most common for NLP) |
| `ip` | Inner product | No | Normalized embeddings, recommendation systems |

**Critical:** The `space` must be compatible with the embedding function. Each Chroma embedding function specifies its default space and supported spaces.

**For Graph RAG:** Use `cosine` for text-based node/edge embeddings since sentence transformer models typically produce embeddings optimized for cosine similarity.

### 2.6 Configuration Syntax (Current vs Legacy)

The docs show two patterns for setting HNSW space:

```python
# CURRENT recommended pattern (configuration dict)
collection = client.create_collection(
    name="my-collection",
    configuration={
        "hnsw": {
            "space": "cosine",
            "ef_construction": 200
        }
    }
)

# LEGACY pattern (metadata dict -- still appears in some examples)
collection = client.create_collection(
    name="images_db",
    metadata={"hnsw:space": "cosine"}
)
```

Both appear in the docs. The `configuration` dict is the newer, recommended approach.

### 2.7 Collection Lifecycle Management

```python
# Modify collection name and metadata
collection.modify(
    name="renamed_collection",
    metadata={"description": "Updated description", "version": 2}
)

# Get record count
count = collection.count()
print(f"Collection has {count} records")

# Peek at first records (useful for debugging)
sample = collection.peek()

# Delete collection (DESTRUCTIVE -- cannot be undone)
client.delete_collection(name="my_collection")
```

---

## 3. Embedding Functions

### 3.1 SentenceTransformerEmbeddingFunction

```python
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

sentence_transformer_ef = SentenceTransformerEmbeddingFunction(
    model_name="all-MiniLM-L6-v2",   # Default model
    device="cpu",                      # "cpu" or "cuda"
    normalize_embeddings=False         # Whether to L2-normalize
)

# Direct usage
texts = ["Hello, world!", "How are you?"]
embeddings = sentence_transformer_ef(texts)
```

### 3.2 Model Dimensions Reference

| Model | Dimensions | Quality | Speed |
|-------|-----------|---------|-------|
| `all-MiniLM-L6-v2` | **384** | Good (default) | Fast |
| `all-mpnet-base-v2` | **768** | Higher quality | Slower |
| `bge-small-en-v1.5` | **384** | Good | Fast |

### 3.3 Using Embedding Functions with Collections

```python
# Method 1: Pass as argument (recommended)
collection = client.create_collection(
    name="my_collection",
    embedding_function=SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    ),
    configuration={"hnsw": {"space": "cosine"}}
)

# Method 2: Set in configuration
from chromadb.utils.embedding_functions import CohereEmbeddingFunction

collection = client.get_or_create_collection(
    name="my_cohere_collection",
    configuration={
        "embedding_function": CohereEmbeddingFunction(
            model_name="embed-english-light-v2.0",
            truncate="NONE"
        ),
        "hnsw": {"space": "cosine"}
    }
)
```

### 3.4 Custom Embedding Functions

```python
from typing import Dict, Any
from chromadb import Documents, EmbeddingFunction, Embeddings
from chromadb.utils.embedding_functions import register_embedding_function

@register_embedding_function
class MyCustomEmbeddingFunction(EmbeddingFunction):
    def __init__(self, model_name: str, api_key: str):
        self.model_name = model_name
        self.api_key = api_key

    def __call__(self, input: Documents) -> Embeddings:
        # Generate embeddings for the input documents
        embeddings = []
        for doc in input:
            embedding = [0.1] * 384  # Replace with actual logic
            embeddings.append(embedding)
        return embeddings

    @staticmethod
    def name() -> str:
        return "my-custom-ef"

    def get_config(self) -> Dict[str, Any]:
        return {"model_name": self.model_name}

    @staticmethod
    def build_from_config(config: Dict[str, Any]) -> "EmbeddingFunction":
        return MyCustomEmbeddingFunction(
            model_name=config["model_name"],
            api_key=""
        )

# Usage
client = chromadb.Client()
collection = client.create_collection(
    name="custom_embeddings",
    embedding_function=MyCustomEmbeddingFunction(
        model_name="my-model",
        api_key="my-api-key"
    )
)
```

### 3.5 Important: Embedding Function Persistence

When you retrieve a collection with `get_collection()`, you **must** pass the same embedding function again -- ChromaDB does not store the embedding function object itself:

```python
# CORRECT: Pass the same EF when retrieving
collection = client.get_collection(
    name="my_collection",
    embedding_function=SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
)

# If you don't pass it, ChromaDB uses a default embedding function,
# which may produce different embeddings and give incorrect results
```

### 3.6 Graph RAG Embedding Strategy

For Graph RAG, consider:
- **One embedding function per collection** -- each collection is bound to one EF
- If you need different embedding dimensions for different data types (e.g., node descriptions vs. community summaries), use separate collections with different EFs
- `all-MiniLM-L6-v2` (384 dims) is a solid default for text embeddings of node descriptions and summaries

---

## 4. Document Structure and CRUD Operations

### 4.1 The Chroma Record Model

Each record in a collection consists of:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `str` | **Yes** | Unique identifier for the record |
| `embedding` | `list[float]` | No* | Vector embedding |
| `document` | `str` | No* | Text content (auto-embedded if no embedding provided) |
| `metadata` | `dict` | No | Key-value metadata |
| `uri` | `str` | No | URI reference |

*Either `embedding` or `document` must be provided so ChromaDB can produce an embedding.

### 4.2 Adding Records

```python
collection.add(
    ids=["id1", "id2", "id3"],
    documents=["Document 1 text", "Document 2 text", "Document 3 text"],
    metadatas=[
        {"source": "wiki", "page": 1},
        {"source": "arxiv", "page": 5},
        {"source": "wiki", "page": 12}
    ]
    # embeddings are auto-generated from documents via the collection's EF
)

# Or with pre-computed embeddings (bypasses the embedding function)
collection.add(
    ids=["id1", "id2"],
    embeddings=[[1.1, 2.3, ...], [4.5, 6.7, ...]],
    metadatas=[{"source": "doc1"}, {"source": "doc2"}],
    documents=["This is document 1", "This is document 2"]
)
```

### 4.3 ID Constraints

- IDs are **strings** (not integers)
- IDs must be **unique** within a collection
- Duplicate IDs in an `add()` call will raise an error
- No documented maximum length, but they should be reasonable strings

### 4.4 Metadata Value Types

From the docs, metadata values can be:

| Type | Example | Filterable |
|------|---------|------------|
| `str` | `"electronics"` | Yes |
| `int` | `42` | Yes |
| `float` | `3.14` | Yes |
| `bool` | `True` | Yes |
| `list[str]` | `["action", "comedy"]` | Yes (with `$contains`) |
| `list[int]` | `[1, 2, 3]` | Yes (with `$contains`) |
| `list[float]` | `[4.5, 3.8]` | Yes (with `$contains`) |
| `list[bool]` | `[True, False]` | Yes (with `$contains`) |

**Constraints on arrays:**
- All elements in an array must be the **same type**
- **Empty arrays are NOT allowed**

```python
collection.add(
    ids=["id1"],
    documents=["lorem ipsum..."],
    metadatas=[
        {
            "chapter": 3,                          # int
            "tags": ["fiction", "adventure"],       # list[str]
            "scores": [1, 2, 3],                   # list[int]
        },
    ],
)
```

### 4.5 Upsert (Insert or Update)

```python
# Creates if ID doesn't exist, updates if it does
collection.upsert(
    ids=["id1", "id2"],
    documents=["Updated document 1", "New document 2"],
    metadatas=[{"key": "value"}, {"key": "value"}]
)
```

**When to use upsert vs add:**
- `add()` -- when you know IDs are new; raises error on duplicate
- `upsert()` -- when IDs might already exist; idempotent and safe for re-processing

**For Graph RAG:** `upsert()` is preferred when rebuilding graph indices, since nodes/edges may be updated during graph construction.

### 4.6 Update

```python
# Updates EXISTING records only; does nothing for non-existent IDs
collection.update(
    ids=["doc1"],
    embeddings=[[9.8, 7.6, ...]],
    metadatas=[{"status": "updated"}]
)
```

### 4.7 Delete

```python
# Delete by IDs
collection.delete(ids=["id1"])

# Delete by metadata filter
collection.delete(where={"key": "value"})

# Delete by document content filter
collection.delete(where_document={"$contains": "search term"})
```

**Important:** A `ValueError` is raised if no deletion criteria (ids, where, or where_document) are specified.

---

## 5. Query Patterns

### 5.1 Similarity Search with `query()`

```python
results = collection.query(
    query_texts=["thus spake zarathustra", "the oracle speaks"],  # Auto-embedded
    n_results=100,                                                 # Default: 10
    where={"page": 10},                                           # Metadata filter
    where_document={"$contains": "search string"}                 # Document filter
)
```

### 5.2 Full Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query_texts` | `list[str]` | No* | - | Text strings to embed and query |
| `query_embeddings` | `list[list[float]]` | No* | - | Pre-computed embedding vectors |
| `n_results` | `int` | No | **10** | Number of results per query input |
| `where` | `dict` | No | - | Metadata filter |
| `where_document` | `dict` | No | - | Document content filter |
| `ids` | `list[str]` | No | - | Constrain search to these IDs |
| `include` | `list[str]` | No | See below | Fields to include in results |

*One of `query_texts` or `query_embeddings` must be provided.

### 5.3 The `include` Parameter

Controls which fields are returned in results.

**Default for `query()`:** `["documents", "metadatas", "distances"]`
**Default for `get()`:** `["documents", "metadatas"]`

Available values: `"documents"`, `"metadatas"`, `"embeddings"`, `"distances"`

The `ids` field is **always returned** regardless of the `include` parameter.

```python
# Query with specific includes
collection.query(
    query_texts=["my query"],
    include=["documents", "metadatas", "embeddings", "distances"]
)

# Get with specific includes
collection.get(include=["documents"])
```

**Note:** `"distances"` is only valid for `query()`, not for `get()`.

### 5.4 Query Result Structure

Results from `query()` return nested lists (because you can query multiple texts at once):

```python
{
    "ids": [["doc1", "doc3"]],           # list[list[str]]
    "documents": [["text1", "text3"]],   # list[list[str]]
    "distances": [[0.1, 0.3]],           # list[list[float]]
    "metadatas": [[{"k": "v"}, {"k": "v2"}]]  # list[list[dict]]
}
```

The outer list corresponds to each query input; the inner list corresponds to results for that query.

### 5.5 Retrieval with `get()`

`get()` does NOT perform similarity ranking -- it retrieves by ID or filter.

```python
# By IDs
results = collection.get(ids=["id1", "id2"])

# With pagination
results = collection.get(limit=100, offset=0)

# With filters
results = collection.get(
    ids=["doc1", "doc2"],
    where={"source": "doc1"},
    limit=10,
    offset=0,
    include=["metadatas", "documents"]
)
```

### 5.6 Metadata Filter Operators

#### Direct Equality (Shorthand)

```python
where={"category": "electronics"}
```

#### Explicit Operators

| Operator | Description | Example |
|----------|-------------|---------|
| `$eq` | Equal | `{"category": {"$eq": "electronics"}}` |
| `$ne` | Not equal | `{"category": {"$ne": "draft"}}` |
| `$gt` | Greater than | `{"price": {"$gt": 100}}` |
| `$gte` | Greater than or equal | `{"price": {"$gte": 100}}` |
| `$lt` | Less than | `{"price": {"$lt": 500}}` |
| `$lte` | Less than or equal | `{"price": {"$lte": 500}}` |
| `$in` | In set | `{"category": {"$in": ["tech", "science"]}}` |
| `$nin` | Not in set | `{"category": {"$nin": ["draft", "deleted"]}}` |
| `$contains` | Array contains value | `{"tags": {"$contains": "action"}}` |
| `$not_contains` | Array does not contain | `{"tags": {"$not_contains": "draft"}}` |

#### Logical Operators

```python
# AND -- all conditions must match
where={
    "$and": [
        {"category": "electronics"},
        {"price": {"$gte": 500}},
        {"price": {"$lte": 1000}}
    ]
}

# OR -- any condition must match
where={
    "$or": [
        {"category": "electronics"},
        {"category": "wearables"}
    ]
}
```

### 5.7 Document Content Filtering (`where_document`)

| Operator | Description | Example |
|----------|-------------|---------|
| `$contains` | Substring match | `{"$contains": "machine learning"}` |
| `$not_contains` | Does not contain substring | `{"$not_contains": "draft"}` |
| `$regex` | Regex pattern match | `{"$regex": "quantum\\s+\\w+"}` |
| `$not_regex` | Does not match regex | `{"$not_regex": "^draft"}` |

**Full-text search is case-sensitive.**

```python
# Combine document filters with logical operators
collection.query(
    query_texts=["query1"],
    where_document={
        "$and": [
            {"$contains": "machine learning"},
            {"$regex": "[a-z]+"},
        ]
    }
)

# Combine with metadata filters
collection.query(
    query_texts=["doc10"],
    n_results=10,
    where={"metadata_field": "is_equal_to_this"},
    where_document={"$contains": "search_string"}
)
```

**Note on syntax:** The docs show a JSON-style format for `where_document` with `"#document"` key in the reference, but the Python API uses the simpler dict format shown above.

---

## 6. Hybrid Search and Filtering

### 6.1 Combining Semantic Search with Metadata Filters

This is ChromaDB's most powerful pattern for Graph RAG:

```python
# Pattern: "Find documents similar to X, but only from service Y"
results = collection.query(
    query_texts=["portable device"],
    where={"category": "electronics"},  # Pre-filter by metadata
    n_results=5
)
```

### 6.2 Range Queries on Numeric Metadata

```python
# Price range query
results = collection.query(
    query_texts=["affordable device"],
    where={
        "$and": [
            {"price": {"$gte": 500}},
            {"price": {"$lte": 1000}}
        ]
    }
)
```

### 6.3 Graph RAG Filtering Pattern

```python
# Find nodes similar to a query, but only within a specific community
results = collection.query(
    query_texts=["machine learning research"],
    where={
        "$and": [
            {"node_type": "entity"},
            {"community_id": {"$in": [1, 2, 3]}}  # Target communities
        ]
    },
    n_results=10,
    include=["documents", "metadatas", "distances"]
)
```

### 6.4 New Search API (Advanced -- Chroma Cloud / Newer Versions)

ChromaDB has introduced a newer `Search` API with expression-based queries:

```python
from chromadb import Search, K, Knn, Rrf

# Basic search with KNN ranking and filtering
search = (
    Search()
    .where(K("category") == "science")
    .rank(Knn(query="quantum computing advances"))
    .limit(10)
    .select(K.DOCUMENT, K.SCORE, "title")
)
results = collection.search(search)

# Hybrid search with Reciprocal Rank Fusion
dense_rank = Knn(
    query="machine learning research",
    key="#embedding",           # Default embedding field
    return_rank=True,
    limit=200
)
sparse_rank = Knn(
    query="machine learning research",
    key="sparse_embedding",     # Separate sparse embedding field
    return_rank=True,
    limit=200
)
hybrid_rank = Rrf(
    [dense_rank, sparse_rank],
    weights=[0.7, 0.3],        # 70% semantic, 30% keyword
    k=60
)
search = (
    Search()
    .where(K("status") == "published")
    .rank(hybrid_rank)
    .limit(20)
    .select(K.DOCUMENT, K.SCORE, "title")
)
results = collection.search(search)
```

**Note:** The `Search` API with `K`, `Knn`, and `Rrf` appears to be primarily documented for **Chroma Cloud**. Availability in the local PersistentClient may vary by version. The traditional `collection.query()` API remains the standard for local usage.

### 6.5 Pre-filter vs. Post-filter Behavior

The docs do not explicitly document whether ChromaDB applies filters before or after the ANN search. However, based on the API behavior:
- `where` and `where_document` filters in `query()` effectively **pre-filter** the candidate set before ranking by similarity
- This means fewer results may be returned than `n_results` if few documents match the filter

---

## 7. Multi-Collection Patterns

### 7.1 When to Use Single vs. Multiple Collections

From the official documentation:

**Use a SINGLE collection when:**
- Using the same embedding model for all data
- Want to search across everything at once
- Can distinguish between records using metadata filtering

**Use MULTIPLE collections when:**
- Different data types require different embedding models
- Multi-tenant requirements (collection per user/org helps avoid filtering overhead)
- Data is fundamentally different in nature

### 7.2 Cross-Collection Queries

ChromaDB does **NOT** natively support cross-collection queries. If you need to search across multiple collections, you must implement this at the **application level**:

```python
# Application-level cross-collection search
collections = [
    client.get_collection("entities"),
    client.get_collection("communities"),
    client.get_collection("relationships")
]

all_results = []
for coll in collections:
    results = coll.query(
        query_texts=["machine learning"],
        n_results=5
    )
    all_results.append(results)

# Merge and re-rank results at application level
```

### 7.3 Graph RAG Multi-Collection Design

For Graph RAG, a practical design pattern:

```python
# Option A: Multiple collections (different embedding needs)
entities_collection = client.get_or_create_collection(
    name="graph-entities",
    embedding_function=sentence_transformer_ef,
    configuration={"hnsw": {"space": "cosine"}}
)

community_summaries_collection = client.get_or_create_collection(
    name="graph-communities",
    embedding_function=sentence_transformer_ef,
    configuration={"hnsw": {"space": "cosine"}}
)

# Option B: Single collection with metadata type field (simpler)
graph_collection = client.get_or_create_collection(
    name="graph-data",
    embedding_function=sentence_transformer_ef,
    configuration={"hnsw": {"space": "cosine"}}
)

# Add entities
graph_collection.add(
    ids=["entity_1", "entity_2"],
    documents=["Machine learning is a subset of AI...", "Neural networks process..."],
    metadatas=[
        {"type": "entity", "entity_name": "Machine Learning", "community_id": 1},
        {"type": "entity", "entity_name": "Neural Networks", "community_id": 1}
    ]
)

# Add community summaries
graph_collection.add(
    ids=["community_1"],
    documents=["This community covers AI and ML topics including..."],
    metadatas=[
        {"type": "community_summary", "community_id": 1, "level": 0}
    ]
)

# Query only entities
results = graph_collection.query(
    query_texts=["deep learning applications"],
    where={"type": "entity"},
    n_results=10
)

# Query only community summaries
results = graph_collection.query(
    query_texts=["AI research overview"],
    where={"type": "community_summary"},
    n_results=5
)
```

### 7.4 Tradeoffs Summary

| Approach | Pros | Cons |
|----------|------|------|
| Single collection + metadata filters | Simpler code, single query path | Larger index, filter overhead |
| Multiple collections | Cleaner separation, independent configs | No native cross-collection query, more code |

### 7.5 Collection Organization

Collections are organized into **databases** which function as logical namespaces:

```
Database (logical namespace)
  |-- Collection A (unique name within database)
  |-- Collection B
  |-- Collection C
```

Useful for separating staging vs. production, or different applications.

---

## 8. Performance, Scaling, and Batch Operations

### 8.1 Batch Add Operations

**Recommended batch size: 300 records per batch call.**

```python
# BAD: Adding one record at a time
for chunk in chunks:
    collection.add(
        ids=[chunk.id],
        documents=[chunk.document],
        metadatas=[chunk.metadata]
    )

# GOOD: Batch adding
BATCH_SIZE = 300
for i in range(0, len(chunks), BATCH_SIZE):
    batch = chunks[i:i + BATCH_SIZE]
    collection.add(
        ids=[chunk.id for chunk in batch],
        documents=[chunk.document for chunk in batch],
        metadatas=[chunk.metadata for chunk in batch]
    )
```

### 8.2 Batch Search Operations

```python
# BAD: Sequential queries
results = []
for search in searches:
    result = collection.search(search)
    results.append(result)

# GOOD: Batch queries (single API call)
results = collection.search(searches)  # Pass list of Search objects
```

### 8.3 Multiple Searches in One Call (New Search API)

```python
from chromadb import Search, K, Knn

searches = [
    (Search()
        .where((K("type") == "article") & (K("year") >= 2024))
        .rank(Knn(query="machine learning applications"))
        .limit(5)
        .select(K.DOCUMENT, K.SCORE, "title")),

    (Search()
        .where(K("author").is_in(["Smith", "Jones"]))
        .rank(Knn(query="neural network research"))
        .limit(10)
        .select(K.DOCUMENT, K.SCORE, "title", "author")),
]

results = collection.search(searches)
```

### 8.4 Performance Best Practices

From the docs:

| Practice | Detail |
|----------|--------|
| Batch adds | Use batches of ~300 records |
| Batch queries | Combine multiple queries into one call |
| Consistent `select` fields | Across batch searches for simpler processing |
| Memory awareness | Be careful with `select_all()` on large batches |
| Result ordering | Batch results maintain input order |

### 8.5 HNSW Tuning for Performance

```python
collection = client.create_collection(
    name="my-collection",
    configuration={
        "hnsw": {
            "space": "cosine",
            "ef_construction": 200  # Higher = better index quality, slower build
        }
    }
)
```

- **`ef_construction`**: Higher values build a better quality index but take longer. Default is typically 100-200. For Graph RAG with moderate dataset sizes (< 100K nodes), the default is fine.

### 8.6 Scaling Considerations

The docs note:
- **PersistentClient** stores data on disk; in distributed setups, collections can be sharded across nodes
- The system automatically manages collection presence in memory based on access patterns
- For very large datasets, a server-backed deployment (HttpClient) is recommended over PersistentClient
- No explicit documented hard limit on documents per collection, but performance degrades with very large collections

---

## 9. GraphRAG-Specific Patterns

### 9.1 Context7 Coverage

**Context7 does NOT have specific Graph RAG documentation for ChromaDB.** The patterns below are synthesized from ChromaDB's general capabilities as applied to Graph RAG architecture. ChromaDB's docs focus on standard RAG pipelines (Haystack, LangChain, etc.) but do not document Graph RAG patterns natively.

### 9.2 Storing Graph Nodes as Embeddings

```python
import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

ef = SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")

client = chromadb.PersistentClient(path="./graphrag_db")

# Collection for entity nodes
entities = client.get_or_create_collection(
    name="graph-entities",
    embedding_function=ef,
    configuration={"hnsw": {"space": "cosine"}}
)

# Add entity nodes with graph metadata
entities.upsert(
    ids=["entity_ml", "entity_dl", "entity_nn"],
    documents=[
        "Machine Learning: A field of AI that enables computers to learn from data",
        "Deep Learning: A subset of ML using neural networks with many layers",
        "Neural Networks: Computing systems inspired by biological neural networks"
    ],
    metadatas=[
        {
            "entity_name": "Machine Learning",
            "entity_type": "CONCEPT",
            "community_id": 1,
            "level": 0,
            "degree": 15,           # Number of connections
            "source_doc_ids": ["doc1", "doc2", "doc3"],
        },
        {
            "entity_name": "Deep Learning",
            "entity_type": "CONCEPT",
            "community_id": 1,
            "level": 0,
            "degree": 12,
            "source_doc_ids": ["doc2", "doc4"],
        },
        {
            "entity_name": "Neural Networks",
            "entity_type": "CONCEPT",
            "community_id": 1,
            "level": 0,
            "degree": 20,
            "source_doc_ids": ["doc1", "doc5"],
        }
    ]
)
```

### 9.3 Storing Community Summaries

```python
communities = client.get_or_create_collection(
    name="graph-communities",
    embedding_function=ef,
    configuration={"hnsw": {"space": "cosine"}}
)

communities.upsert(
    ids=["community_1_L0", "community_2_L0", "community_1_L1"],
    documents=[
        "Community 1 (Level 0): This community focuses on artificial intelligence concepts including machine learning, deep learning, and neural networks. Key entities include...",
        "Community 2 (Level 0): This community covers data engineering and processing pipelines including ETL, data lakes, and stream processing...",
        "Community 1 (Level 1): This higher-level community encompasses all of computer science and technology, including AI, data engineering, and software development..."
    ],
    metadatas=[
        {"community_id": 1, "level": 0, "node_count": 25, "edge_count": 48},
        {"community_id": 2, "level": 0, "node_count": 18, "edge_count": 30},
        {"community_id": 1, "level": 1, "node_count": 50, "edge_count": 95},
    ]
)
```

### 9.4 Storing Relationship/Edge Information

```python
relationships = client.get_or_create_collection(
    name="graph-relationships",
    embedding_function=ef,
    configuration={"hnsw": {"space": "cosine"}}
)

relationships.upsert(
    ids=["rel_ml_dl", "rel_dl_nn"],
    documents=[
        "Machine Learning IS_PARENT_OF Deep Learning: Deep learning is a specialized subset of machine learning that uses multi-layered neural networks",
        "Deep Learning USES Neural Networks: Deep learning systems are built upon neural network architectures with multiple hidden layers"
    ],
    metadatas=[
        {
            "source_entity": "Machine Learning",
            "target_entity": "Deep Learning",
            "relationship_type": "IS_PARENT_OF",
            "weight": 0.95,
            "source_doc_id": "doc2"
        },
        {
            "source_entity": "Deep Learning",
            "target_entity": "Neural Networks",
            "relationship_type": "USES",
            "weight": 0.88,
            "source_doc_id": "doc4"
        }
    ]
)
```

### 9.5 Graph RAG Query Patterns

#### Local Search (Entity-Focused)

```python
def local_search(query: str, n_results: int = 10):
    """Find relevant entities and their relationships."""
    # Step 1: Find relevant entities
    entity_results = entities.query(
        query_texts=[query],
        n_results=n_results,
        include=["documents", "metadatas", "distances"]
    )

    # Step 2: Get relationships for found entities
    entity_names = [m["entity_name"] for m in entity_results["metadatas"][0]]

    related_rels = []
    for name in entity_names:
        rels = relationships.query(
            query_texts=[query],
            where={
                "$or": [
                    {"source_entity": name},
                    {"target_entity": name}
                ]
            },
            n_results=5,
            include=["documents", "metadatas"]
        )
        related_rels.append(rels)

    return entity_results, related_rels
```

#### Global Search (Community-Focused)

```python
def global_search(query: str, level: int = 0, n_results: int = 5):
    """Search community summaries for broad questions."""
    results = communities.query(
        query_texts=[query],
        where={"level": level},
        n_results=n_results,
        include=["documents", "metadatas", "distances"]
    )
    return results
```

#### Neighborhood Retrieval

```python
def get_entity_neighborhood(entity_name: str):
    """Get all entities connected to a given entity."""
    # Find relationships where entity is source or target
    outgoing = relationships.get(
        where={"source_entity": entity_name},
        include=["documents", "metadatas"]
    )
    incoming = relationships.get(
        where={"target_entity": entity_name},
        include=["documents", "metadatas"]
    )

    # Collect neighbor entity names
    neighbor_names = set()
    for m in outgoing["metadatas"]:
        neighbor_names.add(m["target_entity"])
    for m in incoming["metadatas"]:
        neighbor_names.add(m["source_entity"])

    # Fetch neighbor entity details
    if neighbor_names:
        neighbors = entities.get(
            where={"entity_name": {"$in": list(neighbor_names)}},
            include=["documents", "metadatas"]
        )
        return neighbors
    return {"ids": [], "documents": [], "metadatas": []}
```

### 9.6 Single-Collection Graph RAG Alternative

If preferring a single collection (simpler, fewer API calls):

```python
graph_store = client.get_or_create_collection(
    name="graphrag-unified",
    embedding_function=ef,
    configuration={"hnsw": {"space": "cosine"}}
)

# Add all types with a "record_type" metadata field
graph_store.upsert(
    ids=["entity_ml", "rel_ml_dl", "community_1"],
    documents=[
        "Machine Learning: A field of AI...",
        "Machine Learning IS_PARENT_OF Deep Learning...",
        "Community 1 summary: AI and ML concepts..."
    ],
    metadatas=[
        {"record_type": "entity", "entity_name": "Machine Learning", "community_id": 1},
        {"record_type": "relationship", "source_entity": "Machine Learning", "target_entity": "Deep Learning"},
        {"record_type": "community", "community_id": 1, "level": 0}
    ]
)

# Query entities only
graph_store.query(
    query_texts=["deep learning"],
    where={"record_type": "entity"},
    n_results=10
)

# Query communities only
graph_store.query(
    query_texts=["AI overview"],
    where={"record_type": "community"},
    n_results=5
)
```

---

## 10. API Changes and Common Misconceptions

### 10.1 Key API Changes (from older versions)

| Old Pattern | Current Pattern | Notes |
|------------|-----------------|-------|
| `chromadb.Client(Settings(persist_directory="..."))` | `chromadb.PersistentClient(path="...")` | Simplified persistence |
| `client.persist()` | Not needed | PersistentClient auto-persists |
| `metadata={"hnsw:space": "cosine"}` | `configuration={"hnsw": {"space": "cosine"}}` | New configuration dict |
| N/A | `chromadb.CloudClient(...)` | New cloud client type |
| N/A | `chromadb.AsyncHttpClient(...)` | New async client type |
| N/A | `@register_embedding_function` decorator | New EF registration system |
| N/A | `Search()`, `K()`, `Knn()`, `Rrf()` | New Search API (Cloud) |

### 10.2 Common Misconceptions

1. **"ChromaDB stores the embedding function"** -- FALSE. You must pass the same embedding function every time you retrieve a collection with `get_collection()`. ChromaDB only stores the data, not the function object.

2. **"Empty arrays work in metadata"** -- FALSE. Empty arrays (`[]`) are not allowed in metadata values.

3. **"Metadata supports nested dicts"** -- NOT DOCUMENTED. The docs only show flat key-value metadata with scalar types and typed arrays. Nested dictionaries are not mentioned as supported.

4. **"Query always returns n_results items"** -- NOT GUARANTEED. If metadata/document filters are applied, fewer results may be returned if insufficient documents match the filter criteria.

5. **"get() returns distances"** -- FALSE. The `distances` include field is only valid for `query()`, not `get()`.

6. **"Cross-collection queries are supported"** -- FALSE. There is no native cross-collection query mechanism. This must be implemented at the application level.

7. **"PersistentClient is production-ready"** -- CAUTIONED. The docs explicitly state PersistentClient is for local development and testing; server-backed instances are recommended for production.

8. **"l2 is the best distance metric"** -- MISLEADING. While `l2` is the **default**, `cosine` is almost always better for text embeddings from sentence transformer models.

### 10.3 Things Context7 Did NOT Cover

The following topics were queried but had **no specific documentation** in Context7:

- **Exact document limits per collection** -- no hard limit documented
- **Query latency scaling characteristics** -- no benchmarks in docs
- **Maximum batch add size** -- docs recommend 300 per batch but don't state a hard limit
- **Memory behavior of PersistentClient** -- not explicitly documented how much is kept in RAM vs disk
- **Native Graph RAG patterns** -- ChromaDB docs have no Graph RAG-specific documentation; all patterns must be built from general-purpose APIs
- **Pre-filter vs post-filter mechanics** -- not explicitly documented

---

## Appendix A: Quick Reference Card

### Initialization

```python
import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

client = chromadb.PersistentClient(path="./chroma_db")
ef = SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
collection = client.get_or_create_collection(
    name="my-collection",
    embedding_function=ef,
    configuration={"hnsw": {"space": "cosine"}}
)
```

### CRUD

```python
# Create
collection.add(ids=["id1"], documents=["text"], metadatas=[{"k": "v"}])

# Read
collection.get(ids=["id1"])
collection.query(query_texts=["search"], n_results=5, where={"k": "v"})

# Update
collection.update(ids=["id1"], metadatas=[{"k": "v2"}])

# Upsert (create or update)
collection.upsert(ids=["id1"], documents=["new text"], metadatas=[{"k": "v2"}])

# Delete
collection.delete(ids=["id1"])
collection.delete(where={"k": "v"})
```

### Filter Operators

```python
# Comparison: $eq, $ne, $gt, $gte, $lt, $lte
# Set: $in, $nin
# Array: $contains, $not_contains
# Logical: $and, $or
# Document: $contains, $not_contains, $regex, $not_regex
```

### Collection Info

```python
collection.count()      # Number of records
collection.peek()       # Sample records
collection.name         # Collection name
collection.metadata     # Collection metadata
```

---

## Appendix B: Graph RAG Collection Schema Reference

### Recommended Schema for Graph RAG

```
Collection: graph-entities
  - id: "entity_{hash}"
  - document: Entity description text (embedded)
  - metadata:
      entity_name: str
      entity_type: str (PERSON, ORG, CONCEPT, etc.)
      community_id: int
      level: int
      degree: int
      source_doc_ids: list[str]

Collection: graph-relationships
  - id: "rel_{source}_{target}_{type}"
  - document: Relationship description text (embedded)
  - metadata:
      source_entity: str
      target_entity: str
      relationship_type: str
      weight: float
      source_doc_id: str

Collection: graph-communities
  - id: "community_{id}_L{level}"
  - document: Community summary text (embedded)
  - metadata:
      community_id: int
      level: int
      node_count: int
      edge_count: int
```
