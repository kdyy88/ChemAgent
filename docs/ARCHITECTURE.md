# ARCHITECTURE

本文档描述 ChemAgent 的系统架构、运行链路、模块边界与后续演进方向。

配套文档：
- `README.md`：项目总览与启动说明
- `SOURCE_MAP.md`：源码职责地图与开发定位索引

---

## 1. 架构目标

ChemAgent 当前架构围绕四个目标设计：

1. **降低化学幻觉**  
   智能体优先调用权威检索/计算工具，而不是直接臆测结构。

2. **全链路可解释**  
   前端实时展示工具调用、工具结果、最终回答，而非黑盒输出。

3. **平滑扩展工具生态**  
   新工具应尽量做到“注册即可接入”，避免修改核心流程。

4. **支持多轮上下文会话**  
   用户可在同一 session 中连续追问，复用已有结果和对话记忆。

---

## 2. 系统分层

```text
┌─────────────────────────────────────────────┐
│                  Frontend                   │
│ Next.js / React / Zustand / Chat UI         │
│ SmilesPanelSheet / HITL Plan Approval       │
└─────────────────────────────────────────────┘
                     │
           WebSocket │  REST (rdkit/babel)
                     ▼
┌─────────────────────────────────────────────┐
│            API Layer (async-first)          │
│ FastAPI WebSocket / rdkit_api / babel_api   │
│ Protocol / Sessions / Events (no threads)  │
└─────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────┐
│          Agent Runtime (dual-agent)         │
│ ChemBrain (ConversableAgent + LLM)         │
│ Executor  (ConversableAgent, no LLM)       │
│ HITL state machine: plan → approve → exec  │
└─────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────┐
│             Tooling Layer                   │
│ 7 tool functions (chem_tools.py)           │
│ ToolResultStore / slim-payload model       │
│ tenacity retry / async worker offload      │
└─────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────┐
│       Chem Computation Kernel              │
│       app/chem/rdkit_ops.py                │
│       app/chem/babel_ops.py                │
└─────────────────────────────────────────────┘
                     │
                     ▼
         External Libraries (RDKit / Open Babel /
                   PubChem / Serper)
```

### 严格依赖方向

```
外部库
  ↓
app/chem/          ← 纯计算，无 HTTP / Agent 依赖
  ↙         ↘
app/api/   app/tools/   ← 互不依赖，只调用 chem/
  ↓
app/agents/        ← 不直接执行计算
```

**任何方向的逆向依赖都是架构缺陷**（如 `tools/` 导入 `api/`，或 `api/` 导入 `tools/`）。

---

## 3. 模块拆分

## 3.1 Frontend 层

职责：
- 接收用户输入
- 建立和复用 session
- 通过 WebSocket 与后端通信
- 渲染结构化事件流
- 展示 artifacts（图片/JSON/文本等）

核心组成：
- `app/page.tsx`：页面骨架
- `store/chatStore.ts`：状态中心与业务动作
- `lib/chat/socket.ts`：WebSocket 传输层
- `lib/chat/state.ts`：事件归并层
- `lib/chat/session.ts`：session 持久化层
- `hooks/useChemAgent.ts`：对外业务 hook
- `components/chat/*`：消息、思考日志、artifact 展示
- `lib/types.ts`：协议与状态类型定义

### 前端设计原则

- UI 不直接依赖具体工具实现
- 工具展示名称来自后端 `toolCatalog`
- artifact 独立于 message 正文渲染
- 协议驱动状态变化，而不是靠字符串解析

---

## 3.2 API / Session 层

职责：
- 接收前端 WebSocket 连接
- 初始化新 session 或恢复旧 session
- 接收用户消息并启动 agent run（async-first，无线程）
- 将 AG2 内部事件桥接为统一协议帧
- 管理 session 生命周期
- 接收 HITL 消息（plan.approve / plan.reject / settings.update）

核心文件：
- `backend/app/api/chat.py` — WebSocket 入口，HITL 消息路由
- `backend/app/api/events.py` — AG2 事件 → 前端协议帧（async drain）
- `backend/app/api/protocol.py` — 事件/消息 Pydantic schema
- `backend/app/api/sessions.py` — ChatSession + SessionManager

### Async-first 架构

当前 API 层完全运行在 asyncio 上，不使用任何线程：

- `session.lock` 是 `asyncio.Lock`，不是 `threading.Lock`
- `ChatSession.run_planning()` / `run_execution()` / `generate_greeting()` 使用 AG2 的 `await a_run()`
- `drain_response()` 使用 `async for event in response.events` 非阻塞迭代
- WebSocket 帧通过 `await send_fn(frame)` 直接发送，无 Queue 中转
- HITL 消息在主 `while True` 接收循环中直接处理

### Session 模型

当前 session 是**内存态**：
- 每个 session 对应一对 ChemBrain + Executor agent 实例
- session 带有 TTL（当前 15 分钟）
- 同 session 内多轮消息复用历史
- session 持有 `state`（idle / awaiting_approval / executing）和 `auto_approve` 标志

当前生产部署策略：
- `uvicorn` 固定单 worker，避免多进程下 WebSocket session 分裂
- RDKit / OpenBabel 重计算迁移到独立 Redis + ARQ worker
- WebSocket 通过应用层 `ping` / `pong` 心跳清理半连接

---

## 3.3 Agent Runtime 层

职责：
- 接收用户意图
- 两阶段 HITL 执行：规划 → 批准 → 执行
- ChemBrain 调用工具完成化学任务
- 输出结构化结果和制品

核心文件：
- `backend/app/agents/config.py` — LLM 配置工厂
- `backend/app/agents/__init__.py` — `create_agent_pair()` 工厂

### ChemBrain + Executor 双 Agent HITL 状态机

当前采用 **两 Agent 架构**，取代旧的多 Specialist 路由模式：

```text
User → Executor (caller) ←→ ChemBrain (callee/推理+执行) → Response
```

- **ChemBrain**（`ConversableAgent`）：持有 LLM，负责推理、规划、工具调用和生成回复
- **Executor**（`ConversableAgent(llm_config=False)`）：无 LLM 哨兵，负责执行工具函数
- 使用 `register_function(tool, caller=brain, executor=executor)` 进行双绑定
- 通过 `await executor.a_run()` → `AsyncRunResponseProtocol` 驱动

### 两阶段 HITL 执行流程

```text
Phase 1 — 规划
  executor.a_run(recipient=brain, message=prompt, clear_history=True)
  → ChemBrain 分析请求，输出 <plan>...</plan> XML
  → 输出 [AWAITING_APPROVAL] 哨兵
  → session.state = "awaiting_approval"

  若 auto_approve=True:
    → 自动进入 Phase 2
  否则:
    → 前端显示 PlanApprovalCard（批准/拒绝按钮）
    → 等待用户 plan.approve 或 plan.reject

Phase 2 — 执行（用户批准后）
  executor.a_run(recipient=brain, approval_msg, clear_history=False)
  → ChemBrain 逐步调用工具，输出 <todo> 进度标签
  → 最终输出 [TERMINATE]
  → session.state = "idle"
```

### 工具系统

7 个化学工具函数，全部在 `app/tools/chem_tools.py` 中定义：

| 工具 | 类型 | 功能 |
|------|------|------|
| `get_molecule_smiles` | sync | 名称/CAS → SMILES（PubChem） |
| `analyze_molecule` | async | 综合描述符 + Lipinski |
| `extract_murcko_scaffold` | async | Murcko 骨架提取 |
| `draw_molecule_structure` | async | 2D SVG 渲染 |
| `search_web` | sync | Serper 文献检索 |
| `compute_molecular_similarity` | async | Tanimoto 相似度 |
| `check_substructure` | async | 子结构 / SMARTS 匹配 |

**Slim Payload 模式**：工具返回给 LLM 精简 JSON（`{"success", "result_id", "summary"}`），重型制品存入 `ToolResultStore`，通过 WebSocket 推送给前端。

**错误恢复**：网络调用（PubChem、Serper）使用 tenacity 重试（3 次，指数退避 0.5s–4s），避免瞬态网络故障导致 agent 停滞。

**Worker 卸载**：当 `USE_WORKER=1` 时，计算密集型工具通过 `await run_via_worker()` 卸载到 ARQ worker；默认使用 `asyncio.to_thread()` 在线程池中执行。

---

## 3.4 Tooling Layer

职责：
- 7 个化学工具函数的实现
- 统一工具输出结构（`ToolExecutionResult`）
- 缓存完整工具结果（`ToolResultStore`），模型侧脱敏、前端侧完整回放
- 网络重试（tenacity）和异步 worker 卸载

核心文件：
- `backend/app/tools/chem_tools.py` — 7 个工具函数
- `backend/app/tools/__init__.py` — `ALL_TOOLS` 列表 + `public_catalog()`
- `backend/app/core/tooling.py` — `ToolArtifact`、`ToolExecutionResult`、`ToolResultStore`

### 错误恢复策略

采用 tenacity 三层重试：

```python
_retry_transient = retry(
    retry=retry_if_exception_type((URLError, Timeout, ConnectionError, OSError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, max=4),
    reraise=True,
)
```

- PubChem API（`_fetch_smiles_from_pubchem`）：重试 5xx，404 返回 None
- Serper API（`_serper_search`）：重试所有瞬态网络错误

### Worker 卸载

```python
async def _offload(task_name: str, **kwargs):
    if os.getenv("USE_WORKER") == "1":
        return await run_via_worker(task_name, kwargs)
    fn = _TASK_DISPATCH.get(task_name)
    return await asyncio.to_thread(fn, **kwargs)
```

当 `USE_WORKER=1` 时，计算密集型工具（analyze_molecule、draw_molecule 等）通过 Redis + ARQ 队列发送到独立 worker 进程。默认使用 `asyncio.to_thread()` 在线程池中执行，避免阻塞事件循环。

### Chem Computation Kernel（`app/chem/`）

| 文件 | 职责 | 暴露接口 |
|------|------|----------|
| `rdkit_ops.py` | RDKit 2D 渲染 + Lipinski 计算 | `mol_to_png_b64()`, `compute_lipinski()` |
| `babel_ops.py` | Open Babel 格式转换 / 3D 构象 / PDBQT 对接准备 | `convert_format()`, `build_3d_conformer()`, `prepare_pdbqt()` |

`app/chem/` 只依赖第三方库（rdkit、openbabel-wheel），不依赖框架层（FastAPI、AG2），可以在任何上下文中单独测试。

---

## 4. 核心运行时序

## 4.1 单轮请求时序（HITL 流程）

```text
User
  │
  │ 1. 输入问题
  ▼
Frontend ChatInput
  │
  │ 2. sendMessage(prompt)
  ▼
Zustand chatStore
  │
  │ 3. 建立/复用 WebSocket，发送 user.message
  ▼
FastAPI websocket_chat()
  │
  │ 4. 获取 ChatSession，创建 asyncio.Task
  ▼
_run_turn() [async, no threads]
  │
  │ 5. Phase 1：规划
  │    await session.run_planning(prompt)
  │    → ChemBrain 输出 <plan> + [AWAITING_APPROVAL]
  │    → events.py async drain → send_fn(frame)
  │    → session.state = "awaiting_approval"
  ▼
Frontend PlanApprovalCard
  │
  │ 6. 用户点击"批准"或"拒绝"
  │    （或 auto_approve=True 时自动跳过）
  ▼
WebSocket plan.approve / plan.reject
  │
  │ 7. Phase 2：执行（仅当 approved）
  │    await session.run_execution(approval_text)
  │    → ChemBrain 调用工具，输出 <todo> 进度
  │    → events.py async drain → send_fn(frame)
  │    → 最终输出 [TERMINATE]
  ▼
Frontend chatStore
  │  tool.call / tool.result → Turn.steps（ThinkingLog）
  │  assistant.message → Turn.finalAnswer
  ▼
MessageBubble → ReactMarkdown 渲染
```

---

## 4.2 多轮会话时序

```text
浏览器首次打开
→ session.start
→ backend 创建 session
→ 返回 session_id
→ session_id 存入 localStorage

连接存活期间
→ backend 周期性发送 ping
→ frontend 自动回 pong
→ 超时未收到 pong 则后端主动断开连接

下一轮继续提问
→ 前端复用同一个 WebSocket / session_id
→ backend 恢复对应 ChatSession
→ agent 继续在已有 history 上运行
```

---

## 5. 事件协议架构

前后端之间不传“拼接日志文本”，而是传**结构化事件**。

当前事件集合：

### Server → Client 事件
- `ping` — 心跳
- `session.started` — session 初始化完成
- `run.started` — 一轮开始
- `turn.status` — 阶段状态（planning / executing）
- `tool.call` — 模型决定调用工具
- `tool.result` — 工具返回结构化结果
- `assistant.message` — 助手文本消息
- `plan.proposed` — ChemBrain 输出执行计划
- `plan.status` — 计划状态（awaiting_approval / rejected）
- `todo.progress` — 执行进度更新
- `settings.updated` — 设置变更确认
- `run.finished` — 一轮正常结束
- `run.failed` — 一轮异常结束

### Client → Server 事件
- `pong` — 心跳回复
- `user.message` — 用户发送消息
- `session.start` / `session.resume` — 建立/恢复 session
- `session.clear` — 清空 session
- `plan.approve` — 用户批准计划
- `plan.reject` — 用户拒绝计划
- `settings.update` — 切换 auto_approve 等设置

### 事件层的意义

1. 前端状态更新更稳定
2. 工具链展示可扩展
3. 更适合调试与审计
4. 更容易兼容未来更多 artifact 类型

---

## 6. 数据模型架构

## 6.1 Turn 模型

前端将一次交互抽象为 `Turn`：
- 用户问题
- runId
- 步骤列表 `steps`（工具链 + 计划 + 进度，展示在 ThinkingLog）
- `finalAnswer?: string`（综合回答，独立字段，由 MessageBubble 以 Markdown 渲染）
- artifacts 列表
- 状态 `thinking / awaiting_approval / done`

**设计动机**：综合回答与工具链日志分离，避免最终答案混入 ThinkingLog 造成重复展示。HITL 状态 `awaiting_approval` 允许前端在等待用户审批时显示 PlanApprovalCard。

## 6.2 Step 模型

步骤分为六类：
- `tool_call` — 工具调用请求
- `tool_result` — 工具执行结果
- `agent_reply` — 自然语言阶段性总结
- `error` — 错误信息
- `plan` — ChemBrain 输出的执行计划（HITL）
- `todo` — 执行进度更新（HITL）

ThinkingLog 根据步骤类型使用不同图标和颜色：plan=蓝色、todo=绿色。

## 6.3 Artifact 模型

artifact 与 message 分离。

这样做的价值：
- 图片、JSON、文本报告、文件下载都可统一演进
- 模型无需承担大体积媒体内容上下文
- 前端可以按类型独立优化展示器

---

## 7. 模型上下文与 artifact 分离策略

这是当前架构中的一个关键优化。

### 问题

如果把图片的 base64 直接回灌给模型，会带来：
- 上下文膨胀
- completion 卡顿甚至不结束
- 生成结果质量下降
- 浪费 token / 资源

### 现方案

工具执行后：
- **模型侧**：只看到 artifact 元信息（存在什么产物、标题、类型）
- **服务端缓存**：保存完整工具结果和 artifact 数据
- **前端侧**：通过事件拿到完整 artifact

### 结果

- 模型更容易正常收尾并输出 `TERMINATE`
- 前端仍然可以完整展示图像类产物

---

## 8. 可扩展性设计

## 8.1 新增工具

在 `backend/app/tools/chem_tools.py` 中添加新工具函数：

1. 在 `app/chem/` 下实现纯计算核函数（只依赖第三方库，零框架依赖）
2. 在 `chem_tools.py` 中添加新函数，返回 `_slim_response()` 格式
3. 在 `ALL_TOOLS` 列表中注册
4. 在 `create_agent_pair()` 中通过 `register_function()` 绑定到 brain + executor
5. 如需网络重试，使用 `@_retry_transient` 装饰器
6. 如需 worker 卸载，使用 `await _offload(task_name, ...)` 模式

## 8.2 新增 artifact 类型

标准路径：
1. 后端输出新的 `kind` / `mime_type`
2. 前端在 `ArtifactRenderer` 中新增对应渲染分支
3. 必要时增加专门组件

## 8.3 扩展工具数量

当前 7 个工具已覆盖核心化学任务。扩展新工具的标准路径：
1. 在 `backend/app/chem/` 下新增计算函数
2. 在 `backend/app/tools/chem_tools.py` 中添加工具函数
3. 在 `backend/app/tools/__init__.py` 的 `ALL_TOOLS` 中注册
4. 在 `backend/app/agents/__init__.py` 的 `create_agent_pair()` 中绑定

未来候选工具：
- Open Babel 格式转换 / 3D 构象 / PDBQT 准备（REST 端点已就绪）
- ADMET 理化性质估算
- 逆合成路线规划
- 分子对接（Smina / GNINA）

---

## 9. 当前架构优点

### 9.1 工程优点
- 工具注册去硬编码
- 协议结构化
- 前后端职责边界更清晰
- 可测试性更强
- 未来扩展成本更低

### 9.2 产品优点
- 用户能看到推理链条
- 多轮对话体验更自然
- 结果展示从“纯文本”升级为“结果 + 产物”
- 更适合科研/化学场景的可追踪需求

---

## 10. 当前架构限制

### 10.1 Session 仍是内存态
- 服务重启后丢失
- 不适合多实例部署
- 不适合长生命周期用户历史

### 10.2 缺少持久化观测
- 没有独立 run trace 存储
- 没有 tool latency / success rate 统计
- 缺少审计日志分层

### 10.3 安全与生产治理仍较轻
- CORS 仍为全开放
- 未接入鉴权
- 未限制 session 并发与调用配额
- 未做细粒度资源隔离

### 10.4 Agent 终止仍依赖提示词治理
虽然已明显改善，但未来最好补上：
- 更强的 run-level watchdog
- 或明确的 tool/result-driven completion policy

---

## 11. 建议演进路线

## 近期（当前 Sprint）
- **Open Babel Agent 工具 Phase 2**：将已完成且测试通过的 babel REST 端点包装为 Agent 工具（`tools/babel/`），接入 Analyst 或新增 Docking 专家
- **Smina 对接流水线**：`chem/smina_ops.py` → `api/smina_api.py` → `tools/smina/`，端到端分子对接结果可视化

## 中期
- **持久化 session**：Redis / SQLite 替换内存态，支持多实例部署
- **可观测性**：tool latency / success rate 统计，审计日志分层，run trace 存储
- **InChI / 子结构搜索**：`chem/rdkit_ops.py` 中补充，同步暴露 REST + Agent 工具
- **收敛部署配置**：CORS 锁定，接入鉴权，session 并发配额

## 远期
- **可信验证层**：双重检索校验，结果一致性检查，化学规则校验器
- **xTB / GNINA 支持**：`chem/xtb_ops.py`、`chem/gnina_ops.py`，高精度量子化学与深度学习对接
- **历史 session 列表 + artifact 永久下载**
- **Reaction Expert Agent**：逆合成与反应预测专家
- 可视化 run trace
- 可回放的工具链执行视图

---

## 12. 文件到架构层的映射

### 前端
- `frontend/app/page.tsx` → UI 入口层
- `frontend/store/chatStore.ts` → 前端状态编排层（含 HITL actions）
- `frontend/lib/chat/socket.ts` → 传输层
- `frontend/lib/chat/state.ts` → 事件归并层（含 HITL 事件处理）
- `frontend/lib/chat/session.ts` → session 持久化层
- `frontend/hooks/useChemAgent.ts` → 公共业务接口层
- `frontend/lib/types.ts` → 协议/状态类型层（含 HITL 类型）
- `frontend/components/chat/*` → 可解释交互展示层
- `frontend/components/chat/PlanApprovalCard.tsx` → HITL 计划审批 UI

### 后端
- `backend/app/main.py` → 应用入口层
- `backend/app/api/chat.py` → WebSocket 入口层（async，HITL 路由）
- `backend/app/api/events.py` → 事件桥接层（async drain）
- `backend/app/api/sessions.py` → 会话管理层（ChemBrain + Executor）
- `backend/app/api/protocol.py` → 协议模型层（含 HITL 事件类型）
- `backend/app/agents/__init__.py` → 智能体工厂层（create_agent_pair）
- `backend/app/agents/config.py` → LLM 配置层
- `backend/app/core/tooling.py` → 工具核心抽象层
- `backend/app/tools/chem_tools.py` → 7 个化学工具实现（async + retry + worker）
- `backend/app/tools/__init__.py` → ALL_TOOLS + public_catalog()
- `backend/tests/` → pytest 测试套件（23 tests）

---

## 13. 一句话架构总结

ChemAgent 当前采用的是一种**前端事件驱动 + 后端 async-first session 驱动 + 双 Agent HITL 状态机 + 插件化工具扩展**的分层架构，重点不是"单次回答"，而是"可信、可解释、可扩展、用户可控的化学任务执行系统"。
