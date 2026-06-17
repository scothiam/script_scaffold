# base

Reusable Python building blocks for automation scripts that track, search, and store structured data. Provides database setup, ORM models, repositories, RSS crawling, web search integrations, and general utilities — all designed to be imported and extended by application code.

## Requirements

```
pip install -r requirements.txt
```

| Package | Required | Purpose |
|---|---|---|
| `SQLAlchemy>=2.0` | Yes | ORM and database sessions |
| `feedparser>=6.0` | For RSS crawling | Parses RSS/Atom feeds |
| `openai>=1.0` | For AI chat calls | `ai_chat()` in `search.py` (works against any OpenAI-compatible endpoint, not just OpenAI) |
| `tavily-python>=0.3` | For Tavily search | `tavily_search()` in `search.py` |
| `duckduckgo-search>=5.0` | For DDG search | `ddg_search()` in `search.py` |
| `langchain-openai>=0.1` | For LangChain + OpenAI | `get_llm()` in `llm.py` |
| `langchain-anthropic>=0.1` | For LangChain + Anthropic | `get_llm()` in `llm.py` |
| `langchain-ollama>=0.1` | For LangChain + Ollama | `get_llm()` in `llm.py` |

Optional integrations degrade gracefully — if a package is not installed or an API key is unset, the relevant function returns an empty result or `None` instead of raising. For `llm.py`, a missing LangChain package raises `SystemExit` with an install hint rather than silently failing, since structured-output pipelines cannot continue without the provider.

---

## Modules

### `db.py` — Database setup

Utilities for creating a SQLite engine, session factory, and transactional session scope.

```python
from pathlib import Path
from base.db import make_engine, make_session_factory, session_scope, init_tables
from base.models import Base

engine = make_engine(Path("data/myapp.db"))
SessionFactory = make_session_factory(engine)
init_tables(engine, Base)

def get_session():
    return session_scope(SessionFactory)
```

`session_scope` is a context manager that commits on exit and rolls back on exception.

---

### `models.py` — ORM base and mixins

```python
from base.models import Base, PinnableMixin
```

- **`Base`** — SQLAlchemy `DeclarativeBase`. Inherit from it for all app models.
- **`PinnableMixin`** — Adds `is_pinned`, `created_at`, and `updated_at` columns to any model.

```python
from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from base.models import Base, PinnableMixin

class Widget(PinnableMixin, Base):
    __tablename__ = "widgets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
```

---

### `repository.py` — Generic CRUD repository

`BaseRepository` provides standard read/write operations. Subclasses supply a session factory and the model class.

```python
from base.repository import BaseRepository

class WidgetRepository(BaseRepository):
    def __init__(self):
        super().__init__(get_session, Widget)

repo = WidgetRepository()
repo.save(Widget(name="Sprocket"))
all_widgets = repo.all()
repo.update_by_id(1, name="Updated")
repo.delete_by_id(1)
repo.set_pinned(2, True)
```

Available methods: `all()`, `find_by_id()`, `save()`, `update_by_id()`, `delete_by_id()`, `set_pinned()`.

---

### `lookup.py` — Entity validation

`EntityLookup` is a base class for validating named entities before they are persisted. Subclass it and implement `lookup()`.

```python
from base.lookup import EntityLookup, LookupResult

class WidgetLookup(EntityLookup):
    _KNOWN = {"sprocket": "Sprocket", "cog": "Cog Wheel"}

    def lookup(self, query: str) -> LookupResult:
        key = self.fingerprint(query)
        if key in self._KNOWN:
            return LookupResult(found=True, canonical_name=self._KNOWN[key])
        suggestions = [
            LookupResult(found=True, canonical_name=v)
            for k, v in self._KNOWN.items()
            if self.token_similarity(query, k) > 0.4
        ]
        return LookupResult(found=False, suggestions=suggestions)
```

Static helpers on `EntityLookup`:
- `normalize(s)` — lowercase, collapse whitespace.
- `fingerprint(s)` — strip all non-alphanumeric characters and lowercase. `"RTX 3060 Ti"` and `"rtx-3060-ti"` both become `"rtx3060ti"`.
- `token_similarity(a, b)` — Jaccard similarity of whitespace-delimited tokens (0.0–1.0).

---

### `sources.py` — Source and SourceItem models

ORM models for tracking content sources (feeds, pages, APIs) and the items fetched from them.

```python
from base.sources import Source, SourceItem
```

**`Source`** columns:

| Column | Purpose |
|---|---|
| `scope` | App-defined category (`"general"`, `"stock"`, etc.) |
| `scope_value` | Narrows scope to a specific entity key; `None` = applies to all |
| `quality` | App-defined quality tier (`"trusted_news"`, `"community"`, etc.) |
| `domain` | Hostname of the source |
| `url` | Feed or page URL |
| `fetch_method` | `"rss"` \| `"html"` \| `"api"` |
| `is_active` | Set to `False` when a feed returns HTTP 4xx |
| `discovered_by` | `"seeded"` \| `"manual"` \| `"auto"` |

**`SourceItem`** columns: `item_url` (unique), `title`, `summary`, `content_hash`, `published_at`, `fetched_at`, `is_processed`.

---

### `source_repository.py` — Source and SourceItem queries

```python
from base.source_repository import SourceRepository, domain_from_url

repo = SourceRepository(get_session)

# Query
sources = repo.by_scope("general")
active = repo.active_crawlable(scopes=["general"], fetch_methods=["rss"])

# Write
repo.save(Source(scope="general", quality="community", domain="example.com",
                 url="https://example.com/feed", fetch_method="rss", discovered_by="seeded"))
repo.set_active(source_id, False)

# Items
items = repo.recent_items(source_ids=[1, 2], cutoff_days=7)
hits  = repo.items_mentioning(source_ids=[1, 2], terms=["widget", "gadget"])
```

---

### `rss_crawler.py` — RSS/Atom feed crawler

Fetches feeds and upserts items into the database. Deduplicates by URL; detects content changes via SHA-256 hash; marks sources inactive on persistent HTTP errors.

```python
from base.rss_crawler import crawl_sources

summary = crawl_sources(sources, get_session)
# {"sources_crawled": 3, "new_items": 12, "updated_items": 1, "errors": 0}
```

To crawl a single source inside an existing session:

```python
from base.rss_crawler import crawl_rss

with get_session() as session:
    new_count, updated_count = crawl_rss(source, session)
```

---

### `search.py` — Web search and AI integrations

All functions degrade gracefully: they return `[]` or `None` when keys are unset or limits are reached, so callers never need to guard against import errors or missing credentials.

#### DuckDuckGo (no API key required)

```python
from base.search import ddg_search

results = ddg_search("widget prices Canada", max_results=5, days=30)
# [{"title": "...", "url": "...", "content": "..."}, ...]
```

#### Tavily (requires `TAVILY_API_KEY`)

```python
from base.search import tavily_search

results = tavily_search("widget prices Canada", max_results=5, days=30)
```

Results have the same `{title, url, content}` shape as DDG results.

#### AI chat (LiteLLM load types or direct OpenAI)

```python
from script_scaffold.search import ai_chat

reply = ai_chat("Summarise this in one sentence: ...", route="fast")
json_reply = ai_chat(prompt, route="batch", json_mode=True)
```

When `LITELLM_URL` is healthy, `route` selects a load type defined in
`ai-dev-stack/litellm_config.yaml` (`fast`, `batch`, `standard`, `deep`, `code`, `audit`).
Otherwise falls back to direct OpenAI with a mapped cloud model.

```
LITELLM_URL=http://localhost:4000
LITELLM_MASTER_KEY=sk-local-dev-key
AI_ROUTE_OVERRIDE=deep          # optional debug override
OPENAI_API_KEY=sk-...           # fallback when proxy is down
```

Legacy env vars `AI_FILTER_MODEL`, `LLM_ROUTE`, and `AI_MODEL` still work but are deprecated.

---

### `llm.py` — LangChain provider factory

For pipelines that need structured outputs via `llm.with_structured_output(Schema)`.

```python
from script_scaffold.llm import get_llm, check_credentials, apply_options, describe

check_credentials()

llm = get_llm(temperature=0.1, route="deep")
llm = get_llm(temperature=0.1, route="standard")  # structured extraction

apply_options(provider="anthropic", model="claude-sonnet-4-6")  # CLI override
print(describe())  # "litellm  route=deep  url=http://localhost:4000/v1"
```

**Environment variables:**

| Variable | Purpose |
|---|---|
| `LLM_PROVIDER` | `litellm` (default) \| `openai` \| `anthropic` \| `ollama` |
| `LITELLM_URL` | LiteLLM proxy base URL (default: `http://localhost:4000`) |
| `LITELLM_MASTER_KEY` | Proxy auth key |
| `AI_ROUTE_OVERRIDE` | Force all routes to this load type (debug) |
| `LLM_MODEL` | CLI `--model` override (overrides route) |
| `OPENAI_MODEL` | OpenAI model when `LLM_PROVIDER=openai` |
| `ANTHROPIC_MODEL` | Anthropic model when `LLM_PROVIDER=anthropic` |
| `OLLAMA_MODEL` | Ollama model when `LLM_PROVIDER=ollama` |
| `OLLAMA_BASE_URL` | Ollama server URL (default: `http://localhost:11434`) |

---

### `db.py` — Database setup (updated)

`seed_from_list` is now available alongside the existing engine/session helpers:

```python
from script_scaffold.db import seed_from_list

# Idempotent seeding — inserts only rows that don't already exist
count = seed_from_list(
    get_session,
    Source,
    SEEDED_SOURCES,          # list of dicts
    match_on=["url", "scope"],
)
```

For API-style entries with no URL, match on a combination of non-nullable fields:

```python
seed_from_list(get_session, Source, API_SOURCES, match_on=["domain", "scope", "fetch_method"])
```

---

### `models.py` — ORM base and mixins (updated)

Two new mixins for analysis-pipeline tables are now available:

```python
from script_scaffold.models import Base, AnalysisMixin, ScorecardAnalysisMixin
from sqlalchemy.orm import declared_attr
from sqlalchemy import ForeignKey, Integer, String
```

**`AnalysisMixin`** — Adds `id`, `analysis_date`, and `created_at` to any periodic analysis result table. The entity FK must be defined by the concrete class (one instance per table is required by SQLAlchemy):

```python
class StockAnalysis(Base, AnalysisMixin):
    __tablename__ = "stock_analysis"

    @declared_attr
    def stock_id(cls) -> Mapped[int]:
        return mapped_column(Integer, ForeignKey("stocks.id"), nullable=False)

    sentiment: Mapped[str] = mapped_column(String(10))
```

**`ScorecardAnalysisMixin`** — Extends `AnalysisMixin` with `overall_score` (Float), `rationale_json` (Text), and `raw_llm_response` (Text). Use when a pipeline produces a single aggregate numeric score with a JSON rationale:

```python
class MiningScorecard(Base, ScorecardAnalysisMixin):
    __tablename__ = "mining_scorecard"

    @declared_attr
    def stock_id(cls) -> Mapped[int]:
        return mapped_column(Integer, ForeignKey("stocks.id"), nullable=False)

    resource_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    management_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

---

### `utils.py` — General utilities

```python
from base.utils import utcnow, format_price, format_date, vote_with_confidence
```

**`utcnow()`** — timezone-aware UTC datetime with `tzinfo` stripped (safe for SQLite `DateTime` columns).

**`format_price(val, currency=None)`**

```python
format_price(1234.5)          # "$1,234.50"
format_price(1234.5, "CAD")   # "CAD $1,234.50"
format_price(None)            # "—"
```

**`format_date(dt)`**

```python
format_date(datetime(2025, 6, 1))  # "2025-06-01"
format_date(None)                  # "—"
```

**`vote_with_confidence(extracted_list, normalise_fn=None, min_confidence=None)`**

Majority-votes across a list of per-source result dicts to produce a single best-guess dict with per-field confidence counts. Useful when aggregating data extracted from multiple independent web results.

```python
results = [
    {"color": "red",  "size": "large"},
    {"color": "red",  "size": "medium"},
    {"color": "blue", "size": "large"},
]

specs, confidence = vote_with_confidence(results)
# specs      → {"color": "red", "size": "large"}
# confidence → {"color": 2, "size": 2}
```

Supply `min_confidence` to require multiple sources to agree before a field is accepted:

```python
specs, confidence = vote_with_confidence(
    results,
    min_confidence={"color": 2, "size": 1},
)
```

Supply `normalise_fn(field, value) -> str | None` to collapse equivalent representations before counting (e.g. `"448.0 GB/s"` and `"448 GB/s"` → same vote). Return `None` to skip a value.
