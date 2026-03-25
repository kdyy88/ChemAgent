## 🌟 Context Initialization: ChemAgent Project (Current Handoff)

你好！这是为新一轮对话准备的最新上下文背景。请优先阅读本文件，再继续 ChemAgent 的后续开发、排障或功能扩展。

---

## 1. 项目定位

ChemAgent 是一个面向化学研发场景的 **AIDD 多智能体系统 + 专业化学 IDE 工作台**。

系统目标分为两部分：

1. **确定性化学工具链**
	- 提供 RDKit / Open Babel 驱动的结构校验、描述符、子结构、3D 构象、PDBQT、SDF 批处理等能力
2. **多智能体 AI Copilot**
	- 提供可理解当前工作台上下文的对话式化学助手
	- 允许 AI 输出可回填到表单的 Actionable UI

当前前端形态已经稳定为 **三栏 IDE 工作台**，后端则已升级为 **轻网关 + Redis + Worker** 架构。

---

## 2. 技术栈

### 2.1 后端
- Python 3.12+
- FastAPI
- uv
- AG2 (`ag2`)
- RDKit
- Open Babel (`openbabel-wheel`)
- Redis
- ARQ

### 2.2 前端
- Next.js App Router
- React
- Tailwind CSS
- Shadcn UI
- Zustand
- react-resizable-panels

### 2.3 编排 / 可视化
- Waldiez (`@waldiez/react` + `waldiez`)

---

## 3. 当前核心架构

## 3.1 前端：三栏 IDE 工作台

前端维持三栏布局：

1. **左栏：工具导航区**
	- 采用 VS Code 风格双态侧边栏
	- 支持按底层工具和业务场景切换

2. **中栏：化学工作台**
	- 承载确定性表单工具
	- 当前已覆盖：
	  - SMILES 验证与规范化
	  - 脱盐与中和
	  - 综合描述符 / Lipinski
	  - 偏电荷分析
	  - 相似度分析
	  - 子结构 / PAINS
	  - Murcko 骨架
	  - 格式转换
	  - 3D 构象生成
	  - PDBQT 准备
	  - SDF 拆分 / 合并

3. **右栏：AI Copilot**
	- WebSocket 驱动的会话式专家协同面板
	- 可感知当前工作台的隐式上下文

## 3.2 后端：轻网关 + Worker 架构

当前后端不再让 FastAPI 直接承载重计算，而是采用：

1. **FastAPI API / WebSocket 网关**
	- 负责 HTTP 接口
	- 负责 WebSocket 会话
	- 负责将重任务提交到 Redis 队列

2. **Redis**
	- 负责任务队列承接
	- 负责任务结果缓存
	- 负责 SDF 制品短 TTL 存储

3. **ARQ Worker**
	- 负责执行 RDKit / Open Babel 的重计算任务
	- 控制并发，隔离 CPU / 内存压力

这是当前并发优化后的主架构方向。

---

## 4. 多智能体机制

### 4.1 ChemBrain + Executor 双 Agent HITL 状态机

当前已从旧的多 Specialist 路由—合成架构迁移到 **双 Agent HITL（Human-in-the-loop）状态机**：

```
User → Executor (caller) ←→ ChemBrain (callee/推理+执行) → Response
```

- **ChemBrain**（`ConversableAgent`）：持有 LLM，负责推理、规划和生成回复
- **Executor**（`ConversableAgent(llm_config=False)`）：无 LLM 哨兵，负责执行工具调用
- 使用 `register_function(tool, caller=brain, executor=executor)` 进行双绑定
- 通过 `await executor.a_run()` → `AsyncRunResponseProtocol` 驱动
- **Async-first**：使用 `asyncio.Lock`、`async for event in response.events`，无线程

### 4.2 两阶段 HITL 执行流程

1. **Phase 1 — 规划**
   - `await executor.a_run(recipient=brain, message=prompt, clear_history=True)`
   - ChemBrain 分析用户请求，输出 `<plan>...</plan>` 标签
   - 输出 `[AWAITING_APPROVAL]` 哨兵暂停对话
   - session.state → "awaiting_approval"

2. **HITL 审批门**
   - 若 `auto_approve=True`：自动进入 Phase 2
   - 否则：前端显示 `PlanApprovalCard`（批准/拒绝按钮）
   - 用户发送 `plan.approve` 或 `plan.reject` WebSocket 消息

3. **Phase 2 — 执行**（用户批准后）
   - `await executor.a_run(recipient=brain, approval_msg, clear_history=False)`
   - Executor 注入 `[SYSTEM]` 覆盖消息，强制 LLM 立即开始工具调用
   - ChemBrain 逐步调用工具，输出 `<todo>` 进度标签
   - 最终输出 `[TERMINATE]` 结束对话

### 4.3 工具系统

7 个化学工具函数，全部使用 `Annotated` 类型注释 + docstring 作为 LLM schema：

| 工具 | 功能 |
|------|------|
| `get_molecule_smiles` | 名称/CAS → SMILES（PubChem） |
| `analyze_molecule` | 综合描述符 + Lipinski |
| `extract_murcko_scaffold` | Murcko 骨架提取 |
| `draw_molecule_structure` | 2D SVG 渲染 |
| `search_web` | DuckDuckGo 文献检索 |
| `compute_molecular_similarity` | Tanimoto 相似度 |
| `check_substructure` | 子结构 / SMARTS 匹配 |

**Slim Payload 模式**：工具返回给 LLM 精简 JSON（`{"success", "result_id", "summary"}`），重型制品存入 `ToolResultStore`，通过 WebSocket 推送给前端。

### 4.4 隐式上下文穿透
右侧 Copilot 会自动读取当前：
- `currentSmiles`
- `activeFunctionId`

并拼接为系统附加信息发给后端，使 AI 知道用户当前正在操作什么分子、处于哪个工具流。

### 4.5 Actionable UI
AI 可以输出类似 `<ApplySmiles smiles="..." />` 的自定义标签，前端会把它渲染为按钮，并在点击后自动把建议结构写回工作台输入框。

### 4.6 WebSocket 事件协议

保持向后兼容的事件名（`assistant.message`, `tool.call`, `tool.result`），新增 HITL 事件：

| 事件 | 方向 | 用途 |
|------|------|------|
| `plan.proposed` | Server→Client | Brain 输出执行计划 |
| `plan.status` | Server→Client | 计划状态：awaiting_approval / rejected |
| `todo.progress` | Server→Client | 执行进度更新 |
| `settings.updated` | Server→Client | 设置变更确认 |
| `plan.approve` | Client→Server | 人工批准（**已实现**） |
| `plan.reject` | Client→Server | 拒绝重新规划（**已实现**） |
| `settings.update` | Client→Server | 切换 auto_approve 等设置（**已实现**） |

---

## 5. 最近完成的重要改造

以下内容是近几轮开发中已经完成的关键升级：

### 5.1 AG2 Agent 层完全重构（2026-03-25）
- **旧架构已移除**：Manager + 3 Specialist（Analyst、Researcher、Visualizer）+ 各自 UserProxy 共 8 个 Agent
- **新架构已上线**：ChemBrain + Executor 双 Agent HITL 状态机，共 2 个 Agent
- AG2 API 全面迁移：`AssistantAgent` → `ConversableAgent`，裸 dict → `LLMConfig`，`initiate_chat()` → `.run()`
- 工具从 3 个扩展到 7 个，使用 `register_function(f, caller, executor)` 双绑定
- 事件桥接重写：旧 `event_bridge.py` → 新 `events.py`，支持 HITL 事件
- 会话层重写：`ChatSession` 从 8 个 Agent 简化为 2 个
- 删除旧文件：`factory.py`, `manager.py`, `specialists/`, `event_bridge.py`, `runtime.py`, 旧 `tools/` 子目录
- 详细变更见 `docs/CHANGELOG-ag2-refactor.md`

### 5.2 Async-first 迁移 + HITL + 错误恢复
- **Async 迁移**：`.run()` → `await .a_run()`，`threading.Lock` → `asyncio.Lock`，daemon thread → `asyncio.create_task`，`Queue` + `_pump_queue_to_websocket()` → 直接 `await send_fn(frame)`
- **HITL 完整实现**：`plan.approve` / `plan.reject` / `settings.update` WebSocket 消息处理器，`auto_approve` 切换，前端 `PlanApprovalCard` UI
- **tenacity 错误恢复**：PubChem / Serper API 自动重试（3 次，指数退避 0.5s–4s），区分 404/5xx
- **Worker 卸载**：`_offload()` 异步桥接，`USE_WORKER=1` → `run_via_worker`，否则 `asyncio.to_thread`
- **测试基础设施**：后端 pytest 23 tests（test_tools / test_events / test_sessions），前端 vitest 328 tests

### 5.2 并发与性能优化
- 引入 Redis + ARQ
- 重计算接口迁移到 Worker
- 后端 API 进程降为单 `uvicorn` worker
- Worker 并发由环境变量控制
- 通过 TTL 和 LRU 约束 Redis 内存占用

### 5.3 SDF 文件流重构
- 旧的进程内 latest cache 已移除
- SDF split / merge 的下载制品改为 Redis TTL 存储
- 下载接口改为基于 `result_id` / `download_id`

### 5.4 WebSocket 稳定性增强
- 新增 `ping` / `pong` 心跳
- 前端加入自动重连
- 前端持久化 `session_id`

### 5.5 前端 API 访问修正
- 本地 `pnpm dev` + Docker 后端 模式下：
  - 前端 REST 应访问 `http://127.0.0.1:3030/api/...`
  - 前端 WS 应访问 `ws://127.0.0.1:3030/api/chat/ws`
- 前端新增独立 REST 基址变量：`NEXT_PUBLIC_API_BASE_URL`
- 不再把 REST 地址和 WS 地址做复杂联动推导

### 5.6 CORS 问题已修复
- Docker 后端已允许本地开发来源：
  - `http://localhost:3000`
  - `http://127.0.0.1:3000`
  - `http://localhost:3001`
  - `http://127.0.0.1:3001`

此前浏览器中出现的 `Failed to fetch`，根因是 CORS 未放行本地前端来源，而不是接口本身不可用。

---

## 6. 当前本地开发模式

当前推荐的本地开发模式分为两类：

### 模式 A：前端本地 + 后端 Docker
适合日常前端调试。

- 前端：本地 `pnpm dev`
- 后端：Docker Compose 中运行 `backend`、`worker`、`redis`
- 前端环境应指向：
  - `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:3030`
  - `NEXT_PUBLIC_WS_URL=ws://127.0.0.1:3030`

### 模式 B：全 Docker 部署 / 上线模式
适合演示和上线。

- 浏览器通过同源 `/api/*` 与 `/api/chat/ws` 访问后端
- 通常不必显式配置前端 API / WS 地址

---

## 7. 当前已验证通过的能力

### 7.1 REST API（已验证）
- `POST /api/rdkit/validate`
- `POST /api/rdkit/analyze`
- `POST /api/rdkit/scaffold`
- `POST /api/rdkit/similarity`
- `POST /api/rdkit/substructure`
- `POST /api/babel/conformer3d`
- `POST /api/babel/sdf-split` / `GET /api/babel/sdf-split-download`
- `POST /api/babel/sdf-merge` / `GET /api/babel/sdf-merge-download`
- CORS 预检与跨域 POST（本地前端 → Docker 后端）

### 7.2 Agent 层（已验证）
- 12 个源文件 AST 语法检查：全部通过
- 全链路运行时 import 测试：全部通过
- `create_agent_pair()` 端到端创建：Brain + Executor + 7 tools 已注册
- `session_manager.get_or_create()` 创建/恢复：正常
- FastAPI `app` 加载 + 全部路由注册：正常
- **待验证**：需配置真实 API Key 后进行端到端对话测试

---

## 8. 当前需牢记的工程事实

1. **SessionManager 仍是内存态**
	- 因此后端 API 容器当前固定单 worker
	- 不应随意改回多 `uvicorn` worker

2. **重计算必须走 Worker**
	- 不应把 RDKit/Open Babel 大任务重新塞回 FastAPI 请求线程

3. **SDF 下载不再是“最近一次结果”**
	- 必须依赖返回的 `download_id` / `result_id`

4. **前端本地开发和 Docker 上线是两种不同模式**
	- 不要混淆 `3000` / `3030` / 同源代理

5. **浏览器里的 `Failed to fetch` 不一定是接口挂了**
	- 可能是 CORS
	- 也可能是前端地址指错
6. **AG2 Agent 层已使用现代 Async API**
	- `LLMConfig(config_dict)` 而非 `LLMConfig(**kwargs)` —— `LLMConfig` 只接受位置 dict 参数
	- `register_function(f, caller=brain, executor=executor)` 进行双绑定，**不使用** `functions=[]` 挂载到单个 Agent
	- `await executor.a_run()` → `AsyncRunResponseProtocol`，`.events` 是 `AsyncIterable[BaseEvent]`
	- `async for event in response.events` 非阻塞迭代，运行在主事件循环上
	- 完全不使用 daemon thread / Queue / run_in_executor
	- HITL 已完整实现：`plan.approve`、`plan.reject`、`settings.update` 前端按钮均可用
	- `auto_approve` 模式可在 TeamSettingsPopover 中切换

7. **AG2 旧 API 已被移除，不应引入**
	- ❌ `AssistantAgent` / `UserProxyAgent`
	- ❌ `config_list` 裸 dict 配置
	- ❌ `ToolSpec` / `ToolRegistry` / 自动发现
	- ❌ `initiate_chat()` / `a_initiate_chat()`
	- ❌ `threading.Thread` / `queue.Queue` / `run_in_executor`
	- ✅ 正确方式见 `.claude/skills/` 目录下的 AG2 技能文件

8. **错误恢复和 Worker 卸载已实现**
	- tenacity v9.1.4：PubChem 和 Serper API 自动重试（3 次，指数退避）
	- `_offload()` 桥接：USE_WORKER=1 → run_via_worker，否则 asyncio.to_thread
	- 5 个 async 工具 + 2 个 sync 工具（AG2 自动线程化）

9. **测试基础设施已建立**
	- 后端：pytest + pytest-asyncio，23 个测试（test_tools / test_events / test_sessions）
	- 前端：vitest，328 个测试（20 个测试文件），含 HITL 事件和 action 测试
---

## 9. 建议 AI 在新对话中默认知道的事情

如果你是下一轮对话中的 AI，请默认理解以下事实：

- 这是一个 **化学专业工具 + 双 Agent HITL Copilot** 的混合系统
- 前端是 **三栏专业 IDE**，而不是普通聊天页面
- 后端已经完成 **Redis + ARQ 并发架构改造**
- Agent 层已迁移到 **ChemBrain + Executor 双 Agent 状态机**，使用现代 AG2 API
- `.claude/skills/` 目录包含 AG2 最新 API 的权威参考，涉及 AG2 修改时必须先读取
- 当前要尽量保持：
  - 前端简洁
  - 架构可维护
  - 工具链 deterministic
  - 不随意引入过度复杂的状态同步设计
- 若涉及本地开发调试，要先判断用户处于：
  - 本地前端 + Docker 后端
  - 还是全 Docker / 同源代理模式

---

## 10. 下一轮开发建议切入点

后续可优先从以下方向推进：

1. **端到端对话测试**
	- 配置真实 API Key，验证完整 WebSocket 对话流
	- 确认 7 个工具的 LLM 调用 → 执行 → 结果返回链路正常
	- 测试 HITL 流程：plan.approve / plan.reject / auto_approve 切换

2. **Worker 集成增强**
	- 为重计算工具配置 `USE_WORKER=1` 生产级部署
	- 测试 run_via_worker 的超时和错误处理

3. **前端错误提示优化**
	- 将 `Failed to fetch`、队列错误、CORS 错误转为更明确的人类可读提示

4. **运行态可观测性**
	- 展示 worker 状态、活跃 session 数、队列积压情况
	- tool latency / success rate 统计

5. **Open Babel Agent 工具**
	- 在 `chem_tools.py` 中添加格式转换 / 3D 构象 / PDBQT 工具
	- REST 端点已验证通过，直接包装即可

6. **工作流编排增强**
	- 将 Waldiez/工作流编辑器与当前工具链做更深集成

---

## 11. 后端文件结构（当前）

```
backend/
├── pyproject.toml                  # 依赖 + pytest 配置
├── app/
│   ├── main.py                     # FastAPI 入口
│   ├── worker.py                   # ARQ Worker
│   ├── agents/
│   │   ├── __init__.py             # create_agent_pair() 工厂
│   │   ├── brain.py                # ChemBrain 系统提示 + 工厂
│   │   ├── config.py               # LLMConfig 构建
│   │   └── executor.py             # Executor 哨兵工厂
│   ├── api/
│   │   ├── __init__.py
│   │   ├── babel_api.py            # Babel REST 接口
│   │   ├── chat.py                 # WebSocket 主处理器（async，HITL 路由）
│   │   ├── events.py               # AG2 事件 → WS 帧转换（async drain）
│   │   ├── protocol.py             # 事件/消息 schema（含 HITL 类型）
│   │   ├── rdkit_api.py            # RDKit REST 接口
│   │   └── sessions.py             # 会话管理（2 Agent，asyncio.Lock）
│   ├── chem/
│   │   ├── __init__.py
│   │   ├── babel_ops.py            # Open Babel 操作
│   │   └── rdkit_ops.py            # RDKit 操作
│   ├── core/
│   │   ├── __init__.py
│   │   ├── network.py              # CORS / 网络配置
│   │   ├── task_bridge.py          # Worker 任务桥接
│   │   ├── task_queue.py           # ARQ 队列配置
│   │   └── tooling.py              # ToolArtifact / ToolResultStore
│   └── tools/
│       ├── __init__.py             # ALL_TOOLS + public_catalog()
│       └── chem_tools.py           # 7 个工具函数（async + retry + worker）
└── tests/
    ├── __init__.py
    ├── conftest.py                 # mock fixtures
    ├── test_tools.py               # 8 tests
    ├── test_events.py              # 6 tests
    └── test_sessions.py            # 9 tests
```

---

## 12. 结论

ChemAgent 当前已经不是一个简单 Demo，而是：

- 前端：专业三栏化学 IDE
- 后端：轻网关 + Redis + Worker 并发系统
- AI：基于 ChemBrain + Executor 双 Agent HITL 状态机的化学 Copilot，具备上下文感知与可回填交互能力

后续所有开发都应建立在这一事实上：

**要在保持架构清晰的前提下，继续提升稳定性、专业性与工作流闭环能力。**
