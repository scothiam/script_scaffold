# Intentions

This document states *why* each class and function in this base library exists and the
use case it was designed for — independent of how it happens to be implemented today.

The README documents how to call things. This document is for a different purpose: a
checklist to compare the code against later. When you (or a downstream project extending
these classes) come back to this code, re-read the relevant entry below and ask "does the
code still do this, and only this?" If the answer is no, either the code drifted and needs
a fix, or the intention changed and this file needs updating.

When another project extends one of these classes, add a matching entry in that project's
own intentions doc describing the *specific* use case its subclass serves (e.g. "GpuLookup
validates GPU model names against a local catalog" rather than the generic "EntityLookup
validates named entities").

---

## db.py — database lifecycle

**`make_engine` / `make_session_factory` / `init_tables`**
Intention: stand up a single-file SQLite database for a script-sized project with no
external DB server. `check_same_thread=False` exists specifically so a session opened in
one thread (e.g. a scheduler) can be used from another — this is a deliberate relaxation,
not an oversight, and assumes the caller already serializes writes (e.g. via
`session_scope`'s commit/rollback boundary).

**`session_scope`**
Intention: give every write a single commit/rollback boundary so a script that crashes
mid-task can't leave half-written rows behind. Every write path in this library goes
through it; if you find a write that doesn't, that's drift.

**`seed_from_list`**
Intention: let a project hard-code a list of "starting data" (seed sources, default
config rows, etc.) directly in its own code and re-run that seeding on every startup
without creating duplicates. It is match-then-insert, never update — if a seeded row's
other fields change upstream, this function will not reconcile them. That's intentional:
seeding is for bootstrapping new environments, not syncing existing ones.

---

## models.py — ORM base and mixins

**`Base`**
Intention: the one `DeclarativeBase` shared by every table in every project built on this
scaffold, so all models live in the same SQLAlchemy metadata and `init_tables` can create
them all in one call.

**`PinnableMixin`**
Intention: for tables holding a list of *discrete items a user browses and curates* (deal
listings, watchlist entries) — adds the ability to pin a favourite plus created/updated
timestamps. Not intended for rows that are themselves aggregates or analysis output.

**`AnalysisMixin`**
Intention: the shared shape for "we ran a pipeline against an entity on a given date and
recorded a result" — one row per (entity, run). The entity foreign key is deliberately
left to the subclass (via `declared_attr`) because each domain's entity table differs
(stocks vs. GPUs vs. whatever); this mixin only owns what's common to *all* periodic
analysis tables: an id, the date the analysis covers, and when the row was created.

**`ScorecardAnalysisMixin`**
Intention: for analysis pipelines whose output is *one aggregate numeric score plus a
rationale*, as opposed to pipelines that produce multiple independent fields. Bundles the
raw LLM response alongside the score so a human can audit *why* the score landed where it
did without re-running the pipeline. If a downstream pipeline doesn't produce a single
overall score, it should not use this mixin — that's a sign `AnalysisMixin` alone is the
right fit.

---

## repository.py — generic CRUD

**`BaseRepository`**
Intention: every project-specific repository should be five lines — pass in
`get_session` and a model class, inherit the rest. The intention is that a downstream
project never re-implements get/save/update/delete/pin by hand; if it does, that's a sign
this base class is missing a method it should gain instead. Each public method opens and
closes its own session scope rather than accepting one, because callers are expected to
use a repository as a one-shot operation, not as part of a larger transaction they
control.

---

## lookup.py — entity validation

**`EntityLookup` / `LookupResult`**
Intention: a project that ingests free-text user input referring to a real-world named
entity (a GPU model, a stock ticker, a company name) needs to turn fuzzy input into either
a confirmed canonical name or a short list of "did you mean" suggestions before anything
gets persisted — never silently store an unrecognized or misspelled name. The base class
intentionally has no notion of *where* canonical data comes from (local dict, SQL table,
remote API); subclasses own that, this class only owns the normalization/matching
vocabulary (`normalize`, `fingerprint`, `token_similarity`) so every subclass's matching
behaves consistently.

---

## sources.py — content source tracking

**`Source`**
Intention: a single row per *place to fetch content from* (a feed URL, a page, an API
endpoint), tagged with an app-defined `scope`/`scope_value` so one sources table can serve
several unrelated features in the same app (e.g. general news vs. per-ticker news) without
needing a table per feature. `is_active` exists so a feed that starts 404ing gets quietly
excluded from future crawls rather than failing every run indefinitely — the intention is
self-healing crawl lists, not manual pruning.

**`SourceItem`**
Intention: one row per distinct piece of content ever seen from a `Source`, deduplicated
forever by `item_url`. `content_hash` exists so a re-fetched-but-unchanged item costs
nothing beyond a timestamp touch, while a genuinely edited item is detected and re-queued
via `is_processed=False` for whatever downstream pipeline consumes it. The intention is
that "new content to process" is always answerable by querying `is_processed`, never by
diffing fetch runs.

---

## source_repository.py — Source/SourceItem queries

**`SourceRepository`**
Intention: hold every query shape that a crawler or a content-consuming pipeline actually
needs (by scope, active+crawlable, recent, in a date range, mentioning specific terms) so
that no project writes raw SQLAlchemy queries against `Source`/`SourceItem` directly. The
`scope_value is None` matches "applies to all" convention in `active_crawlable` is load
-bearing: it's what lets a single general-purpose source (e.g. a broad market news feed)
be returned for every specific scope value without being duplicated per entity.

**`domain_from_url`**
Intention: derive a human-readable domain for display/dedup purposes when seeding or
listing sources, without pulling in a full URL-parsing dependency.

---

## rss_crawler.py — feed crawling

**`BaseCrawler` / `RssCrawler`**
Intention: `BaseCrawler` exists purely so a future HTML or API crawler can be dropped in
beside `RssCrawler` and driven by the same `crawl_sources` loop. `RssCrawler` itself
encodes a specific policy: a feed returning HTTP 4xx is assumed dead and the source is
marked inactive (see `Source.is_active` above) rather than retried — the intention is an
unattended scheduled crawl that prunes its own source list rather than accumulating
permanently-broken feeds.

**`crawl_rss` / `crawl_sources`**
Intention: module-level wrappers kept for callers written before `BaseCrawler` existed.
`crawl_sources` deliberately gives each source its own session so one feed's failure
can't roll back items already saved from other feeds in the same run — a partial-success
crawl is the expected outcome, not a failure.

---

## search.py — web search and single-turn LLM calls

**`BaseSearch` / `DdgSearch` / `TavilySearch`**
Intention: every search backend normalizes to the same `{title, url, content}` shape so a
caller can swap DDG for Tavily (or fall back from one to the other) without touching
downstream code. Every backend is intentionally fail-soft: a missing key, a network error,
or a hit usage limit returns `[]` rather than raising, because search is treated as
*best-effort enrichment*, never a hard dependency a pipeline can't run without.
`TavilySearch` additionally disables itself for the rest of the process once it detects a
usage-limit error, so a long-running batch job doesn't keep re-hitting (and re-logging) a
plan limit on every subsequent call.

**`ai_chat` / `resolve_ai_config`**
Intention: a single-turn "ask an LLM one question, get one string back" helper for use
cases too simple to justify LangChain (`llm.py`) — e.g. a one-off summarization or
classification inside a script. When `AI_BASE_URL` is unset, prefers the ai-dev-stack
LiteLLM proxy (load types: `fast`, `batch`, `standard`, `deep`, `code`, `audit` — local
pools with cloud fallback), then direct OpenAI via `OPENAI_API_KEY` or legacy `AI_API_KEY`.
Callers pass `route=` to select the load type; legacy `AI_FILTER_MODEL` / `LLM_ROUTE` env
vars still map to routes. Set `AI_BASE_URL` explicitly to target any other OpenAI-compatible endpoint. Same fail-soft contract as the search
functions: no credentials or permanent auth/quota error returns `None` and disables
itself for the run, rather than crashing the calling script.

---

## ai_gates.py — fast per-item AI filter gates

**`GateResult` / `FastAiGate`**
Intention: give filter pipelines a shared skeleton for "ask the fast model one yes/no
question about this item, keep or reject it" without each project re-implementing
`ai_chat` wiring, JSON parsing, skip shortcuts, and fail-open behavior. Subclasses
own the prompt and reply parser; the base class owns the call contract
(`route=fast`, JSON mode, `(keep, reason, ai_called)` outcome). Same fail-soft
default as `ai_chat`: when `fail_open=True` (the default), a missing API, failed
call, or unparseable reply keeps the item rather than dropping it silently.
Downstream projects use this for post-fetch gates (resume vs job posting, hard
requirement checks, remote eligibility) where a keyword list would require endless
maintenance.

---

## llm.py — LangChain provider factory

**`get_llm` / `check_credentials` / `apply_options` / `describe`**
Intention: for the opposite use case from `search.py`'s chat helpers — pipelines that need
`.with_structured_output(Schema)` to get a typed/validated object back from the LLM rather
than a string. When `LLM_PROVIDER=litellm` (default), callers pass `route=` to select a
load type; provider choice remains a single env var so a project can switch
openai/anthropic/ollama without code changes, including in deployed/scheduled contexts
where flags aren't convenient. Unlike `search.py`, a missing package or credential here
raises `SystemExit` rather than degrading gracefully — the intention is that a structured
-output pipeline genuinely cannot produce a meaningful result without its LLM, so failing
fast at startup (ideally via an explicit `check_credentials()` call before a long pipeline
begins) is preferable to failing deep inside a multi-step run.

---

## utils.py — small shared helpers

**`utcnow`**
Intention: a single source of "now" for every `created_at`/`fetched_at` column in this
library, with `tzinfo` stripped specifically because SQLite's `DateTime` column can't
round-trip timezone-aware datetimes reliably — so this is the one place that decision
lives rather than being repeated (and potentially gotten wrong) at every call site.

**`format_price` / `format_date`**
Intention: consistent, locale-light display formatting for prices/dates across every
project's UI or report output, including a consistent placeholder (`"—"`) for missing
values so templates don't need their own None-handling.

**`vote_with_confidence`**
Intention: when multiple independent sources (search results, scraped pages, LLM
extractions) each report a value for the same field, and they don't all agree, pick the
majority answer and report how many sources agreed — so a downstream pipeline can decide
per-field whether to trust the result or treat it as unknown via `min_confidence`. The
`normalise_fn` hook exists because "agreement" should be judged on meaning, not on exact
string equality (e.g. `"448 GB/s"` vs `"448.0 GB/s"`).
