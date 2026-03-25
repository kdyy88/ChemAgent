# SOURCE_MAP

本文件用于后续开发时快速定位代码职责、入口、数据流和扩展点。

适用对象：
- 新加入项目的开发者
- 后续扩展化学工具的开发者
- 需要定位问题的调试人员

---

## 1. 总览

项目分为两层：

- `backend/`：智能体运行时、工具注册、WebSocket 协议、session 管理
- `frontend/`：聊天界面、推理日志、artifact 展示、会话状态管理

核心路径：

```text
用户输入
  ↓
frontend/app/page.tsx
  ↓
frontend/components/chat/ChatInput.tsx
  ↓
frontend/store/chatStore.ts
  ↓ WebSocket
backend/app/api/chat.py
  ↓
backend/app/api/sessions.py
  ┌────────────────────────────────────────────
  │ Phase 1：ChemBrain 规划 → <plan> + [AWAITING_APPROVAL]
  │ HITL Gate：auto_approve 或等待 plan.approve
  │ Phase 2：ChemBrain 执行 → 工具调用 + <todo> 进度
  └────────────────────────────────────────────
  ↓
backend/app/tools/chem_tools.py (7 tools, async + retry)
  ↓ (化学计算委托给)
backend/app/chem/<rdkit_ops|babel_ops>.py
  ↓
结构化事件（async drain）回流前端
  ↓
frontend/components/chat/*
```

---

## 2. 根目录

### `README.md`
项目总说明，面向使用者和开发者。

### `SOURCE_MAP.md`
本文件，面向维护者。

### `backend/`
后端服务。

### `frontend/`
前端 UI。

---

## 3. Backend 源码地图

## 3.1 入口层

### `backend/app/main.py`
**职责**
- 创建 FastAPI 应用
- 配置 CORS
- 注册聊天 WebSocket 路由
- 提供健康检查接口

**部署补充**
- 通过 `CORS_ALLOWED_ORIGINS` 驱动允许来源
- 健康检查返回当前允许来源，便于线上排障

**你会在这里做什么**
- 增加 HTTP 路由
- 调整 CORS / 中间件
- 接入鉴权、日志、监控

---

## 3.2 Agent 层

### `backend/app/agents/__init__.py`
**职责**
- `create_agent_pair(llm_config)` 工厂函数
- 创建 ChemBrain（ConversableAgent + LLM）和 Executor（ConversableAgent, no LLM）
- 使用 `register_function(tool, caller=brain, executor=executor)` 双绑定 7 个工具

### `backend/app/agents/config.py`
**职责**
- 加载 `.env`
- 规范化 OpenAI 兼容 `base_url`
- 提供 `build_llm_config(model)` / `get_resolved_model_name()`

---

## 3.3 API 层

### `backend/app/api/chat.py`
**职责**
- WebSocket 主入口（async-first，无线程）
- 初始化或恢复 session
- 接收用户消息，启动 HITL 两阶段运行
- 路由 HITL 消息（plan.approve / plan.reject / settings.update）
- 将结构化事件持续发回前端

**关键函数**
- `_run_turn()` — 完整 HITL 轮次：plan → approval → execute
- `_run_approval()` — 用户批准后恢复执行
- `_run_greeting()` — 新 session 欢迎消息
- `_init_session()` — session 初始化/恢复
- `websocket_chat()` — 主 WebSocket 端点

**Async 架构**
- 使用 `asyncio.Lock` 而非 `threading.Lock`
- 使用 `asyncio.create_task()` 而非 daemon thread
- 直接 `await send_fn(frame)` 而非 Queue + pump

**这是排障第一现场**
如果出现以下问题，先看这里：
- 前端收不到事件
- 工具调用有了，但 UI 不更新
- assistant.message 文本异常
- run 不结束
- HITL 批准/拒绝不响应
- WebSocket 协议不一致

### `backend/app/api/events.py`
**职责**
- 将 AG2 `AsyncRunResponseProtocol` 事件映射为前端协议帧
- 负责 async drain（`async for event in response.events`）
- 解析 `<plan>`、`<todo>` XML 标签和 `[AWAITING_APPROVAL]`、`[TERMINATE]` 哨兵
- 发射 HITL 事件（plan.proposed、plan.status、todo.progress）

**关键函数**
- `drain_response()` — 核心 async 迭代器，消费 AG2 事件流
- `_event_to_frames()` — 单事件 → WebSocket 帧列表
- `stream_planning()` — Phase 1 规划流
- `stream_execution()` — Phase 2 执行流
- `stream_greeting()` — 欢迎消息流

### `backend/app/api/protocol.py`
**职责**
- 定义 WebSocket 输入输出的数据模型

**核心模型**
- `SessionControlMessage`
- `UserMessage`（含 plan.approve / plan.reject 类型）
- `EventEnvelope`（含 HITL 事件类型：plan.proposed, plan.status, todo.progress, settings.updated）

**修改时机**
- 新增事件类型
- 调整协议字段命名
- 统一协议版本
**职责**
- 管理多轮会话
- 维护 ChemBrain + Executor agent 对
- HITL 状态机（idle / awaiting_approval / executing）
- 维护 session TTL
- 在同一 session 内复用 agent 历史

**核心对象**
- `ChatSession` — 含 brain/executor/state/auto_approve/lock(asyncio.Lock)
- `SessionManager` — 单例，管理所有 session 生命周期
- `session_manager` — 全局实例

**关键函数**
- `run_planning(prompt)` — Phase 1，`await executor.a_run(recipient=brain)`
- `run_execution(approval_text)` — Phase 2，`await executor.a_run(clear_history=False)`
- `generate_greeting()` — 一轮制欢迎消息
- `get_or_create()` — 恢复或创建 session

### `backend/app/api/rdkit_api.py`
**职责**
- 薄 HTTP 路由层，暴露 RDKit 计算能力为独立 REST 端点
- 不含任何化学逻辑，全部委托给 `app/chem/rdkit_ops.py`

**端点**
- `POST /api/rdkit/analyze` — SMILES → Lipinski Rule-of-5 + 2D 结构图

### `backend/app/api/babel_api.py`
**职责**
- 薄 HTTP 路由层，暴露 Open Babel 计算能力为独立 REST 端点
- 不含任何化学逻辑，全部委托给 `app/chem/babel_ops.py`

**端点**
- `POST /api/babel/convert` — 分子格式互转（130+ 格式）
- `POST /api/babel/conformer3d` — SMILES → 3D SDF 构象（MMFF94/UFF）
- `POST /api/babel/pdbqt` — SMILES → PDBQT 对接预处理（含加氢、Gasteiger 电荷）

---

## 3.4 Core 层

### `backend/app/core/tooling.py`
**职责**
- 定义工具输出模型（`ToolArtifact`、`ToolExecutionResult`）
- 维护工具结果缓存（`ToolResultStore`），支持模型侧脱敏、前端侧全量 artifact 回放
- 解析工具 payload（`parse_tool_payload()`）

**设计约束**
- 模型看到的是精简 JSON（success + result_id + summary）
- 前端收到的是完整 artifact
- 工具执行结果必须统一使用 `ToolExecutionResult`

---

## 3.5 Chem Computation Kernel 层（`app/chem/`）

纯计算核心，只依赖第三方库，零框架依赖。同时为 REST 端点（`app/api/`）和 Agent 工具（`app/tools/`）提供共享实现，杜绝重复化学逻辑。

### `backend/app/chem/rdkit_ops.py`
**职责**
- RDKit 2D 分子渲染与 Lipinski 计算

**暴露接口**
- `mol_to_png_b64(mol, size)` — RDKit Mol 对象 → 裸 base64 PNG
- `compute_lipinski(smiles, name)` — SMILES → `LipinskiResult`（含 MW/LogP/HBD/HBA/TPSA、`is_valid`、`lipinski_pass`、`violations`、`structure_image`）

### `backend/app/chem/babel_ops.py`
**职责**
- Open Babel 格式转换、3D 构象生成、PDBQT 对接预处理

**暴露接口**
- `convert_format(molecule_str, input_fmt, output_fmt)` → `FormatConversionResult`
- `build_3d_conformer(smiles, name, forcefield, steps)` → `Conformer3DResult`（SDF 内容）
- `prepare_pdbqt(smiles, name, ph)` → `PdbqtPrepResult`（PDBQT 内容，自动 Gasteiger 电荷）

**关键化学不变量**
`mol.OBMol.AddHydrogens(False, True, ph)` **先于** `mol.make3D()`，确保氢原子在力场优化前已存在。

---

## 3.6 Tool Modules 层（`app/tools/`）

Agent 工具实现，委托 `app/chem/` 函数或外部 API，不含化学逻辑。

### `backend/app/tools/chem_tools.py`
**导出工具（7 个）**
- `get_molecule_smiles` — 名称/CAS → SMILES（PubChem，sync，tenacity 重试）
- `analyze_molecule` — 综合描述符 + Lipinski（async，worker 卸载）
- `extract_murcko_scaffold` — Murcko 骨架提取（async，worker 卸载）
- `draw_molecule_structure` — 2D SVG 渲染（async，worker 卸载）
- `search_web` — Serper 文献检索（sync，tenacity 重试）
- `compute_molecular_similarity` — Tanimoto 相似度（async，worker 卸载）
- `check_substructure` — 子结构 / SMARTS 匹配（async，worker 卸载）

**关键内部函数**
- `_slim_response()` — 构建精简 JSON 回复 + 缓存完整结果到 ToolResultStore
- `_fetch_smiles_from_pubchem()` — PubChem REST API SMILES 查询（tenacity 重试）
- `_serper_search()` — Serper API 搜索（tenacity 重试）
- `_offload()` — Worker 卸载桥接（USE_WORKER=1 → run_via_worker，否则 asyncio.to_thread）

### `backend/app/tools/__init__.py`
- `ALL_TOOLS` — 7 个工具函数列表
- `public_catalog()` — 返回工具元信息（名称 + 描述），发送给前端

---

## 4. Frontend 源码地图

## 4.1 页面入口

### `frontend/app/page.tsx`
**职责**
- 组合页面骨架
- 顶部标题栏
- 中部消息区
- 底部输入区

**通常不放业务逻辑**
页面结构层应尽量保持薄。

### `frontend/app/layout.tsx`
**职责**
- 应用全局布局、字体、主题等

### `frontend/app/globals.css`
**职责**
- 全局样式

---

## 4.2 状态层

### `frontend/store/chatStore.ts`
**职责**
- 管理 chat 业务状态
- 组合 socket / session / reducer 辅助层
- 暴露 `sendMessage()` / `clearTurns()`

**这是前端最重要的业务文件**
如果出现以下问题，先看这里：
- 发送消息没反应
- turn 状态不对
- 工具结果没挂到对应轮次
- 清空会话异常
- session 恢复失败

**关键私有流程**
- `flushPendingTurn()`
- `connectSocket()`

### `frontend/lib/chat/session.ts`
**职责**
- 统一 `session_id` 的 localStorage 读写

### `frontend/lib/chat/socket.ts`
**职责**
- 封装 WebSocket 建连、握手与消息反序列化

**部署补充**
- 默认优先使用同源 `ws(s)://{host}/api/chat/ws`
- 显式配置 `NEXT_PUBLIC_WS_URL` 时才直连外部后端地址

### `frontend/lib/chat/state.ts`
**职责**
- 提供纯函数式事件归并逻辑
- 统一 `Turn` 更新、artifact 归一化和断线兜底

### `deploy/nginx/default.conf`
**职责**
- 对外暴露 `80` 端口
- 将 `/` 转发到前端容器
- 将 `/api/chat/ws` 和 `/api/` 转发到后端容器

### `compose.yaml`
**职责**
- 编排 `frontend`、`backend`、`gateway`
- 对外暴露前端 `80`、后端 `3030`
- 作为单机 Docker 上线入口

### `frontend/hooks/useChemAgent.ts`
**职责**
- 对外暴露稳定 hook 接口
- 封装 Zustand，避免 UI 组件直接依赖 store 实现细节

**建议**
- 新组件优先使用这个 hook，而不是直接读取 store

---

## 4.3 类型层

### `frontend/lib/types.ts`
**职责**
- 定义前端核心数据类型

**关键类型**
- `TurnStatus`
- `Artifact`
- `ToolMeta`
- `Step`（各变体含 `sender?: string` 溯源字段）
- `Turn`（含 `finalAnswer?: string`，Manager 综合回答独立字段）
- `ServerEvent`

**任何协议改动都要同步这里**
如果后端事件字段变了，这里必须先更新。

### `frontend/lib/utils.ts`
通用工具函数。

---

## 4.4 Chat UI 组件层

### `frontend/components/chat/ChatInput.tsx`
**职责**
- 输入框
- 提交消息
- 可能包含清空、发送状态控制

### `frontend/components/chat/MessageList.tsx`
**职责**
- 渲染所有 turn
- 负责滚动体验

### `frontend/components/chat/MessageBubble.tsx`
**职责**
- 渲染单个 turn
- 组织用户消息、思考日志、最终回答、artifact
- 使用 `react-markdown` + `remark-gfm` 渲染 `turn.finalAnswer`（支持粗体、有序列表、代码块等）
- 若 `finalAnswer` 不存在，回退到最后一条 `agent_reply` step（兼容旧 session）

### `frontend/components/chat/ThinkingLog.tsx`
**职责**
- 渲染工具调用与工具结果（仅 Specialist 步骤，不含 Manager 综合回答）
- 让用户看到白盒链路
- 根据 `step.sender` 渲染溯源徽章（Visualizer=绿 / Researcher=紫 / Manager=蓝）

### `frontend/components/chat/ArtifactRenderer.tsx`
**职责**
- 按 artifact 类型分发渲染
- 管理下载型 artifact 的对象 URL 生命周期

**高频扩展点**
如果以后增加：
- JSON 报告
- CSV 下载
- 3D viewer
- 表格结果
- 光谱图片
都应先改这里

### `frontend/components/chat/MoleculeCard.tsx`
**职责**
- 显示分子 2D 图片类 artifact

### `frontend/components/chat/ThinkingLog.tsx`
**职责补充**
- 使用工具元信息 `toolCatalog` 渲染更友好的工具名称
- 根据 `step.sender` 显示颜色溯源徽章（Visualizer=绿 / Researcher=紫 / Manager=蓝）

---

## 4.5 UI 基础组件层

### `frontend/components/ui/*`
**职责**
- 通用 UI 组件
- 多为 shadcn/ui 风格封装

**原则**
- 不放业务语义
- 只做基础可复用 UI 能力

---

## 5. 关键数据流

## 5.1 一次正常请求的数据流

```text
用户输入 prompt
→ ChatInput
→ useChemAgent / chatStore.sendMessage()
→ 建立或复用 WebSocket
→ backend websocket_chat()
→ SessionManager 获取 session
→ ChatSession.run_turn()
→ AG2 驱动 agent 与工具
→ chat.py 将事件转为协议帧
→ 前端 store 逐条消费事件
→ MessageList / MessageBubble / ThinkingLog / ArtifactRenderer 渲染
```

---

## 5.2 Session 恢复流

```text
浏览器加载
→ chatStore 读取 localStorage session_id
→ WebSocket onopen 发送 session.resume
→ 后端返回 session.started(resumed=true/false)
→ 前端继续在同一 session 上发下一轮消息
```

---

## 6. 已有协议事件说明

### Server → Client 事件

### `session.started`
用于初始化工具目录和 session id。

### `run.started`
一轮开始。

### `turn.status`
阶段状态更新（planning / executing）。

### `tool.call`
模型决定调用某个工具。

### `tool.result`
工具返回结构化结果。

### `assistant.message`
助手自然语言消息，路由至 `Turn.finalAnswer`。

### `plan.proposed`
ChemBrain 输出执行计划（`<plan>` 标签内容）。

### `plan.status`
计划状态变更：`awaiting_approval`（等待用户审批）或 `rejected`（被拒绝）。

### `todo.progress`
执行进度更新（`<todo>` 标签内容）。

### `settings.updated`
设置变更确认（如 `auto_approve` 切换）。

### `run.finished`
一轮正常结束。

### `run.failed`
一轮异常结束。

### Client → Server 事件

### `pong`
心跳回复。

### `user.message`
用户发送消息。

### `session.start` / `session.resume`
建立或恢复 session。

### `session.clear`
清空 session。

### `plan.approve`
用户批准执行计划，可附带修改意见。

### `plan.reject`
用户拒绝执行计划。

### `settings.update`
切换设置（如 `auto_approve`）。

---

## 7. 新增工具的标准做法

1. 在 `backend/app/chem/` 下实现纯计算核函数（只依赖第三方库，零框架依赖）
2. 在 `backend/app/tools/chem_tools.py` 中添加新工具函数
   - 使用 `Annotated` 类型注释 + docstring 作为 LLM schema
   - 返回 `_slim_response()` 格式
   - 如需网络重试：使用 `@_retry_transient` 装饰器
   - 如需 worker 卸载：使用 `await _offload(task_name, ...)` 模式
3. 在 `backend/app/tools/__init__.py` 的 `ALL_TOOLS` 列表中注册
4. 在 `backend/app/agents/__init__.py` 的 `create_agent_pair()` 中用 `register_function()` 绑定

**最小示例心智模型**
- 计算逻辑 → `app/chem/`
- 工具函数 → `app/tools/chem_tools.py`（返回 slim JSON）
- 工具注册 → `app/tools/__init__.py` + `app/agents/__init__.py`

---

## 8. 新增 artifact 的标准做法

1. 后端工具返回新的 `kind` / `mime_type`
2. 更新 `frontend/lib/types.ts`（如需要）
3. 在 `frontend/components/chat/ArtifactRenderer.tsx` 增加渲染分支
4. 必要时新增专门组件，如 `SpectrumCard.tsx`

---

## 9. 修改提示词时的建议

修改文件：`backend/app/agents/manager.py`、`backend/app/agents/specialists/`、`backend/app/agents/config.py`

优先调整：
- 工具使用顺序
- 出错后的 retry 策略
- 何时终止
- 如何总结结果

避免：
- 在提示词里耦合前端展示细节
- 在提示词里写死 base64 展示逻辑
- 让模型直接复述冗长 JSON

---

## 10. 排障指北

## 10.1 前端没有响应
先检查：
- `frontend/store/chatStore.ts`
- 后端是否启动在 8000
- `NEXT_PUBLIC_WS_URL` 是否正确
- 浏览器 Network / WS 帧

## 10.2 工具执行成功但页面没显示
先检查：
- `backend/app/api/chat.py` 是否发送了 `tool.result`
- `frontend/lib/chat/state.ts` 是否把 artifact 追加到 `turn.artifacts`
- `ArtifactRenderer.tsx` 是否支持对应类型

## 10.3 run 卡住不结束
先检查：
- `backend/app/agents/manager.py` 与 `backend/app/agents/specialists/` 的终止提示词
- 是否出现大体积内容进入模型上下文
- `event_bridge.py` 是否收到 `RunCompletionEvent`

## 10.4 多轮上下文失效
先检查：
- `backend/app/api/sessions.py` 的 `has_history`
- 前端是否复用了 `sessionId`
- 浏览器 localStorage 是否被清空

---

## 11. 当前空位与未来预留

### 后端预留
- `backend/app/agents/specialists/` 可继续新增更多专家

可用于未来拆分：
- Validator
- Retrieval Specialist
- Reaction Expert

### 前端预留方向
- 3D 分子可视化
- 可折叠 run trace
- artifact 下载面板
- 工具耗时与状态徽章
- session 历史列表

---

## 12. 建议维护原则

1. **后端协议优先结构化**
2. **工具输出优先统一模型**
3. **前端尽量不写死具体工具名**
4. **新能力优先走 artifact 扩展，而不是塞进 message 文本**
5. **复杂逻辑优先集中在 store / api / core，避免散落到 UI**

---

## 13. 一句话索引

- 想改 Agent 系统提示词：看 `backend/app/agents/__init__.py`（brain 的 system_message）
- 想改 LLM 配置：看 `backend/app/agents/config.py`
- 想加化学计算逻辑：看 `backend/app/chem/rdkit_ops.py` 或 `backend/app/chem/babel_ops.py`
- 想加 REST 端点：看 `backend/app/api/rdkit_api.py` 或 `backend/app/api/babel_api.py`
- 想加 Agent 工具：看 `backend/app/tools/chem_tools.py` + `backend/app/tools/__init__.py`
- 想改工具输出模型：看 `backend/app/core/tooling.py`
- 想改协议：看 `backend/app/api/protocol.py` 和 `frontend/lib/types.ts`
- 想查流式事件 / HITL 哨兵：看 `backend/app/api/events.py`
- 想查 session / HITL 状态机：看 `backend/app/api/sessions.py`
- 想查 WebSocket HITL 路由：看 `backend/app/api/chat.py`
- 想查前端状态 / HITL actions：看 `frontend/store/chatStore.ts`
- 想改最终气泡渲染：看 `frontend/components/chat/MessageBubble.tsx`
- 想改思考日志 / 计划卡片：看 `frontend/components/chat/ThinkingLog.tsx` 和 `PlanApprovalCard.tsx`
- 想调用 Open Babel REST 端点（前端）：看 `frontend/lib/chem-api.ts`
- 想运行后端测试：`cd backend && uv run pytest tests/ -v`
- 想运行前端测试：`cd frontend && npx vitest run`
