# CHANGELOG

All notable changes to ChemAgent are documented in this file.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).  
Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.2.0] — 2026-03-24

### Summary

Completed the pluggable multi-agent architecture: specialist→tool mapping is now
category-based (not name-exact), making the system truly pluggable. Router
modernized to single `ConversableAgent.run()` (removes legacy `AssistantAgent` +
`UserProxyAgent` pair). LLM config migrated from raw `dict` to typed `LLMConfig`.
Manager routing system message updated to accurately reflect all specialist
capabilities including newly wired tools.

### Changed

#### Pluggable Tool Routing (`backend/app/agents/specialists/`)

- **`visualizer.py`** — Tool selection predicate changed from `spec.name == "draw_molecules_by_name"` to `spec.category == "visualization"`.
  Now receives **2 tools**: `draw_molecules_by_name` (name→PubChem→image) and `generate_2d_image_from_smiles` (SMILES→image).  
  System message updated to explain both tools and when to use each.

- **`researcher.py`** — Tool selection predicate changed from `spec.name == "web_search"` to `spec.category == "retrieval"`.
  Now receives **2 tools**: `web_search` (literature/drug/approval search) and `get_smiles_by_name` (PubChem SMILES lookup).  
  System message updated to guide the LLM on choosing between the two retrieval strategies.

- **`analyst.py`** — Tool selection predicate changed from `spec.name == "analyze_molecule_from_smiles"` to `spec.category == "analysis"`.
  Receives 1 tool now; ready for any future `analysis`-category tool without file edits.

- **Plugin contract**: Any new tool file added to `backend/app/tools/` that registers with `category="visualization"`, `"retrieval"`, or `"analysis"` will automatically flow to the appropriate specialist via `walk_packages` discovery. Zero specialist file edits required.

#### Router Modernization (`backend/app/agents/manager.py`, `factory.py`, `runtime.py`, `sessions.py`)

- **`manager.py`** — `create_routing_agent()` now returns a single `ConversableAgent` instead of a `tuple[AssistantAgent, UserProxyAgent]`.
  Sessions call `router.run(max_turns=1, silent=True)` and exhaust `.events` to obtain `.summary`.
  Eliminates `AssistantAgent`, `UserProxyAgent`, and `initiate_chat()` from the routing path.

- **`factory.py`** — Removed `create_assistant_agent()` and `create_executor_agent()` (used only by the old routing pair).
  Added `create_router_agent(*, name, system_message, llm_config) → ConversableAgent`.
  Removed `AssistantAgent`, `UserProxyAgent` imports entirely.

- **`api/runtime.py`** — `AgentTeam` dataclass: removed `router_trigger: UserProxyAgent` field; `router` type changed from `AssistantAgent` to `ConversableAgent`.
  Object count per turn: 9 → **6** (router pair merged into one).

- **`api/sessions.py`** — `_do_routing()` replaced `team.router_trigger.initiate_chat(team.router, ...)` with `team.router.run(max_turns=1, silent=True)` + `for _ in result.events: pass` + `result.summary`.

#### LLM Config Migration (`backend/app/agents/config.py`)

- `build_llm_config()` now returns `LLMConfig` (the typed AG2 Pydantic model) instead of a raw `dict[str, list[dict]]`.
  Per the AG2 skill documentation: *"Always use `LLMConfig` — never pass a raw dict"*.
- `get_fast_llm_config()` return type updated similarly.
- `sessions.py` `_resolved_model()` updated: `.config_list[0]["model"]` (attribute access) replaces `["config_list"][0]["model"]` (dict key).
- `sessions.py` `synthesis_factory` return annotation updated to `tuple[str, str, LLMConfig]`.
- `api/event_bridge.py` `stream_synthesis_async()` updated: `llm_config.config_list[0]` replaces `llm_config["config_list"][0]`.

#### Manager Routing System Message (`backend/app/agents/manager.py`)

- Updated `_ROUTING_SYSTEM_MESSAGE` to accurately describe all current specialist capabilities:
  - Visualizer: name→PubChem→2D image **and** SMILES→2D image
  - Researcher: web/literature search **and** PubChem SMILES lookup
  - Analyst: SMILES → Lipinski/descriptors (unchanged)
- Added routing rule: "user provides compound name, only needs SMILES (no visualization) → `["researcher"]`" (Researcher uses `get_smiles_by_name`).

#### Plugin Convention Documentation (`backend/app/tools/babel/__init__.py`)

- Added category convention block documenting that future Babel agent tools should register with `category="conversion"`, `"3d"`, or `"docking"`.
- Documented how a future Preparator specialist can filter by these categories with zero edits to existing files.

### Fixed

- `generate_2d_image_from_smiles` and `get_smiles_by_name` were registered in the tool registry but never assigned to any specialist (dead registry entries). Both are now active.

### Technical Notes

- AG2 `LLMConfig` constructor in 0.11.4: accepts `LLMConfig(flat_dict)` (single positional dict); does **not** accept `config_list=` keyword. Internally stores as `config_list=[entry]` with Pydantic model per entry. `config_list[0]` returns a dict-like object supporting key access.
- `ConversableAgent.run()` returns `RunResponseProtocol`. Iterating `for _ in result.events: pass` exhausts the queue and causes `RunCompletionEvent` to populate `result.summary` synchronously. No `result.process()` call needed (that prints to console).

---

## [2.1.0] — 2026-03-24

### Summary

AG2 0.11.4 full migration to single-agent `ConversableAgent` pattern; multiple
bug fixes discovered during the audit; Redis dev environment and VS Code task
improvements; Pylance/Pyright type-safety hardening throughout the backend.

### Changed

#### AG2 Agent Architecture (`backend/app/agents/`)

- **`factory.py`** — Replaced old dual-agent factory functions with two new
  primitives that implement the modern ag2 single-agent pattern:
  - `create_specialist_agent(*, name, system_message, llm_config, specs, max_consecutive_auto_reply) → tuple[ConversableAgent, list[Tool]]`  
    Creates one `ConversableAgent` per specialist, pre-registers tools for LLM
    reasoning via `tool.register_for_llm(agent)`, and returns the tool list for
    runtime execution via `agent.run(tools=[...])`.
  - `get_specialist_tools(specs) → list[Tool]`  
    Converts raw `ToolSpec` registry entries to `autogen.tools.Tool` objects.
  - Removed: `create_tool_agent_pair()`, `register_tools()` (dual-agent pattern).

- **`specialists/visualizer.py`**, **`/analyst.py`**, **`/researcher.py`** —  
  Each specialist creator migrated from returning `(AssistantAgent, UserProxyAgent)`
  pairs to returning `(ConversableAgent, list[Tool])`.  
  `max_consecutive_auto_reply` tuned per specialist: Visualizer=4, Analyst=3,
  Researcher=4.

- **`manager.py`** — Removed dead code:
  - `create_manager()` — synthesis never used the AG2 Manager object; raw
    `AsyncOpenAI` in `event_bridge.stream_synthesis_async()` bypasses AG2.
  - `sanitize_messages()` — v2 never persists AG2 `_oai_messages` to Redis;
    only text summaries are stored.
  - Removed stale `build_llm_config` import.

- **`api/runtime.py`** — `AgentTeam` dataclass reduced from 9 fields to 7:
  - Removed: `manager`, `visualizer_executor`, `researcher_executor`,
    `analyst_executor`.
  - Added: `visualizer_tools`, `researcher_tools`, `analyst_tools`
    (`list["Tool"]` each).
  - Re-typed `router: AssistantAgent` and `router_trigger: UserProxyAgent`
    (previously untyped as `object`, causing Pylance `initiate_chat` error).
  - Now imports `AssistantAgent` and `UserProxyAgent` at module level (not
    behind `TYPE_CHECKING`) so the dataclass field types are concrete.

- **`api/sessions.py`** — Updated for the new `AgentTeam` shape:
  - `_build_agent_team()`: unpacks each specialist as `agent, tools = create_*()`
    instead of `agent, executor = create_tool_agent_pair()`.
  - `build_run_plan()` Phase 2: calls `agent.run(message=..., tools=agent_tools,
    clear_history=True, summary_method="last_msg", silent=False)` for each
    active specialist (single-agent pattern replacing `executor.run(recipient=agent)`).
  - `run_greeting()`: creates a temporary `ConversableAgent` inline without
    building a full `AgentTeam`; the agent is discarded after `.run()` returns.

#### Type Safety (`backend/app/core/redis_client.py`)

- Added `AsyncRedis` Protocol (`@runtime_checkable`) that declares all
  redis methods used in the codebase as `async def` with concrete return types.  
  **Root cause**: redis-py 5.x types async-client methods as
  `Union[Awaitable[T], T]` because the class serves both sync and async clients.
  Pylance cannot narrow the Union, so every `await redis.*()` call produced a
  type error.  
  **Fix**: `get_redis()` now returns `AsyncRedis` (Protocol) instead of
  `aioredis.Redis`.  At runtime the actual object is still `aioredis.Redis`
  (satisfies the Protocol); no behaviour change.

#### Dev Environment (`.vscode/tasks.json`, `compose.yaml`)

- **`tasks.json`** — two new tasks:
  - `📦 Start Dev Redis` — runs `docker compose up -d redis` (blocking, exits
    once the container is healthy).
  - `🧪 ChemAgent Dev (Redis + Full Stack)` — sequential compound task that
    starts Redis first, then launches Backend + Frontend in parallel; recommended
    entry-point for local development without Docker.
- **`compose.yaml`** — added `ports: ["6379:6379"]` to the `redis` service so
  the Docker container's Redis is reachable on the host's `localhost:6379`.
  This is required for `uv run uvicorn` (running on the host) to connect to
  Redis without a full `docker compose up`.

### Fixed

- **`tools/pubchem/lookup.py`** — `except requests.exceptions.RequestException`
  raised a `NameError` at runtime because `requests` was never imported; the
  actual HTTP client is `httpx`.  
  Fixed: `except httpx.RequestError`.

- **`agents/config.py`** — `_load_environment()` had a TOCTOU race window on
  `_ENV_LOADED` when multiple IO_POOL threads entered simultaneously.  
  Fixed: `threading.Lock()` with double-checked locking.

- **`api/protocol.py`** — Two protocol bugs:
  - `ServerEventType` Literal was missing `"turn.status"` and `"turn.started"`,
    causing `ValidationError` when `chat.py` emitted those frames.
  - `UserMessage.content` was a required field, breaking `session.clear`
    messages that carry no text body.  
    Fixed: `content: str = ""` (default empty string).

### Infrastructure

- Stopped and disabled the `apt`-installed system `redis-server` service that
  was introduced during debugging.  Replaced with the project-native
  `redis:7-alpine` Compose container to avoid port 6379 conflicts on reboot.

---

## [2.0.0] — 2026-03-23

### Summary

Concurrent architecture overhaul — stateless sessions + async computation.
Designed for 50 concurrent users on 4 GB RAM without OOM risk.

### Added

- **Redis session store** (`backend/app/core/redis_client.py`):  
  Async connection pool (`max_connections=100`) + separate sync client (`max_connections=50`) for tool callbacks in IO_POOL threads.  
  Key schema: `session:{id}` hash, `session:{id}:turns` list (LTRIM to 3, TTL 1800 s), `tool_result:{id}` string (TTL 600 s).

- **Global bounded IO_POOL** (`backend/app/core/executor.py`):  
  Single process-wide `ThreadPoolExecutor(max_workers=16)` replaces unbounded per-turn ephemeral pools.

- **Rate limiting** (`backend/app/core/limiter.py`):  
  slowapi `Limiter` with Redis storage. Constants: `CHAT_RATE = "10/minute"`, `COMPUTE_RATE = "3/5 minutes"`.

- **Health check API** (`backend/app/api/health.py`):  
  `GET /api/health` — Redis PING + ARQ worker heartbeat (HTTP 200/503).  
  `GET /api/health/queue` — queue depth + pressure level (`low`/`medium`/`high`).

- **ARQ task queue** (`backend/app/workers/`):  
  `chem_tasks.py` — three async task functions for heavy computation:  
  `task_build_3d_conformer`, `task_prepare_pdbqt`, `task_compute_descriptors`.  
  `main.py` — `WorkerSettings` with `max_jobs=4`, `job_timeout=120`, `keep_result=600`, `health_check_interval=30`.

- **Redis + ARQ worker services** in `compose.yaml`:  
  `redis` service: redis:7-alpine, 512 MB `maxmemory`, `allkeys-lru`.  
  `arq-worker` service: same backend image, 768 MB memory limit.  
  Both backend and worker receive `REDIS_URL` env var.

- **`GET /api/babel/jobs/{job_id}`** poll endpoint — check ARQ job status and retrieve result.

- **Dockerfile HEALTHCHECK**: `GET /api/health` with 30s interval, 5s timeout, 15s start period.

- **`docs/CHANGELOG.md`** (this file).

- **`docs/ARCHITECTURE.md` §14** — 并发架构 v2 section: memory budget table, infra topology diagram, Redis key schema, per-turn lifecycle flowchart, Gotcha fix register.

- **`docs/SOURCE_MAP.md` §13–14** — v2 quick-index additions + new file table.

### Changed

- **`backend/app/api/sessions.py`** — completely rewritten.  
  Old: `ChatSession` + `SessionManager` in-process singleton (9 AG2 objects per session).  
  New: Redis-backed async functions (`create_session`, `get_turn_history`, `push_turn`, `clear_session`) + sync `build_run_plan()` / `run_greeting()` that create and destroy `AgentTeam` per turn.

- **`backend/app/api/chat.py`** — stateless WebSocket handler.  
  Old: `threading.Lock` per session, persistent `ChatSession`, daemon threads with `Queue`.  
  New: `asyncio.Lock` per connection, stateless `session_id` + `agent_models` dict, `IO_POOL.submit(stream_specialists)` + `await stream_synthesis_async()`.

- **`backend/app/api/event_bridge.py`** — three key changes:  
  1. `_drain_specialists_parallel()` uses shared `IO_POOL` instead of per-turn `ThreadPoolExecutor`.  
  2. New `stream_specialists()` sync function (Phase 2 IO_POOL entry point).  
  3. New `stream_synthesis_async()` async function using `AsyncOpenAI` — no Queue, streams directly to WebSocket.  
  4. `stream_greeting()` accepts `agent_models: dict` instead of `ChatSession`.  
  Removed: `stream_multi_agent_run()`, `_stream_synthesis_direct()`.

- **`backend/app/api/babel_api.py`** — heavy endpoints → ARQ.  
  `POST /api/babel/conformer3d` and `POST /api/babel/pdbqt` now return HTTP 202 + `job_id` immediately.

- **`backend/app/core/tooling.py`** — `ToolResultStore` backed by Redis (`get_sync_redis()`).  
  Old: `dict` + `threading.Lock` + manual pruning.  
  New: `setex`/`get` with TTL, graceful degradation if Redis unavailable.

- **`backend/app/agents/manager.py`** — added `sanitize_messages()` (Gotcha 2 fix).  
  Deep-converts AG2 `_oai_messages` Pydantic objects → JSON-safe dicts before Redis storage.

- **`backend/app/main.py`** — lifespan context manager (`init_redis` → `close_redis` + `IO_POOL.shutdown`), health router at `/api/health`, slowapi `RateLimitExceeded` handler.

- **Tools HTTP library** — `requests` → `httpx` (sync) in all three tool files:  
  `backend/app/tools/pubchem/lookup.py`, `backend/app/tools/rdkit/image.py`, `backend/app/tools/search/web.py`.

- **`backend/pyproject.toml`** — new dependencies:  
  `redis[asyncio]>=5.0`, `hiredis>=2.3`, `arq>=0.26`, `httpx>=0.27`, `slowapi>=0.1.9`.  
  Dev extras: `fakeredis>=2.23`, `pytest>=8.0`, `pytest-asyncio>=0.24`.

### Fixed

- **Gotcha 1** — IO_POOL threads had no asyncio event loop.  
  Fixed: two Redis clients — async for WebSocket handlers, sync for tool callbacks in threads.

- **Gotcha 2** — AG2 `_oai_messages` contained non-JSON-serializable Pydantic objects.  
  Fixed: `sanitize_messages()` deep-converts before any Redis serialization.

- **Gotcha 3** — Default Redis connection pool size (10) exhausted under 50 concurrent users.  
  Fixed: `max_connections=100` in async pool, `max_connections=50` in sync pool.

---

## [1.0.0] — 2025 (initial release)

### Added

- Three-phase multi-agent routing: Manager → Specialists (Visualizer / Analyst / Researcher) → Synthesis.
- AG2-based agent framework with RDKit and OpenBabel chemistry engines.
- WebSocket streaming with real-time event frames (`tool.call`, `tool.result`, `assistant.message`, `run.finished`).
- Next.js frontend with chat UI, artifact gallery, and molecule card renderer.
- REST API for RDKit (2D image, Lipinski, fingerprint) and OpenBabel (convert, conformer3d, pdbqt, sdf-split/merge).
- Docker Compose deployment with nginx gateway.
