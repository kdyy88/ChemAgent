# ARCHITECTURE

本文档描述 ChemAgent 当前（LangGraph 时代）的系统架构、运行链路、模块边界与演进规划。

配套文档：
- [SOURCE_MAP.md](SOURCE_MAP.md) — 源码职责地图与文件定位索引
- [API.md](API.md) — REST + SSE 端点参考

---

## 1. 架构目标

1. **降低化学幻觉** — 智能体优先调用确定性的 RDKit / Open Babel 工具，而不是直接臆测结构或数值。
2. **全链路可解释** — 前端通过 SSE 实时展示每个节点的工具调用、中间推理和最终回答。
3. **抗幻觉防火墙** — Shadow Lab 节点用纯 RDKit 对所有节点产生的 SMILES 做化合价校验，校验失败触发自我修正循环。
4. **平滑扩展工具生态** — 新工具以 `@tool` 装饰器注册，加入对应节点工具列表即可，无需改动核心流程。

---

## 2. 技术栈

| 层 | 技术 |
|----|----|
| 前端 | Next.js 15 (App Router), React, Tailwind CSS, Shadcn UI, Zustand |
| 传输协议 | HTTP SSE (`text/event-stream`) via `@microsoft/fetch-event-source` |
| 后端运行时 | Python 3.12, FastAPI, uvicorn, `uv` |
| Agent 框架 | **LangGraph 1.1.3** (`StateGraph`, astream_events v2) |
| LLM 客户端 | `langchain-openai 1.1.12` (`ChatOpenAI`, Responses API) |
| LLM 服务 | DMXAPI (`https://www.dmxapi.cn/v1/responses`), model `gpt-5` / `gpt-5-mini` |
| 化学引擎 | RDKit 2025, Open Babel 3.1 (`openbabel-wheel`) |
| 任务队列 | ARQ + Redis (REST 化学计算端点专用，不涉及 Agent) |

---

## 3. 系统分层

```text
┌─────────────────────────────────────────────────────────┐
│                        Frontend                         │
│  Next.js / React / Zustand                              │
│  useSSEChemAgent hook  ←  @microsoft/fetch-event-source │
│  ArtifactGallery / MessageList / ThinkingLog            │
└───────────────────────────┬─────────────────────────────┘
                            │  POST /api/chat/stream  (SSE)
                            │  POST /api/rdkit/*      (REST)
                            │  POST /api/babel/*      (REST)
                            ▼
┌─────────────────────────────────────────────────────────┐
│                      API Layer                          │
│  FastAPI                                                │
│  sse_chat.py   → astream_events → SSE 帧               │
│  rdkit_api.py  → 直接调用 rdkit_ops (同步)               │
│  babel_api.py  → ARQ 任务队列 → Redis Worker            │
└───────────────────────────┬─────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│                  LangGraph Agent Graph                  │
│                                                         │
│   START → supervisor ─────────────────────────► END     │
│                │                                 ▲      │
│                ├─► visualizer → shadow_lab ──────┤      │
│                ├─► analyst   → shadow_lab ───────┤      │
│                └─► prep      → shadow_lab ───────┘      │
│                         │ (validation error)             │
│                         └─► supervisor (自我修正, ≤3次)  │
└───────────────────────────┬─────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│              LangGraph @tool 层                          │
│  app/agents/lg_tools.py   — 7 个 RDKit 工具             │
│  app/tools/babel/prep.py  — 6 个 Open Babel 工具        │
└───────────────────────────┬─────────────────────────────┘
                            │
              ┌─────────────┴──────────────┐
              ▼                            ▼
┌─────────────────────┐        ┌──────────────────────────┐
│  app/chem/rdkit_ops │        │  app/chem/babel_ops       │
│  (纯 RDKit 计算)     │        │  (纯 Open Babel 计算)     │
└─────────────────────┘        └──────────────────────────┘
```

### 严格依赖方向

```
外部库 (rdkit, openbabel, openai)
  ↓
app/chem/          ← 纯计算，无 HTTP / Agent 依赖
  ↙         ↘
app/api/   app/tools/  ← 互不依赖，只调用 chem/
              ↓
app/agents/lg_tools.py / graph.py  ← 不直接执行计算
              ↓
app/api/sse_chat.py    ← 只调用 compiled_graph
```

---

## 4. LangGraph 图拓扑

### 4.1 节点职责

| 节点 | 类型 | 工具集 | 职责 |
|------|------|--------|------|
| `supervisor` | 结构化输出 LLM | — | 解析用户意图，路由到 visualizer / analyst / prep / END |
| `visualizer` | 工具调用 LLM | `VISUALIZER_TOOLS` (RDKit) | 2D 结构图渲染 |
| `analyst` | 工具调用 LLM | `ANALYST_TOOLS` (RDKit) + `BABEL_ANALYSIS_TOOLS` | Lipinski/QED/TPSA/相似度/骨架/部分电荷 |
| `prep` | 工具调用 LLM | `PREP_TOOLS` (Open Babel) | 格式转换 / 3D 构象 / PDBQT 对接准备 |
| `shadow_lab` | 纯确定性 RDKit | — | SMILES 化合价校验 + 自我修正触发 |

### 4.2 工具清单

#### RDKit 工具（`app/agents/lg_tools.py`）

| 工具 | 核心函数 | 说明 |
|------|---------|------|
| `tool_validate_smiles` | `rdkit_ops.validate_smiles` | 校验 + 规范化 SMILES |
| `tool_compute_descriptors` | `rdkit_ops.compute_descriptors` | Lipinski Ro5 + QED + SA + TPSA + 全量描述符 |
| `tool_compute_similarity` | `rdkit_ops.compute_similarity` | Tanimoto 相似度（ECFP4 Morgan 指纹） |
| `tool_substructure_match` | `rdkit_ops.substructure_match` | SMARTS 子结构搜索 + PAINS 筛查 |
| `tool_murcko_scaffold` | `rdkit_ops.murcko_scaffold` | Bemis-Murcko 骨架提取 |
| `tool_strip_salts` | `rdkit_ops.strip_salts_and_neutralize` | 盐型处理与去离子化 |
| `tool_render_smiles` | `rdkit_ops.mol_to_png_b64` | 2D 结构图（base64 PNG） |

#### Open Babel 工具（`app/tools/babel/prep.py`）

| 工具 | 核心函数 | 说明 |
|------|---------|------|
| `tool_convert_format` | `babel_ops.convert_format` | 任意 110+ 格式互转（SMILES↔SDF/MOL2/PDB/InChI/InChIKey…） |
| `tool_build_3d_conformer` | `babel_ops.build_3d_conformer` | SMILES → MMFF94/UFF 力场 3D 构象（含能量） |
| `tool_prepare_pdbqt` | `babel_ops.prepare_pdbqt` | SMILES → 加氢(pH) → 3D → Gasteiger 电荷 → PDBQT |
| `tool_compute_mol_properties` | `babel_ops.compute_mol_properties` | Open Babel 分子属性（精确质量、分子式、成键数…） |
| `tool_compute_partial_charges` | `babel_ops.compute_partial_charges` | 逐原子部分电荷（Gasteiger/MMFF94/QEq/EEM） |
| `tool_list_formats` | `babel_ops.list_supported_formats` | 列出所有受支持格式代码 |

### 4.3 状态结构 `ChemMVPState`

```python
class ChemMVPState(TypedDict):
    messages:          Annotated[list[BaseMessage], add_messages]  # 消息历史（合并追加）
    active_smiles:     str | None                                  # 当前画布 SMILES（末写优先）
    validation_errors: Annotated[list[str], operator.add]          # Shadow Lab 累计错误
    artifacts:         Annotated[list[dict], operator.add]         # 累计产物（图像/文件/JSON）
    next_node:         str | None                                  # Supervisor 路由信号
    iteration_count:   int                                         # 防止自我修正无限循环
```

### 4.4 Supervisor 路由逻辑

Supervisor 使用 `with_structured_output(RouteDecision)` — 纯结构化输出，无字符串解析：

```python
class RouteDecision(BaseModel):
    next: Literal["visualizer", "analyst", "prep", "END"]
    active_smiles: str | None
    compound_name:  str | None
    reasoning:      str   # 一句话中文理由
```

### 4.5 Shadow Lab 防幻觉机制

```
Worker 完成
   ↓
shadow_lab_node
   ├─ active_smiles is None → pass-through → END
   ├─ Chem.MolFromSmiles(sanitize=True) → None  → 注入 HumanMessage + dispatch shadow_lab_error
   ├─ 化合价异常  → 注入 HumanMessage + dispatch shadow_lab_error
   └─ 合法 → 更新为规范化 SMILES → END

校验失败时：
  next_node = "supervisor"
  iteration_count < MAX_ITERATIONS (3)?
    是 → 路由回 supervisor（自我修正）
    否 → 强制 END（防无限循环）
```

---

## 5. SSE 事件协议

前后端之间传输的是**结构化 JSON 事件**，而非拼接日志文本。

### 5.1 端点

```
POST /api/chat/stream
Content-Type: application/json
→ text/event-stream
```

### 5.2 请求体

```json
{
  "message":      "计算阿司匹林的 Lipinski 性质",
  "session_id":   "optional-uuid",
  "turn_id":      "client-uuid",
  "active_smiles": "CC(=O)Oc1ccccc1C(=O)O"
}
```

### 5.3 事件类型

| type | 触发时机 | 关键字段 |
|------|---------|---------|
| `run_started` | 连接建立立即 | `message` |
| `node_start` | 节点开始执行 | `node` |
| `token` | LLM 流式 token | `node`, `content` |
| `tool_start` | `@tool` 开始执行 | `tool`, `input` |
| `tool_end` | `@tool` 完成 | `tool`, `output` |
| `artifact` | 产物就绪（图像/SDF/PDBQT/JSON） | `kind`, `data`, `title` |
| `shadow_error` | Shadow Lab 检测到非法 SMILES | `smiles`, `error` |
| `node_end` | 节点执行完毕 | `node` |
| `done` | 图运行完毕 | — |
| `error` | 未处理异常 | `error`, `traceback` |

### 5.4 Artifact kind 枚举

| kind | mime_type | 说明 |
|------|-----------|------|
| `molecule_image` | `image/png` | 2D 结构图，base64 编码 |
| `descriptors` | `application/json` | Lipinski/QED/TPSA 等描述符 JSON |
| `conformer_3d` | `chemical/x-mdl-sdfile` | MMFF94/UFF 优化 SDF 文件 |
| `pdbqt` | `chemical/x-pdbqt` | AutoDock PDBQT 对接配体 |
| `format_conversion` | `text/plain` | 格式转换输出（InChI、MOL2、PDB 等） |

---

## 6. LLM 配置

所有节点共用同一 `_build_chat_llm()` 工厂，调用 DMXAPI Responses API：

```python
ChatOpenAI(
    model            = os.environ["OPENAI_MODEL"],   # gpt-5
    api_key          = os.environ["OPENAI_API_KEY"],
    base_url         = "https://www.dmxapi.cn/v1",   # 规范化后（去掉 /responses 后缀）
    use_responses_api= True,                          # → POST /v1/responses
    reasoning        = {"effort": "minimal"},         # 最低推理强度，降低延迟+成本
    streaming        = True,
)
```

Supervisor 附加 `.with_structured_output(RouteDecision)`；Worker 节点附加 `.bind_tools(TOOLS_LIST)`。

---

## 7. 扩展指南

### 7.1 新增 LangGraph 工具

1. 在 `app/chem/<lib>_ops.py` 中实现纯计算函数（无框架依赖）。
2. 在 `app/agents/lg_tools.py`（RDKit）或 `app/tools/babel/prep.py`（Open Babel）中添加 `@tool` 装饰器包装。
3. 将新工具加入 `graph.py` 中对应节点的工具列表。
4. 更新节点系统提示，告知 LLM 新工具的用途。

### 7.2 新增节点

1. 在 `graph.py` 中定义 `async def new_node(state: ChemMVPState) -> dict`。
2. 将新的值加入 `RouteDecision.next` Literal。
3. 更新 `_SUPERVISOR_SYSTEM` 路由规则。
4. 在 `build_graph()` 中注册节点 + 连接 Shadow Lab 出边。
5. 更新 `sse_chat.py` 的 `_STREAMING_NODES` 和 `_LIFECYCLE_NODES` 集合。

### 7.3 新增 Artifact 类型

1. 在工作节点的 agentic loop 中调用 `adispatch_custom_event("artifact", {...})`，设置 `kind` 字段。
2. 前端 `ArtifactRenderer.tsx` 在 `kind` 分支中新增对应渲染逻辑。

---

## 8. 当前限制与演进路线

| 限制 | 说明 |
|------|------|
| 无跨轮记忆 | 每个 POST 独立 LangGraph 状态，无 Checkpointer |
| Session 无持久化 | 服务重启后无上下文恢复 |
| 幻觉防护仅覆盖 SMILES | Shadow Lab 只校验化合价；数值幻觉未覆盖 |
| 并行 Worker 未实现 | 每次只路由到一个节点；analyst+visualizer 联动需两轮 |

### 近期演进方向

- **LangGraph Checkpointer** — `SqliteSaver` / `RedisSaver`，实现跨请求多轮记忆
- **并行 Fan-out** — Supervisor 同时路由 analyst + visualizer（`Send` API）
- **xTB / GNINA** — 量化化学与深度学习对接节点
- **Smina 对接节点** — `chem/smina_ops.py` → `tools/smina/` → `docking_node`
- **ADMET 预测** — SwissADME / pkCSM REST API 接入
- **LangSmith 可观测性** — tool 延迟 / 成功率统计 + 完整 trace
