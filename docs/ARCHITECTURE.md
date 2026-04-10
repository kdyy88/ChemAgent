# ChemAgent — 架构文档

> 最后更新：2026-04-10  
> 代码路径均相对于仓库根目录。

---

## 1. 总体架构

```
Browser / Frontend (Next.js)
        │  HTTP + SSE
        ▼
  Nginx (反向代理)
        │
        ▼
  FastAPI 后端  ──── Redis ────  ARQ Worker
  (app/main.py)                  (RDKit / Babel 重计算任务)
        │
   LangGraph
  ChemState 图
```

前端通过 HTTP POST 推送对话消息，后端以 **Server-Sent Events (SSE)** 流式返回 token、工具调用事件、Artifact 指针与状态更新。重量级计算（3D 构象生成、分子对接预处理）通过 ARQ + Redis 卸载到 Worker 进程，主进程保持响应。

---

## 2. 目录结构（`backend/app/`）

```
app/
├── main.py                    # FastAPI app 工厂；挂载所有路由
├── worker.py                  # ARQ WorkerSettings；重计算任务入口
│
├── api/                       # HTTP 传输层
│   ├── rest/                  # JSON REST 端点
│   │   ├── rdkit.py           # /api/rdkit/*  —— RDKit 直调 API
│   │   ├── babel.py           # /api/babel/*  —— OpenBabel 转换 API
│   │   └── scratchpad.py      # /api/scratchpad/*  —— 子 agent 暂存读取
│   └── sse/                   # SSE 流式端点
│       ├── chat.py            # /api/chat/*  —— 主控对话流
│       └── protocol.py        # SSE 信封类型定义（EventEnvelope 等）
│
├── agents/                    # LangGraph 智能体层
│   ├── engine.py              # ChemSessionEngine（双层生成器）
│   ├── graph.py               # build_graph() —— StateGraph 拓扑定义
│   ├── runtime.py             # 编译图缓存、持久会话检测
│   ├── state.py               # ChemState TypedDict；Task、MoleculeWorkspaceEntry 等
│   ├── prompts.py             # 主 agent 系统提示
│   ├── nodes/                 # LangGraph 节点函数
│   │   ├── agent.py           # chem_agent_node（主 LLM 调用）
│   │   ├── executor.py        # tools_executor_node（工具执行 + 状态更新）
│   │   ├── planner.py         # planner_node（结构化计划生成）
│   │   └── router.py          # task_router_node（simple / complex 路由）
│   ├── middleware/            # 跨节点横切关注点
│   │   ├── sanitization.py    # 消息净化 + 4级上下文压缩（状态写入前 / LLM 调用前）
│   │   ├── workspace.py       # 分子工作区 + 任务生命周期管理
│   │   └── postprocessors.py  # 工具结果后处理（渲染图像、分发 Artifact）
│   └── sub_agents/            # 子 agent 框架
│       ├── graph.py           # 子 agent LangGraph 图
│       ├── dispatcher.py      # tool_run_sub_agent（父→子派发）
│       ├── protocol.py        # 子 agent 消息协议
│       ├── runtime_tools.py   # 子 agent 运行时工具注入
│       ├── prompts.py         # 子 agent 系统提示
│       └── skills.py          # 技能 Markdown 加载（docs/subagent-skills/）
│
├── tools/                     # LangChain @tool 定义
│   ├── registry.py            # get_root_tools() —— 完整工具目录
│   ├── decorators.py          # 安全工具装饰器（safe_chem_tool）
│   ├── chem/                  # 化学核心工具
│   │   ├── rdkit_tools.py     # 20 个 RDKit @tool（PURE_RDKIT_TOOLS）
│   │   ├── pubchem.py         # tool_pubchem_lookup
│   │   ├── babel_tools.py     # OpenBabel 格式转换 @tool
│   │   └── __init__.py        # ALL_RDKIT_TOOLS / ALL_CHEM_TOOLS 目录组装
│   ├── interaction/           # 人机 + 网络工具
│   │   ├── web_search.py      # tool_web_search（Tavily / Serper 双后端）
│   │   └── ask_human.py       # tool_ask_human（HITL 暂停）
│   └── system/                # 系统状态工具
│       └── task_status.py     # tool_update_task_status（任务进度上报）
│
├── services/                  # 纯计算服务层（无 LangGraph 依赖）
│   ├── chem/
│   │   ├── rdkit_ops.py       # RDKit 底层操作函数
│   │   └── babel_ops.py       # OpenBabel 底层操作函数
│   └── task_runner/
│       ├── bridge.py          # ARQ 任务提交桥接
│       └── dispatch.py        # 任务注册表 + 重计算分发
│
├── domain/                    # 领域模型 + 持久化
│   ├── schemas/
│   │   ├── agent.py           # Pydantic 结构化输出模式（RouteDecision、PlanStructure 等）
│   │   └── api.py             # HTTP 请求体模式（StreamChatRequest、ApproveToolRequest 等）
│   └── stores/
│       ├── artifacts.py       # Artifact 存储（Redis + 内存双后端）
│       ├── plans.py           # 计划文件读写（JSON on disk）
│       └── scratchpad.py      # 子 agent 暂存区读写
│
└── core/                      # 基础设施
    ├── config.py              # LLM 配置、build_llm()、fetch_available_models()
    ├── redis.py               # Redis 连接池（ARQ 任务队列）
    └── network.py             # CORS 来源解析
```

---

## 3. LangGraph 图拓扑

```
START
  │
  ▼
task_router ──► is_complex=false ──► chem_agent
  │                                      │
  └──► is_complex=true ──► planner_node ─┘
                                         │
                           chem_agent ◄──┘
                               │
                    has_tool_calls?
                     yes │      no
                         ▼      ▼
                  tools_executor  END
                         │
                         └──► chem_agent（循环）
```

| 节点 | 文件 | 职责 |
|------|------|------|
| `task_router` | `nodes/router.py` | 调用 `with_structured_output(RouteDecision)` 判断任务复杂度 |
| `planner_node` | `nodes/planner.py` | 调用 `with_structured_output(PlanStructure)` 生成 3–5 步任务列表 |
| `chem_agent` | `nodes/agent.py` | 主 ReAct 循环；绑定工具目录；支持 native reasoning |
| `tools_executor` | `nodes/executor.py` | 并发执行工具调用；维护 `molecule_workspace` / `tasks`；仲裁 HITL 断点 |

### 持久性与 HITL

- **持久化**：`AsyncSqliteSaver`（`runtime.py`），以 `thread_id = session_id` 做 checkpoint。
- **Hard Breakpoint**：`HEAVY_TOOLS` 集合中的工具触发 `interrupt()`，等待前端 `POST /api/chat/approve`。
- **ask_human**：`tool_ask_human` 通过 `interrupt()` 暂停图，前端显示问题并回传答案。
- **计划审批**：子 agent 以 `status=plan_pending_approval` 返回，图暂停等待用户确认计划后再执行。

---

## 4. ChemSessionEngine（双层生成器）

```
submit_message()                         ← 外层：SSE 格式化、错误扣留、自愈重试
  └── _graph_query_loop()                ← 内层：astream_events v2 解析
        ├── on_chain_start / end         →  node_start / node_end SSE 事件
        ├── on_chat_model_stream         →  token SSE 事件
        ├── on_tool_start / end          →  tool_start / tool_end SSE 事件
        └── custom events               →  artifact / task_update / thinking / interrupt
```

**错误扣留**：底层化学错误（价键非法、SMILES 解析失败）在 `submit_message` 层拦截，自动注入修正提示并触发最多 `MAX_AUTO_RETRIES`（默认 2）次重试，前端感知不到该异常。

---

## 5. Artifact 系统

- **控制面**（SSE）：只传 Artifact 指针 `{ "artifact_id": "art_xxxxx" }`，不传原始数据。
- **数据面**（Redis / 内存）：`domain/stores/artifacts.py`；大体积 SDF、PDB、图像 base64 存于此。
- Artifact 分层：`"temp"` 层（5 分钟 TTL）用于临时重定向；正式层（300 秒 TTL，可配置）用于前端渲染。
- 前端通过 `GET /api/chat/artifacts/{artifact_id}` + `?session_id=` 取回内容。

---

## 6. 上下文压缩系统（4级压缩）

`agents/middleware/sanitization.py` 的 `normalize_messages_for_api()` 在每次 LLM 调用前执行，将完整 LangGraph 消息历史压缩为合法且 token 高效的 API 序列：

```
normalize_messages_for_api(messages, max_tool_history=15, max_tool_length=10000)
  │
  ├── Level 1: 丢弃虚拟 SystemMessage
  │     前端注入的带 is_virtual 标记的 SystemMessage 直接过滤掉
  │
  ├── Level 2: 孤立 / 悬挂工具调用修复
  │     - 删除没有匹配 AIMessage 的孤立 ToolMessage
  │     - 对未收到回执的 tool_call 就地注入关闭占位 ToolMessage
  │       （紧跟 AIMessage 后，保证 API 序列合法：AIMessage → ToolMessage → ...）
  │
  ├── Level 3: 历史 ToolMessage 压缩（反向遍历，最新优先）
  │     3a. 超出 max_tool_history（默认 15）的旧 ToolMessage
  │           → 替换为轻量占位符 "[System] Tool result omitted"
  │     3b. 单条超出 max_tool_length（默认 10000 字符）的 ToolMessage
  │           → 保留 head + tail，中间插入 "…[N chars omitted]…"
  │     3c. 合并多条占位符为一条信息性摘要
  │           第一条：统计总省略数量并提示 agent 依赖任务摘要与分子工作区
  │           其余：压缩为 "[Omitted]" 以满足 API tool_call_id 配对要求
  │
  └── Level 4: 合并连续同类型消息
        相邻同类型消息（HumanMessage / AIMessage 自然语言部分）合并为一条
        （ToolMessage 和携带 tool_calls 的 AIMessage 豁免，不参与合并）
```

**注意**：`sanitize_messages_for_state()` 之前承载「上下文防火墙」（字符限额强制写入）功能，已确认不及预期并于此版本移除，当前为无操作直通（no-op passthrough），仅保留接口供调用方兼容。上下文保护由 `normalize_messages_for_api()` 的 4 级机制在 LLM 调用前完成。

---

## 7. 分子工作区（Molecule Workspace）

`agents/middleware/workspace.py` 维护 `ChemState.molecule_workspace: list[MoleculeWorkspaceEntry]`：

- 每次工具成功返回 SMILES 时，`update_molecule_workspace()` 自动 upsert 对应条目。
- `format_molecule_workspace_for_prompt()` 将工作区序列化注入系统提示，使 agent 在多轮对话中保留分子上下文。
- `active_smiles` 字段追踪当前画布焦点；`apply_active_smiles_update()` 解析工具结果中的 SMILES 更新规则。

---

## 8. 子 Agent 框架

```
chem_agent
  └── tool_run_sub_agent(task, delegation, mode)
        ├── mode="plan"     → 生成计划 JSON → 等待用户审批 → mode="general"
        └── mode="general"  → 在独立 sub_thread_id 图中执行
              ├── 独立 LangGraph checkpoint（不污染父 session）
              ├── 可读取父 artifact（artifact_pointers 参数传入）
              └── 结果写入 scratchpad + 返回 produced_artifacts 列表
```

子 agent 技能通过 `docs/subagent-skills/*.md` 注入，`CHEMAGENT_SKILLS_DIR` 环境变量可覆盖路径。

---

## 9. 计算服务层（ARQ Worker）

重量级计算通过 `services/task_runner/` 卸载：

```
tools_executor
  └── safe_chem_tool 装饰器 (tools/decorators.py)
        ├── Redis 可用 → 提交 ARQ 任务 → 轮询结果
        └── Redis 不可用 → fallback：进程内直接执行（开发模式）
```

工具用 `@safe_chem_tool` + `@tool` 双装饰器注册，具备超时保护与 fallback 降级。

---

## 10. 工具目录

主 agent 绑定工具通过 `tools/registry.py` 的 `get_root_tools()` 组装，分三类：

### RDKit 工具（`tools/chem/rdkit_tools.py`）

| 工具名 | 功能 |
|--------|------|
| `tool_validate_smiles` | SMILES 合法性验证 + 标准化 |
| `tool_evaluate_molecule` | Lipinski / ADMET 快速评估 |
| `tool_compute_descriptors` | 分子描述符计算（MW、logP 等） |
| `tool_compute_similarity` | 摩根指纹 Tanimoto 相似度 |
| `tool_substructure_match` | SMARTS 子结构匹配 + 高亮图 |
| `tool_murcko_scaffold` | Murcko / 通用骨架提取 |
| `tool_strip_salts` | 盐去除 |
| `tool_render_smiles` | 2D 结构图渲染（PNG base64） |

### OpenBabel 工具（`tools/chem/babel_tools.py`）

| 工具名 | 功能 |
|--------|------|
| `tool_convert_format` | 分子格式互转（SDF / MOL2 / PDB / InChI …） |
| `tool_build_3d_conformer` | 3D 构象生成（MMFF94 / UFF） |
| `tool_prepare_pdbqt` | AutoDock Vina 对接预处理（输出 PDBQT） |
| `tool_compute_mol_properties` | OpenBabel 属性计算 |
| `tool_compute_partial_charges` | 部分电荷计算（Gasteiger / MMFF94 / QEq / EEM） |
| `tool_list_formats` | 列出所有支持的 OpenBabel 格式 |

### 其他工具

| 工具名 | 文件 | 功能 |
|--------|------|------|
| `tool_pubchem_lookup` | `tools/chem/pubchem.py` | PubChem REST 查询（SMILES、分子量、IUPAC 名称等） |
| `tool_web_search` | `tools/interaction/web_search.py` | 网络搜索（Tavily API / Serper API） |
| `tool_ask_human` | `tools/interaction/ask_human.py` | HITL 人机交互暂停 |
| `tool_update_task_status` | `tools/system/task_status.py` | 计划任务状态上报（`pending/in_progress/completed/failed`） |
| `tool_run_sub_agent` | `agents/sub_agents/dispatcher.py` | 启动子 agent 执行委托任务 |

---

## 11. 向后兼容垫片

重构后以下文件作为重导出垫片保留，新代码应直接使用目标模块：

| 垫片 | 重导出来源 |
|------|-----------|
| `agents/lg_tools.py` | `tools/chem/`, `tools/interaction/`, `tools/system/` |
| `agents/utils.py` | `agents/middleware/sanitization`, `agents/middleware/workspace`, `core/config`, `domain/stores/artifacts` |
| `agents/state.py` | 重导出 `domain/schemas/agent` 中的 Pydantic 模式 |
| `tools/babel/__init__.py` | `tools/chem/babel_tools` |

---

## 12. 环境变量参考

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OPENAI_API_KEY` | — | 必填 |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI 兼容代理地址（填到 `/v1`） |
| `OPENAI_MODEL` | `gpt-4o-mini` | 默认模型 |
| `CHEMAGENT_NATIVE_REASONING` | 自动检测 | `1` 强制启用 / `0` 强制关闭 native reasoning |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | Redis 连接串 |
| `CHEMAGENT_WORKER_MAX_JOBS` | `2` | ARQ worker 并发上限 |
| `CHEMAGENT_WORKER_JOB_TIMEOUT_SECONDS` | `120` | 单任务超时（秒） |
| `CHEMAGENT_GRAPH_RECURSION_LIMIT` | `60` | LangGraph 递归上限 |
| `TASK_POLL_INTERVAL_SECONDS` | `0.2` | ARQ 结果轮询间隔 |
| `ARTIFACT_TTL_SECONDS` | `300` | Redis Artifact 生存时间 |
| `CORS_ALLOWED_ORIGINS` | — | 逗号分隔的允许来源（生产必填） |
| `CHEMAGENT_SKILLS_DIR` | `docs/subagent-skills/` | 子 agent 技能 Markdown 根目录 |
