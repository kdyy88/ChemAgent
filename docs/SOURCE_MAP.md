# SOURCE_MAP

本文件是 ChemAgent 代码库的职责地图，面向维护者和新加入的开发者。

---

## 1. 核心数据流

```
用户输入
  ↓
frontend/app/page.tsx → components/chat/ChatInput.tsx
  ↓
frontend/hooks/useSSEChemAgent.ts  (@microsoft/fetch-event-source)
  ↓  POST /api/chat/stream
backend/app/api/sse_chat.py
  ↓  compiled_graph.astream_events(version="v2")
backend/app/agents/graph.py  (StateGraph)
  ├─► supervisor_node   → RouteDecision (structured output)
  ├─► visualizer_node  → RDKit 2D 渲染工具
  ├─► analyst_node     → RDKit + Open Babel 分析工具
  ├─► prep_node        → Open Babel 格式/3D/对接工具
  └─► shadow_lab_node  → RDKit 纯化合价校验
  ↓
SSE 事件帧 → useSSEChemAgent → Zustand stores
  ↓
MessageList / ArtifactGallery / ThinkingLog
```

---

## 2. 后端文件地图

### `backend/app/main.py`
应用入口。注册所有 APIRouter，启动 FastAPI 实例。

### `backend/app/api/`

| 文件 | 路由前缀 | 职责 |
|------|----------|------|
| `sse_chat.py` | `POST /api/chat/stream` | LangGraph SSE 端点；驱动 `astream_events(v2)`；将事件映射为 SSE 帧 |
| `rdkit_api.py` | `/api/rdkit/*` | 6 个 RDKit REST 端点（同步，直接调用 rdkit_ops） |
| `babel_api.py` | `/api/babel/*` | 4 个 Open Babel REST 端点（ARQ 异步任务队列） |
| `protocol.py` | — | Pydantic 请求/响应模型（REST 层用） |

### `backend/app/agents/`

| 文件 | 职责 |
|------|------|
| `graph.py` | **核心**：`ChemMVPState`, 5 个节点函数, 条件边, `compiled_graph = build_graph().compile()` |
| `lg_tools.py` | 7 个 RDKit `@tool` 包装；导出 `ALL_TOOLS`, `ANALYST_TOOLS`, `VISUALIZER_TOOLS` |
| `config.py` | `_load_environment()` (.env 加载，级联搜索)；`build_llm_config()` |

**`graph.py` 内部结构一览：**

| 符号 | 类型 | 说明 |
|------|------|------|
| `ChemMVPState` | TypedDict | 全局状态，带 `add_messages` / `operator.add` reducer |
| `RouteDecision` | Pydantic BaseModel | Supervisor 结构化输出；`next: Literal["visualizer","analyst","prep","END"]` |
| `_build_chat_llm()` | 工厂函数 | 构建 `ChatOpenAI(use_responses_api=True, reasoning={"effort":"minimal"})` |
| `supervisor_node` | async node | 路由决策；`.with_structured_output(RouteDecision)` |
| `visualizer_node` | async node | 2D 渲染；绑定 `VISUALIZER_TOOLS` |
| `analyst_node` | async node | 理化分析；绑定 `_ANALYST_ALL_TOOLS`（RDKit + Babel） |
| `prep_node` | async node | 格式/3D/对接；绑定 `PREP_TOOLS` |
| `shadow_lab_node` | async node | 纯 RDKit 化合价校验，永不调用 LLM |
| `route_after_supervisor` | 条件边函数 | `"END"` → `END` sentinel；其余直传节点名 |
| `route_after_shadow_lab` | 条件边函数 | 失败且 `iteration_count < 3` → 回 supervisor；否则 END |
| `compiled_graph` | 模块级常量 | `build_graph().compile()`，进程内复用 |

### `backend/app/tools/babel/`

| 文件 | 职责 |
|------|------|
| `prep.py` | 6 个 Open Babel `@tool` 包装；导出 `ALL_BABEL_TOOLS`, `PREP_TOOLS`, `BABEL_ANALYSIS_TOOLS` |
| `__init__.py` | 统一重导出（`from app.tools.babel import PREP_TOOLS, ...`） |

**`prep.py` 工具清单：**

| 工具 | 参数 | 核函数 |
|------|------|--------|
| `tool_convert_format` | `molecule_str, input_fmt, output_fmt` | `babel_ops.convert_format` |
| `tool_build_3d_conformer` | `smiles, name="", forcefield="mmff94", steps=500` | `babel_ops.build_3d_conformer` |
| `tool_prepare_pdbqt` | `smiles, name="", ph=7.4` | `babel_ops.prepare_pdbqt` |
| `tool_compute_mol_properties` | `smiles` | `babel_ops.compute_mol_properties` |
| `tool_compute_partial_charges` | `smiles, method="gasteiger"` | `babel_ops.compute_partial_charges` |
| `tool_list_formats` | `direction="both"` | `babel_ops.list_supported_formats` |

### `backend/app/chem/`

| 文件 | 职责 | 对外接口 |
|------|------|---------|
| `rdkit_ops.py` | 纯 RDKit 计算 | `validate_smiles`, `compute_descriptors`, `compute_similarity`, `substructure_match`, `murcko_scaffold`, `strip_salts_and_neutralize`, `mol_to_png_b64` |
| `babel_ops.py` | 纯 Open Babel 计算 | `convert_format`, `build_3d_conformer`, `prepare_pdbqt`, `compute_mol_properties`, `compute_partial_charges`, `compute_mol_properties`, `list_supported_formats`, `sdf_split`, `sdf_merge` |

`app/chem/` 零框架依赖，可在任何上下文中单独测试。

### `backend/app/core/`

| 文件 | 职责 |
|------|------|
| `tooling.py` | `ToolSpec`, `ToolArtifact`, `ToolExecutionResult`, `ToolRegistry`（REST 层用，已移除 AG2 适配） |
| `network.py` | HTTP 客户端工具（PubChem 检索等） |
| `task_queue.py` | ARQ 任务定义（babel REST Worker） |
| `task_bridge.py` | ARQ 任务状态查询桥接 |

### `backend/tests/`

| 文件 | 职责 |
|------|------|
| `test_sse_stream.py` | CLI 烟雾测试；彩色输出；支持 `--smiles` / `--url` 参数。运行：`uv run python tests/test_sse_stream.py [--smiles SMILES] "消息"` |

---

## 3. 前端文件地图

### `frontend/hooks/useSSEChemAgent.ts`
主业务 hook。调用 `POST /api/chat/stream`，消费 SSE 事件，维护 `turns` 列表（每轮含 `assistantText`, `artifacts`, `toolCalls`, `shadowErrors`, `activeNode`）。

### `frontend/lib/sse-types.ts`
所有 SSE 事件的 TypeScript 类型联合（`RunStartedEvent | NodeStartEvent | TokenEvent | ToolStartEvent | ArtifactEvent | ...`）。

### `frontend/lib/chem-api.ts`
REST API 客户端（rdkit / babel 端点 fetch 函数）。

### `frontend/lib/types.ts`
共享 TypeScript 类型（`MoleculeDescriptors`, `LipinskiResult`, `ArtifactKind`…）。

### `frontend/store/`

| 文件 | 职责 |
|------|------|
| `chatStore.ts` | SSE 轮次状态（与 `useSSEChemAgent` 配合） |
| `workspaceStore.ts` | 画布 SMILES、活跃分子、工具面板状态 |

### `frontend/components/chat/`

| 文件 | 职责 |
|------|------|
| `MessageList.tsx` | 渲染 turns 列表 |
| `MessageBubble.tsx` | 单条消息（Markdown 渲染） |
| `ThinkingLog.tsx` | 工具调用链路展示（节点徽章） |
| `ArtifactGallery.tsx` | 产物画廊（按 turn 聚合） |
| `ArtifactRenderer.tsx` | 单个产物渲染（按 `kind` 分支：图像 / JSON / 文件下载） |
| `ChatInput.tsx` | 输入框 + 发送 |
| `MoleculeCard.tsx` | 分子信息卡（结构图 + 描述符） |
| `LipinskiCard.tsx` | Lipinski Ro5 展示卡 |
| `BabelResultCard.tsx` | Open Babel 结果卡（格式转换 / 3D / PDBQT） |

---

## 4. 配置与环境

### `.env`（项目根目录）

```env
OPENAI_API_KEY="sk-..."
OPENAI_BASE_URL="https://www.dmxapi.cn/v1/responses"   # config.py 会去掉 /responses
OPENAI_MODEL=gpt-5
FAST_MODEL=gpt-5-mini
```

`config.py._load_environment()` 级联搜索：`backend/.env` → 项目根 `.env` → `CWD/.env`。

### `pyproject.toml` 核心依赖

```toml
langgraph>=1.1.3
langchain-openai>=1.1.12
langchain-core>=1.2.23
fastapi>=0.135.1
uvicorn>=0.41.0
rdkit>=2025.9.6
openbabel-wheel>=3.1.1.23
python-dotenv>=1.1.1
arq>=0.26
redis[hiredis]>=5.0
```

---

## 5. 关键运行命令

```bash
# 后端开发服务（热重载）
cd backend; uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 前端开发服务
cd frontend; pnpm dev

# 烟雾测试（需要服务运行）
cd backend
uv run python tests/test_sse_stream.py "计算阿司匹林的 Lipinski 性质" --smiles "CC(=O)Oc1ccccc1C(=O)O"
uv run python tests/test_sse_stream.py "生成布洛芬的 3D 构象并输出 SDF" --smiles "CC(C)Cc1ccc(cc1)C(C)C(=O)O"
uv run python tests/test_sse_stream.py "把阿司匹林 SMILES 转换为 InChIKey" --smiles "CC(=O)Oc1ccccc1C(=O)O"
```

---

## 6. 已删除的 AG2 文件（破坏性更新记录）

以下文件在 LangGraph 迁移时删除，**不得恢复**：

| 删除文件 | 原职责 |
|----------|--------|
| `app/api/chat.py` | WebSocket 入口（AG2） |
| `app/api/event_bridge.py` | AG2 事件桥接 |
| `app/api/sessions.py` | AG2 session 管理 |
| `app/api/runtime.py` | AG2 运行期模型 |
| `app/agents/manager.py` | AG2 Manager agent |
| `app/agents/factory.py` | AG2 agent 工厂 |
| `app/agents/specialists/analyst.py` | AG2 Analyst specialist |
| `app/agents/specialists/researcher.py` | AG2 Researcher specialist |
| `app/agents/specialists/visualizer.py` | AG2 Visualizer specialist |

替代关系：

| 旧（AG2） | 新（LangGraph） |
|-----------|----------------|
| WebSocket `/api/chat/ws` | SSE `POST /api/chat/stream` |
| 3 个 AG2 Specialist | 4 个 LangGraph 节点（visualizer / analyst / prep / shadow_lab） |
| 手写事件桥 `event_bridge.py` | `astream_events(version="v2")` 原生流 |
| `tool_registry.register()` | `@tool` + 节点工具列表 |
