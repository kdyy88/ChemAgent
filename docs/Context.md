# ChemAgent — Project Context (AI Onboarding Reference)

> **Purpose**: This document gives any new AI assistant or developer an accurate,
> complete picture of ChemAgent's architecture, conventions, and current state.
> Read this before making any changes.
>
> **Last updated**: 2026-03-24 (v2.2.0)

---

## 1. What Is ChemAgent?

ChemAgent is an AI-driven drug-discovery assistant. It combines:

- A **FastAPI backend** running a pluggable multi-agent pipeline (AG2 0.11.4)
- A **Next.js frontend** providing a three-panel IDE-style workspace with an
  embedded AI Copilot chat panel
- **RDKit** and **Open Babel** for cheminformatics operations
- **Redis** (Docker Compose) for session storage and async task queuing (arq)

Users interact via natural language in the chat panel. The backend routes the
request to specialist agents, each with domain-specific tools, and streams the
synthesised answer back over WebSocket.

---

## 2. Tech Stack

| Layer | Technology | Notes |
|---|---|---|
| Language | Python 3.12 | `uv` for package management |
| Web framework | FastAPI | uvicorn with lifespan |
| Agent framework | `ag2` 0.11.4 | NOT `autogen-agentchat`; package import is `autogen` |
| LLM config | `autogen.LLMConfig` | Never use raw dict — see §7 |
| Cheminformatics | RDKit, openbabel-wheel | Wrapped in `app/chem/` |
| Session / queue | Redis 7-alpine | Docker Compose only; `arq` workers |
| Frontend | Next.js 14 (App Router) | pnpm, Tailwind CSS, Shadcn UI, Zustand |
| State management | Zustand | `chatStore.ts`, `workspaceStore.ts` |
| Container / infra | Docker Compose, Nginx | `compose.yaml`, `deploy/nginx/` |

---

## 3. Repository Layout

```
chem-agent-project/
├── backend/
│   └── app/
│       ├── main.py              # FastAPI app + lifespan (tool registry init)
│       ├── agents/              # AG2 agent construction
│       │   ├── config.py        # build_llm_config() → LLMConfig
│       │   ├── factory.py       # create_specialist_agent(), create_router_agent()
│       │   ├── manager.py       # create_routing_agent(), SYNTHESIS_SYSTEM_MESSAGE
│       │   └── specialists/     # visualizer.py, researcher.py, analyst.py
│       ├── api/                 # FastAPI routers + orchestration engine
│       │   ├── chat.py          # WebSocket /ws/{session_id}
│       │   ├── sessions.py      # Three-phase per-turn orchestration
│       │   ├── runtime.py       # AgentTeam, MultiAgentRunPlan dataclasses
│       │   ├── event_bridge.py  # AG2 events → WebSocket frames + synthesis streaming
│       │   ├── rdkit_api.py     # /rdkit/* REST endpoints
│       │   ├── babel_api.py     # /babel/* REST endpoints
│       │   └── health.py        # /health
│       ├── chem/                # Pure-Python chem wrappers (no AG2)
│       │   ├── rdkit_ops.py     # RDKit operations
│       │   └── babel_ops.py     # Open Babel operations
│       ├── core/
│       │   ├── tooling.py       # ToolRegistry, ToolSpec, @tool_registry.register
│       │   ├── redis_client.py  # AsyncRedis Protocol
│       │   ├── executor.py      # Specialist run helper
│       │   ├── limiter.py       # Rate limiter
│       │   └── network.py       # HTTP client helpers
│       ├── tools/               # Pluggable tool packages (auto-discovered)
│       │   ├── rdkit/           # category="analysis" + "visualization"
│       │   ├── pubchem/         # category="retrieval"
│       │   ├── search/          # category="retrieval"
│       │   └── babel/           # category="conversion", "3d", "docking" (future)
│       └── workers/             # arq background workers
├── frontend/
│   ├── app/                     # Next.js App Router pages
│   │   ├── page.tsx             # Root → chat UI
│   │   └── workflow/page.tsx    # (Agent flow editor, experimental)
│   ├── components/
│   │   ├── chat/                # ChatInput, MessageList, MoleculeCard, etc.
│   │   ├── workspace/           # Three-panel IDE layout, tool forms
│   │   └── ui/                  # Shadcn UI primitives
│   ├── hooks/useChemAgent.ts    # WebSocket hook — primary data flow
│   ├── lib/chem-api.ts          # REST client for /rdkit, /babel endpoints
│   ├── store/chatStore.ts       # Zustand: messages, session, streaming state
│   └── store/workspaceStore.ts  # Zustand: currentSmiles, activeFunctionId
└── docs/
    ├── Context.md               # ← This file
    ├── CHANGELOG.md             # Versioned change history
    ├── ARCHITECTURE.md          # Deep architecture notes
    ├── API.md                   # REST + WebSocket API reference
    └── SOURCE_MAP.md            # File-by-file responsibility map
```

---

## 4. Three-Phase Orchestration Pipeline

Every user turn runs three sequential phases in `backend/app/api/sessions.py`.

### Phase 1 — Routing

```
Router (single ConversableAgent)
  .run(message=routing_prompt, max_turns=1, silent=True)
  → JSON: {"specialists": ["visualizer", "researcher"]}
```

- Router is a single `ConversableAgent` created by `create_routing_agent()` in `manager.py`.
- Uses `max_turns=1`; events exhausted with `for _ in result.events: pass` to make `result.summary` available.
- Routing decision is parsed from `result.summary`.
- Routing system message (`_ROUTING_SYSTEM_MESSAGE`) describes all specialists and their tool capabilities.

### Phase 2 — Parallel Specialist Execution

```
For each selected specialist (visualizer / researcher / analyst):
  agent.run(message=specialist_prompt, tools=tools, max_turns=...)
  → SpecialistSummary(role, summary, tool_calls, images)
```

- Specialists run concurrently via `asyncio.gather`.
- Tools are passed into `.run(tools=...)` — **never pre-registered** before calling `.run()`.
- Each specialist receives only the tools whose `category` matches its predicate.
- Events are forwarded to the WebSocket in real time via `event_bridge.py`.

### Phase 3 — Synthesis

```
AsyncOpenAI(streaming=True)
  prompt = SYNTHESIS_SYSTEM_MESSAGE + all specialist summaries
  → Markdown stream back to WebSocket
```

- Phase 3 **intentionally bypasses AG2** and calls the LLM API directly for full streaming control.
- `stream_synthesis_async()` in `event_bridge.py` constructs the client from `LLMConfig`.

---

## 5. Pluggable Tool Registry

### Registration (`app/core/tooling.py`)

```python
@tool_registry.register(
    name="analyze_molecule_from_smiles",
    category="analysis",
    tags=["rdkit", "lipinski", "descriptors"],
    description="...",
    output_kinds=["json"],
)
def analyze_molecule_from_smiles(smiles: str) -> dict: ...
```

Tools are discovered automatically at startup via `pkgutil.walk_packages` over the `app/tools/` namespace. The `@tool_registry.register()` decorator fires when the module is imported, adding a `ToolSpec` to `ToolRegistry._tools`.

### Specialist → Category Mapping

| Specialist | Predicate | Tools (v2.2.0) |
|---|---|---|
| Visualizer | `spec.category == "visualization"` | `draw_molecules_by_name`, `generate_2d_image_from_smiles` |
| Researcher | `spec.category == "retrieval"` | `web_search`, `get_smiles_by_name` |
| Analyst | `spec.category == "analysis"` | `analyze_molecule_from_smiles` |

### Adding a New Tool (Zero Existing-File Edits)

1. Create a new file in `backend/app/tools/<package>/your_tool.py`.
2. Decorate with `@tool_registry.register(category="<category>", ...)`.
3. The tool is auto-discovered at startup and routed to the matching specialist automatically.

### Future: Babel-Tool Categories

Future tools in `app/tools/babel/` should use these category strings:

| Category | Meaning |
|---|---|
| `"conversion"` | Format conversion (SDF↔SMILES, MOL2, PDB…) |
| `"3d"` | 3D conformer generation, energy minimization |
| `"docking"` | PDBQT preparation, docking setup |

A future **Preparator** specialist would use `spec.category in {"conversion", "3d", "docking"}` and require no edits to the existing three specialist files.

---

## 6. Agent Construction API (AG2 0.11.4)

### LLMConfig — ALWAYS use; NEVER pass raw dict

```python
from autogen import LLMConfig

# Correct — flat dict positional arg
llm_config = LLMConfig({"model": "gpt-4o", "api_key": "sk-..."})

# Wrong — keyword arg not supported in 0.11.4
# llm_config = LLMConfig(config_list=[{"model": "..."}])  # TypeError

# Wrong — never pass dict directly to an agent
# agent = ConversableAgent(llm_config={"config_list": [...]})
```

Accessing values:

```python
# llm_config.config_list[0] returns a dict-like object
model    = llm_config.config_list[0]["model"]
api_key  = llm_config.config_list[0]["api_key"]
base_url = llm_config.config_list[0].get("base_url")
```

### ConversableAgent — the only agent class to use for new code

```python
from autogen import ConversableAgent

router = ConversableAgent(
    name="Manager_Router",
    system_message="...",
    llm_config=llm_config,          # LLMConfig object
    max_consecutive_auto_reply=1,
    human_input_mode="NEVER",
    code_execution_config=False,
)
```

### Running an Agent

```python
# Single-shot routing
result = router.run(
    message=routing_prompt,
    max_turns=1,
    clear_history=True,
    summary_method="last_msg",
    silent=True,
)
for _ in result.events:             # exhaust queue → populates result.summary
    pass
decision = result.summary or ""

# Specialist with tools (passed at call time, not at construction)
result = specialist.run(
    message=task_prompt,
    tools=tools,
    max_turns=10,
    silent=True,
)
```

### Deprecated patterns — DO NOT USE

| Pattern | Replacement |
|---|---|
| `AssistantAgent` | `ConversableAgent` |
| `UserProxyAgent` | Not needed for routing |
| `initiate_chat(target, ...)` | `agent.run(message=..., max_turns=N)` |
| `result.process()` | `for _ in result.events: pass` (prints to console) |
| `AssistantAgent + UserProxyAgent` pair for routing | Single `ConversableAgent.run()` |

---

## 7. LLM Configuration (`app/agents/config.py`)

`build_llm_config(model)` reads `OPENAI_API_KEY`, optional `OPENAI_BASE_URL`, and `LLM_MODEL` from the environment and returns `LLMConfig({"model": ..., "api_key": ..., "base_url": ...})`.

`get_fast_llm_config()` uses `FAST_MODEL` (defaults to `LLM_MODEL`) for the router's quick one-shot calls.

Environment variables (`.env` in `backend/`):

| Variable | Purpose | Default |
|---|---|---|
| `OPENAI_API_KEY` | LLM API key | required |
| `LLM_MODEL` | Primary model | `gpt-4o` |
| `FAST_MODEL` | Router / fast calls | same as `LLM_MODEL` |
| `OPENAI_BASE_URL` | Custom endpoint (OpenRouter, etc.) | not set |
| `REDIS_URL` | Redis connection | `redis://localhost:6379/0` |

---

## 8. Redis

- **Purpose**: HTTP session storage (turn history, model selections) + `arq` async task queue.
- **Dev setup**: Docker Compose service `redis:7-alpine` on port 6379. System-level `redis-server` is disabled.
- **Client**: `AsyncRedis` Protocol in `app/core/redis_client.py` — type-safe interface over `redis.asyncio`.
- **Pinned**: `redis>=5.3,<6` due to `arq` compatibility constraint.

---

## 9. Frontend Architecture

### Three-Panel IDE Workspace

The workspace (Next.js App Router, `app/page.tsx`) is split with `react-resizable-panels`:

| Panel | Default Width | Component | Purpose |
|---|---|---|---|
| A — Navigation | 15% | `ToolSidebar.tsx` | VS Code-style activity bar + tree menu |
| B — Main workbench | 60% | `WorkspaceArea.tsx` | 12 professional chemistry tool forms |
| C — AI Copilot | 25% | `CopilotSidebar.tsx` | Chat panel with streaming Markdown |

### Key Mechanisms

**Implicit Context Injection**: When the user types in the Copilot panel, `ChatInput.tsx` reads `currentSmiles` and `activeFunctionId` from Zustand and appends a hidden system annotation to the message (`[System context: user is operating molecule <SMILES> in tool <id>]`). This gives the AI "sight" of the current workspace state without the user doing anything extra.

**Actionable UI (Markdown → Button)**: The AI can respond with custom tags like `<ApplySmiles smiles="CCO" />`. The Markdown renderer intercepts this and renders a Shadcn `<Button>`. On click it calls `zustand.setSmiles(smiles)`, updating the centre-panel form automatically — completing the AI-suggests → auto-apply loop.

**WebSocket hook**: `hooks/useChemAgent.ts` manages the WebSocket connection to `ws://<host>/ws/{session_id}`. Server frames: `thinking`, `tool_call`, `tool_result`, `token`, `done`, `error`.

### Chemistry Tool Forms (WorkspaceArea)

Twelve tool forms across four domains, all using the shared `<ToolLayout>` component:

| Domain | Tools |
|---|---|
| Data cleaning | SMILES validation, desalting & neutralization |
| Physicochemical properties | Full descriptor + Lipinski panel, atomic partial charges |
| Structure analysis | Fingerprint similarity, substructure & PAINS filter, Murcko scaffold |
| 3D & docking | Format converter, 3D conformer + energy, PDBQT preparation, SDF batch split/merge |

---

## 10. Running Locally

```bash
# 1. Start Redis
docker compose up redis -d

# 2. Start backend
cd backend
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 3. Start frontend (separate terminal)
cd frontend
pnpm dev
```

Or use the VS Code task **🚀 Start ChemAgent (Full Stack)** to launch both in parallel.

---

## 11. Conventions & Rules

### Never Do

| Rule | Reason |
|---|---|
| Pass raw `dict` as `llm_config` | AG2 0.11.4 requires `LLMConfig` object |
| Pre-register tools before `.run()` | Pass tools into `.run(tools=...)` instead |
| Use `initiate_chat()` | Replaced by `agent.run()` |
| Use `AssistantAgent` or `UserProxyAgent` for new code | Use `ConversableAgent` |
| Call `result.process()` | Prints to console; use `for _ in result.events: pass` |
| Use name-exact predicates in specialists (`spec.name == "..."`) | Use `spec.category == "..."` for pluggability |
| Subscript `llm_config["config_list"]` | Use attribute: `llm_config.config_list` |

### Always Do

| Rule | Reason |
|---|---|
| Register new tools with `category=` | Required for specialist routing |
| Use `uv run` for Python commands | Ensures the correct virtualenv |
| Import from `autogen` (not `pyautogen`) | Project uses `ag2` package which exposes `autogen` |
| Keep `app/chem/` pure (no AG2) | Allows REST endpoints and agents to share chem logic |

---

## 12. Version History Summary

| Version | Key Change |
|---|---|
| 2.2.0 | Category-based specialist predicates; single `ConversableAgent` router; `LLMConfig` migration |
| 2.1.0 | Full AG2 migration (`ConversableAgent` throughout); Redis dev environment; bug fixes |
| 2.0.0 | Three-panel IDE frontend; 12 chemistry tool forms; Actionable UI |
| 1.x | Initial multi-agent prototype |

Full details in [CHANGELOG.md](CHANGELOG.md).
