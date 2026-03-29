# ChemAgent

ChemAgent 是一个面向化学场景的全栈智能体项目，目标是通过**权威检索 + 结构化工具调用 + 可解释流式过程展示**，尽量减少化学幻觉，并为后续分子分析工具扩展提供稳定底座。

当前版本已完成：
- 后端**三层解耦架构**：纯计算层（`chem/`）→ HTTP 层（`api/`）→ 智能体工具层（`tools/`）
- **LangGraph 多智能体编排**（Supervisor + 3 Worker + Shadow Lab 共 5 节点）
- **13 个 LangGraph `@tool` 封装**：7 个 RDKit 工具 + 6 个 Open Babel 工具，全部供 Agent 按需调用
- **RDKit 与 Open Babel 的 14 大 REST API**：覆盖分子验证、格式转换、3D 构象、PDBQT 对接预处理等
- 结构化 SSE 流式协议（`/api/chat/stream`），含 artifact 事件分发
- 前端白盒推理展示与通用 artifact 渲染

---

## 1. 项目目标

ChemAgent 聚焦三个核心问题：

1. **减少化学幻觉**  
   不直接"猜结构"，而是通过 RDKit Shadow Lab 校验每一个 SMILES，并优先通过工具层调用权威计算引擎。

2. **让智能体过程透明**  
   前端会展示节点路由、工具调用链、最终回答，而不是只返回黑盒结论。

3. **为后续工具生态做准备**  
   采用插拔式架构：新增化学软件只需新增 `chem/` 计算层 + `tools/` 封装层 + 在 `graph.py` 注册节点，**不修改任何现有文件**。

---

## 2. 技术栈

### 前端
- Next.js 15
- React 19
- TypeScript
- Zustand
- Tailwind CSS 4
- shadcn/ui

### 后端
- FastAPI
- **LangGraph 1.1.3**（替换原 AG2/AutoGen）
- **langchain-openai 1.1.12**（`use_responses_api=True` + Responses API）
- Pydantic v2
- RDKit
- **Open Babel**（`openbabel-wheel`）
- ARQ + Redis（REST 后台任务队列）

### LLM
- **DMXAPI**（OpenAI-compatible，`base_url = https://www.dmxapi.cn/v1`）
- 模型：`gpt-5`（Responses API，`reasoning={"effort": "minimal"}`）

---

## 3. 项目结构

```text
chem-agent-project/
├── .env                          # ★ 统一环境变量（本地开发 + Docker 共用）
├── .env.example                  #   环境变量模板
├── dev.sh                        #   一键本地启动脚本
├── compose.yaml                  #   Docker Compose 全栈配置
├── backend/
│   ├── app/
│   │   ├── chem/                 # ★ 纯计算核心层（不含 HTTP/Agent 依赖）
│   │   │   ├── rdkit_ops.py      #   RDKit：验证、描述符、相似度、骨架、SA Score
│   │   │   └── babel_ops.py      #   Open Babel：格式转换、3D 构象、PDBQT、电荷
│   │   ├── agents/
│   │   │   ├── config.py         #   LLM 配置加载（DMXAPI base_url 规范化）
│   │   │   ├── graph.py          # ★ LangGraph StateGraph（5 节点拓扑）
│   │   │   └── lg_tools.py       #   7 个 RDKit @tool 封装
│   │   ├── api/
│   │   │   ├── rdkit_api.py      #   POST /api/rdkit/*（6 个端点）
│   │   │   ├── babel_api.py      #   POST/GET /api/babel/*（8 个端点）
│   │   │   └── sse_chat.py       # ★ POST /api/chat/stream（SSE 主入口）
│   │   └── tools/
│   │       ├── search/
│   │       │   └── web.py        #   web_search（PubChem + Serper）
│   │       └── babel/
│   │           └── prep.py       # ★ 6 个 Open Babel @tool 封装
│   └── pyproject.toml
├── frontend/
│   ├── app/                      #   Next.js App Router
│   ├── components/chat/          #   聊天、artifact 展示、ThinkingLog 组件
│   ├── hooks/
│   │   └── useChemAgent.ts       # ★ SSE hook（取代旧 WebSocket hook）
│   └── lib/
│       ├── chem-api.ts           #   REST API 调用
│       └── types.ts              #   前端类型定义（含 artifact kinds）
├── docs/
│   ├── API.md                    #   SSE + REST 完整 API 文档
│   ├── ARCHITECTURE.md           #   LangGraph 架构详解
│   └── SOURCE_MAP.md             #   文件职责索引
└── deploy/nginx/default.conf
```

### 依赖方向（严格执行）

```
外部库（RDKit / Open Babel）
        ↓
   app/chem/          ← 纯计算，不依赖 FastAPI 或 Agent 框架
      ↙       ↘
 app/api/    app/tools/    ← 两者只调用 chem/，互不依赖
                ↓
          app/agents/      ← graph.py 从 tools/ 导入 @tool，不直接执行计算
```

新软件（如 Smina、xTB）接入时：新增 `chem/smina_ops.py` → `api/smina_api.py` → `tools/smina/` → `graph.py` 追加节点，**不修改任何现有文件**。

---

## 4. 当前能力

### REST API（14 个端点，无需 Agent 直接可用）

**RDKit 工具簇（6 个端点）：**
| 端点 | 功能 |
|---|---|
| `POST /api/rdkit/validate` | SMILES 验证与规范化 |
| `POST /api/rdkit/salt-strip` | 分子脱盐与电荷中和 |
| `POST /api/rdkit/descriptors` | 综合描述符（Lipinski Ro5 + SA Score + QED）|
| `POST /api/rdkit/similarity` | 摩根指纹 Tanimoto 相似度 |
| `POST /api/rdkit/substructure` | SMARTS 子结构搜索 + PAINS 警告 |
| `POST /api/rdkit/scaffold` | Bemis-Murcko 核心骨架提取 |

**Open Babel 工具簇（8 个端点）：**
| 端点 | 功能 |
|---|---|
| `POST /api/babel/properties` | 精确分子质量、净电荷、自旋多重度 |
| `POST /api/babel/partial-charges` | 原子偏电荷（Gasteiger/MMFF94/QEq）|
| `POST /api/babel/convert` | 格式万能转换（SMILES ↔ SDF ↔ MOL2 ↔ PDB ↔ InChI…）|
| `POST /api/babel/conformer3d` | SMILES → 力场优化 3D 构象（含能量）|
| `POST /api/babel/pdbqt` | PDBQT 对接预处理（pH 质子化 → 3D → Gasteiger 电荷）|
| `POST /api/babel/sdf-split` | 多分子 SDF 拆分 → zip 压缩包 |
| `POST /api/babel/sdf-merge` | 批量 SDF 合并为单个库文件 |
| `GET  /api/babel/formats` | 枚举所有支持的格式代码 |

详细请求/响应格式见 [docs/API.md](docs/API.md)。

### Agent 工具（13 个 `@tool`，由 LangGraph 节点按需调用）

**RDKit 工具（`app/agents/lg_tools.py`，7 个）：**
| 工具名 | 节点 | 功能 |
|---|---|---|
| `tool_validate_smiles` | analyst / visualizer | SMILES 验证与规范化 |
| `tool_compute_descriptors` | analyst | Lipinski + QED + SA Score + TPSA |
| `tool_compute_similarity` | analyst | Morgan ECFP4 Tanimoto 相似度 |
| `tool_substructure_match` | analyst | SMARTS 子结构 + PAINS |
| `tool_murcko_scaffold` | analyst | Bemis-Murcko 骨架 |
| `tool_strip_salts` | analyst | 脱盐 + 电荷中和 |
| `tool_render_smiles` | visualizer | SMILES → 2D 结构图（base64 PNG）|

**Open Babel 工具（`app/tools/babel/prep.py`，6 个）：**
| 工具名 | 节点 | 功能 |
|---|---|---|
| `tool_build_3d_conformer` | prep | SMILES → 力场优化 3D SDF（MMFF94/UFF）|
| `tool_prepare_pdbqt` | prep | SMILES → PDBQT（AutoDock/Vina/Smina）|
| `tool_convert_format` | prep | 110+ 格式互转 |
| `tool_list_formats` | prep | 枚举支持格式 |
| `tool_compute_mol_properties` | analyst | Open Babel 分子属性（与 RDKit 交叉验证）|
| `tool_compute_partial_charges` | analyst | 原子偏电荷（Gasteiger/MMFF94/QEq/EEM）|

> **注：** `sdf_split` / `sdf_merge` 涉及二进制文件 I/O，不适合 tool-calling 协议，保留为 REST-only 端点。

### SSE 事件流（`POST /api/chat/stream`）

| 事件 | 含义 |
|---|---|
| `node_start` | 节点启动（`node` 字段标明哪个节点）|
| `node_end` | 节点结束 |
| `token` | LLM 流式 token |
| `tool_call` | Agent 调用工具 |
| `tool_result` | 工具返回结果 |
| `artifact` | 独立渲染产物（结构图、描述符表、3D SDF、PDBQT）|
| `done` | 整个 turn 结束 |
| `error` | 错误事件 |

Artifact 类型（`kind` 字段）：`structure_image` / `descriptors` / `conformer_3d` / `pdbqt` / `format_conversion`

---

## 5. LangGraph 多智能体拓扑

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

| 节点 | 职责 | 工具集 |
|---|---|---|
| `supervisor` | 结构化路由（Pydantic `RouteDecision`，无 LLM 流式） | 无 |
| `visualizer` | 2D 结构图渲染 | `tool_render_smiles`, `tool_validate_smiles` |
| `analyst` | 理化性质计算 | 6 RDKit 工具 + `tool_compute_mol_properties`, `tool_compute_partial_charges` |
| `prep` | 格式转换、3D 构象、PDBQT | `tool_convert_format`, `tool_build_3d_conformer`, `tool_prepare_pdbqt`, `tool_list_formats` |
| `shadow_lab` | RDKit SMILES 确定性校验（无 LLM） | 无 |

---

## 6. 插拔式扩展方式

新接入化学软件（如 Smina、xTB、ORCA）遵循统一三步扩展路径，**无需修改任何现有文件**：

### Step 1 — 纯计算层

```python
# backend/app/chem/smina_ops.py
def dock_ligand(receptor_pdbqt: str, ligand_pdbqt: str, ...) -> dict: ...
```

### Step 2 — REST 层（可选，供直接调用测试）

```python
# backend/app/api/smina_api.py
router = APIRouter(prefix="/api/smina")
# main.py: app.include_router(smina_router)
```

### Step 3 — Agent 工具层 + 新节点

```python
# backend/app/tools/smina/dock.py
@tool
def tool_dock_ligand(receptor_pdbqt: str, ligand_pdbqt: str) -> str:
    """Dock a ligand PDBQT into a receptor using Smina."""
    result = dock_ligand(receptor_pdbqt, ligand_pdbqt)
    return json.dumps(result)

# backend/app/agents/graph.py（仅新增，不修改现有代码）
# 1. import SMINA_TOOLS from app.tools.smina.dock
# 2. 定义 docking_node()
# 3. RouteDecision.next 增加 "docking"
# 4. build_graph() 注册 add_node("docking", docking_node)
# 5. add_edge("docking", "shadow_lab")
```

### 扩展点汇总

| 扩展类型 | 需改的文件 | 不需改的文件 |
|---|---|---|
| 新增工具到现有节点 | `lg_tools.py` 或 `prep.py` | `graph.py`, `chem/`, `api/` |
| 新增专用节点 | `graph.py`（仅追加）| 所有已有节点 |
| 新增 REST 端点 | `api/<new>_api.py`, `main.py` | `chem/`, `agents/`, `tools/` |
| 新增 artifact 类型 | `sse_chat.py`, 前端 `ArtifactRenderer.tsx` | 所有后端节点 |

---

## 7. 本地启动

### 前置准备

```bash
# 1. 配置环境变量
cp .env.example .env
vim .env   # 填写 OPENAI_API_KEY、OPENAI_BASE_URL、OPENAI_MODEL

# 2. 安装依赖
cd backend && uv sync && cd ..
cd frontend && pnpm install && cd ..
```

所需环境变量：

| 变量 | 说明 |
|---|---|
| `OPENAI_API_KEY` | **必填**，DMXAPI key |
| `OPENAI_BASE_URL` | **必填**，`https://www.dmxapi.cn/v1`（或其他 OpenAI-compatible base）|
| `OPENAI_MODEL` | 模型名，如 `gpt-5` |

### 方式一：VS Code 任务（推荐）

打开命令面板 → `Tasks: Run Build Task` → **🚀 Start ChemAgent (Full Stack)**

同时启动后端（port 8000）和前端（port 3000）。

### 方式二：手动启动

```bash
# 后端
cd backend && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 前端（另开终端）
cd frontend && pnpm dev
```

### 方式三：Docker 全栈

```bash
docker compose up -d --build
```

---

## 8. 常用检查命令

```bash
# 后端健康检查
curl http://localhost:8000/health

# 冒烟测试 SSE 流（需后端运行中）
cd backend
uv run python tests/test_sse_stream.py "阿司匹林的 Lipinski 性质"
uv run python tests/test_sse_stream.py --smiles "CC(C)Cc1ccc(cc1)C(C)C(=O)O" "为布洛芬生成 3D 构象"
uv run python tests/test_sse_stream.py --smiles "CC(C)Cc1ccc(cc1)C(C)C(=O)O" "计算布洛芬的偏电荷"

# RDKit REST 验证
curl -s -X POST http://localhost:8000/api/rdkit/validate \
  -H 'Content-Type: application/json' \
  -d '{"smiles": "CC(=O)Oc1ccccc1C(=O)O"}'

# Open Babel REST 验证
curl -s -X POST http://localhost:8000/api/babel/conformer3d \
  -H 'Content-Type: application/json' \
  -d '{"smiles": "CC(C)Cc1ccc(cc1)C(C)C(=O)O", "name": "Ibuprofen"}'
```

---

## 9. 已验证的关键能力

| 场景 | 路由节点 | 工具调用 | Artifact | 验证状态 |
|---|---|---|---|---|
| 阿司匹林 Lipinski 性质 | analyst | `tool_compute_descriptors` | `descriptors` | ✅ 346 事件 17.4s |
| 布洛芬 2D 结构图 | visualizer | `tool_render_smiles` | `structure_image` | ✅ |
| 布洛芬 3D 构象生成 | prep | `tool_build_3d_conformer` | `conformer_3d` | ✅ 372 事件 16.6s |
| 布洛芬偏电荷计算 | analyst | `tool_compute_partial_charges` | — | ✅ 637 事件 17.3s |
| 布洛芬 3D 构象 + PDBQT | prep | `tool_build_3d_conformer` + `tool_prepare_pdbqt` | `conformer_3d` + `pdbqt` | ✅ |

---

## 10. 后续建议路线

### 近期

1. **前端 Artifact 渲染**：接入 NGL Viewer 或 3Dmol.js 渲染 `conformer_3d` SDF；创建 `BabelResultCard.tsx` 展示 PDBQT 下载
2. **LangGraph Checkpointer**：`SqliteSaver`/`RedisSaver` 实现跨请求多轮记忆
3. **Smina / GNINA 分子对接**：PDBQT 准备路径已就绪，新增 `chem/smina_ops.py` + `docking_node`
4. **PubChem 检索工具**：新增 `tools/pubchem/` → 名称/CID → SMILES 查询

### 中期

5. **并行 Fan-out**：Supervisor 通过 LangGraph `Send` API 同时派发 analyst + visualizer
6. **ADMET 预测**：SwissADME / pkCSM REST 工具
7. **持久化 Session**：Redis-backed 对话历史
8. **生产配置**：鉴权、CORS、WSS、限流

---

## 11. 相关文档

| 文档 | 说明 |
|---|---|
| [docs/API.md](docs/API.md) | SSE 流 + REST API 完整请求/响应文档（含 curl 示例）|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | LangGraph 5 节点架构详解、工具目录、扩展指南 |
| [docs/SOURCE_MAP.md](docs/SOURCE_MAP.md) | 文件职责索引、符号表、AG2→LangGraph 迁移记录 |

---

## 12. 一句话总结

ChemAgent 采用 **LangGraph 5 节点有向图**（Supervisor → Visualizer / Analyst / Prep → Shadow Lab）+ **13 个 `@tool` 封装**（7 RDKit + 6 Open Babel），通过 SSE 流直播每一步推理与工具调用，任何新化学软件只需新增计算层 + 工具封装 + 在 `graph.py` 追加节点，即可零侵入接入整个智能体工作流。
