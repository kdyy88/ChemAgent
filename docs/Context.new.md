# ChemAgent — 新对话上下文（LangGraph 版，截至 2026-03-29）

> 本文档是给下一个对话 session 的完整交接上下文。将本文全文粘贴到新对话开头即可让 AI 无缝接续开发。

---

## 1. 项目概述

**ChemAgent** 是面向化学场景的全栈多智能体项目，后端以 **LangGraph 1.1.3** 编排 5 个节点，Frontend 通过 **SSE** 实时接收推理过程和分子 artifact。

- 后端：`/home/administrator/chem-agent-project/backend/`
- 前端：`/home/administrator/chem-agent-project/frontend/`
- 端口：后端 **8000**，前端 **3000**

---

## 2. 技术栈（当前生效版本）

| 组件 | 版本 / 配置 |
|---|---|
| LangGraph | 1.1.3 |
| langchain-openai | 1.1.12，`use_responses_api=True`，`reasoning={"effort": "minimal"}` |
| LLM | DMXAPI，`base_url=https://www.dmxapi.cn/v1`，model=`gpt-5` |
| FastAPI | 当前版本，port 8000 |
| RDKit | via `rdkit` package |
| Open Babel | via `openbabel-wheel` |
| Next.js | 15，port 3000 |
| Python 包管理 | `uv`（`uv run` 执行所有 Python 命令）|

**重要：** `config.py` 会自动规范化 `OPENAI_BASE_URL`，将 `/responses`、`/chat/completions` 等后缀剥离，langchain-openai 会自动拼接 `/responses`（Responses API）。

---

## 3. LangGraph 5 节点拓扑

```
START
  │
  ▼
supervisor ─────────────────────────────────────────────► END
  │                                                         ▲
  ├─► visualizer_node → shadow_lab_node ───────────────────┤
  │                           │ (validation error)          │
  ├─► analyst_node ───────────┤                             │
  │                           │                             │
  └─► prep_node ──────────────┤                             │
                              └─► supervisor (自纠正, ≤3 次)─┘
```

| 节点 | 职责 | LLM 流式 |
|---|---|---|
| `supervisor` | 结构化路由（`RouteDecision` Pydantic 输出）| 否 |
| `visualizer` | 2D 结构图渲染 | 是 |
| `analyst` | 理化性质、描述符、偏电荷 | 是 |
| `prep` | 3D 构象、PDBQT、格式转换 | 是 |
| `shadow_lab` | RDKit SMILES 确定性校验 | 否 |

`RouteDecision.next` 的合法值：`"visualizer"` / `"analyst"` / `"prep"` / `"END"`

---

## 4. 13 个 Agent @tool 封装

### RDKit 工具：`backend/app/agents/lg_tools.py`（7 个）

| 工具名 | 调用核心函数 | 分配节点 |
|---|---|---|
| `tool_validate_smiles` | `validate_smiles` | analyst, visualizer |
| `tool_compute_descriptors` | `compute_descriptors` | analyst |
| `tool_compute_similarity` | `compute_similarity` | analyst |
| `tool_substructure_match` | `substructure_match` | analyst |
| `tool_murcko_scaffold` | `murcko_scaffold` | analyst |
| `tool_strip_salts` | `strip_salts_and_neutralize` | analyst |
| `tool_render_smiles` | `mol_to_png_b64` | visualizer |

导出：`ALL_TOOLS`（7个）、`ANALYST_TOOLS`（6个，不含 render）、`VISUALIZER_TOOLS`（2个）

### Open Babel 工具：`backend/app/tools/babel/prep.py`（6 个）

| 工具名 | 调用核心函数 | 分配节点 |
|---|---|---|
| `tool_build_3d_conformer` | `build_3d_conformer` | prep |
| `tool_prepare_pdbqt` | `prepare_pdbqt` | prep |
| `tool_convert_format` | `convert_format` | prep |
| `tool_list_formats` | `list_supported_formats` | prep |
| `tool_compute_mol_properties` | `compute_mol_properties` | analyst |
| `tool_compute_partial_charges` | `compute_partial_charges` | analyst |

导出：`ALL_BABEL_TOOLS`（6个）、`PREP_TOOLS`（4个）、`BABEL_ANALYSIS_TOOLS`（2个）

**关键设计**：`_to_text()` 辅助函数从 LLM JSON 中剥离 `sdf_content`、`pdbqt_content`、`zip_bytes`、`atoms` 等大字段，`prep_node` 在 artifact dispatch 时通过检查 `data.get("type") == "conformer_3d"` 等条件，**重新调用 `babel_ops` 核心函数**获取完整内容。

---

## 5. 关键文件索引

| 文件 | 职责 |
|---|---|
| `backend/app/agents/graph.py` | ★ LangGraph StateGraph：5 节点定义、路由、工具绑定、artifact dispatch |
| `backend/app/agents/lg_tools.py` | 7 个 RDKit @tool 封装 |
| `backend/app/tools/babel/prep.py` | 6 个 Open Babel @tool 封装 |
| `backend/app/api/sse_chat.py` | POST /api/chat/stream SSE 流主入口 |
| `backend/app/chem/rdkit_ops.py` | RDKit 纯计算层（不依赖 FastAPI/Agent）|
| `backend/app/chem/babel_ops.py` | Open Babel 纯计算层 |
| `backend/app/agents/config.py` | LLM 配置加载（DMXAPI base_url 规范化）|
| `backend/tests/test_sse_stream.py` | SSE 冒烟测试脚本 |
| `frontend/hooks/useChemAgent.ts` | SSE hook（取代旧 WebSocket hook）|
| `frontend/lib/types.ts` | 前端类型定义（含 artifact kinds）|

---

## 6. `graph.py` 内部符号表

| 符号 | 类型 | 说明 |
|---|---|---|
| `ChemMVPState` | TypedDict | 全图共享状态（messages, active_smiles, artifacts, …）|
| `RouteDecision` | Pydantic BaseModel | Supervisor 结构化输出；`next` 字段驱动路由 |
| `_build_chat_llm()` | 函数 | 构建 ChatOpenAI（Responses API）|
| `supervisor_node()` | async 节点 | with_structured_output(RouteDecision) |
| `visualizer_node()` | async 节点 | bind_tools(VISUALIZER_TOOLS) |
| `analyst_node()` | async 节点 | bind_tools(ANALYST_TOOLS + BABEL_ANALYSIS_TOOLS) |
| `prep_node()` | async 节点 | bind_tools(PREP_TOOLS)；含 artifact dispatch |
| `shadow_lab_node()` | async 节点 | 纯 RDKit 校验，无 LLM |
| `route_after_supervisor()` | 条件函数 | 读 `state["next_node"]` → 路由字符串 |
| `build_graph()` | 函数 | 组装并编译 StateGraph |
| `_ANALYST_ALL_TOOLS` | list | ANALYST_TOOLS + BABEL_ANALYSIS_TOOLS |

---

## 7. SSE 协议

**端点**：`POST /api/chat/stream`

**请求体**：
```json
{
  "session_id": "uuid-string",
  "message": "用户消息",
  "smiles": "CC(=O)Oc1ccccc1C(=O)O"  // 可选
}
```

**事件类型**（`event:` 字段）：

| 事件 | data 字段 |
|---|---|
| `node_start` | `{"node": "analyst"}` |
| `node_end` | `{"node": "analyst"}` |
| `token` | `{"content": "..."}` |
| `tool_call` | `{"name": "tool_compute_descriptors", "args": {...}}` |
| `tool_result` | `{"name": "...", "content": "..."}` |
| `artifact` | `{"kind": "descriptors", "title": "...", "data": {...}}` |
| `done` | `{}` |
| `error` | `{"message": "..."}` |

**Artifact kind 枚举**：`structure_image` / `descriptors` / `conformer_3d` / `pdbqt` / `format_conversion`

**_STREAMING_NODES**：`{"supervisor", "visualizer", "analyst", "prep"}`  
**_LIFECYCLE_NODES**：`{"supervisor", "visualizer", "analyst", "prep", "shadow_lab"}`

---

## 8. Responses API Token 提取（重要 Bug 修复，已生效）

DMXAPI Responses API 返回的 `chunk.content` 是列表，不是字符串：
```python
# sse_chat.py 中的 token 提取逻辑
tok = ev.get("content", "")
if isinstance(tok, list):
    tok = "".join(
        b.get("text", "") if isinstance(b, dict) else str(b) for b in tok
    )
```
同样的处理也在 `tests/test_sse_stream.py` 中生效。

---

## 9. 冒烟测试命令

后端需运行中（port 8000）：

```bash
cd /home/administrator/chem-agent-project/backend

# 1. 阿司匹林 Lipinski（analyst 节点）
uv run python tests/test_sse_stream.py "分析阿司匹林的成药性"

# 2. 布洛芬 3D 构象（prep 节点）
uv run python tests/test_sse_stream.py \
  --smiles "CC(C)Cc1ccc(cc1)C(C)C(=O)O" \
  "为布洛芬生成 3D 构象"

# 3. 布洛芬偏电荷（analyst + babel 工具）
uv run python tests/test_sse_stream.py \
  --smiles "CC(C)Cc1ccc(cc1)C(C)C(=O)O" \
  "计算布洛芬的 Gasteiger 偏电荷"

# 4. 3D 构象 + PDBQT 联合（prep 节点，两个 artifact）
uv run python tests/test_sse_stream.py \
  --smiles "CC(C)Cc1ccc(cc1)C(C)C(=O)O" \
  "为布洛芬生成 3D 构象，准备 PDBQT 对接文件"
```

---

## 10. 已验证结果

| 场景 | 节点 | Artifact | 结果 |
|---|---|---|---|
| 阿司匹林 Lipinski | analyst | `descriptors` | ✅ 346 事件 17.4s |
| 布洛芬 3D 构象 | prep | `conformer_3d` | ✅ 372 事件 16.6s |
| 布洛芬偏电荷 | analyst | — | ✅ 637 事件 17.3s |
| 布洛芬 3D + PDBQT | prep | `conformer_3d` + `pdbqt` | ✅ 双 artifact |

---

## 11. 工具覆盖审计结论

**RDKit：** 6 个 REST 端点全部有对应 `@tool`；额外 1 个仅 Agent 工具（`tool_render_smiles`）。覆盖率 100%。

**Open Babel：** 6 个可用于 tool-calling 的 ops 函数全部封装。`sdf_split` / `sdf_merge` 因二进制 I/O 不适合 tool-calling，**有意保留为 REST-only**，不计入缺口。覆盖率 100%（按设计）。

---

## 12. 插拔式对接新化学工具

新化学软件（Smina、xTB、ORCA、ADMET 工具等）接入路径：

1. `backend/app/chem/<software>_ops.py` — 纯计算，无框架依赖
2. `backend/app/api/<software>_api.py` — REST 端点（可选，先测通）
3. `backend/app/tools/<software>/<module>.py` — `@tool` 封装
4. `backend/app/agents/graph.py` — 追加：import → `_node()` 函数 → `RouteDecision.next` 枚举 → `build_graph()` 注册
5. `backend/app/api/sse_chat.py` — 将新节点名加入 `_STREAMING_NODES` / `_LIFECYCLE_NODES`

每步均不修改现有文件中的现有代码，**只追加**。

---

## 13. 待办事项（按优先级）

| 优先级 | 任务 |
|---|---|
| 高 | 前端接入 NGL Viewer/3Dmol.js 渲染 `conformer_3d` SDF |
| 高 | 创建 `BabelResultCard.tsx` 展示 PDBQT 下载链接 |
| 中 | LangGraph `SqliteSaver` Checkpointer（跨请求多轮记忆）|
| 中 | PubChem 检索工具（名称/CID → SMILES）|
| 中 | LangGraph `Send` API 并行 fan-out（analyst + visualizer 同时）|
| 低 | Smina/GNINA `docking_node` |
| 低 | ADMET 工具（SwissADME / pkCSM）|
| 低 | Redis-backed Session 持久化 |

---

## 14. 文档位置

| 文档 | 路径 |
|---|---|
| 本上下文文档 | `docs/Context.new.md` |
| API 文档 | `docs/API.md` |
| 架构文档 | `docs/ARCHITECTURE.md` |
| 文件职责索引 | `docs/SOURCE_MAP.md` |
| README | `README.md` |
