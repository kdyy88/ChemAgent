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
  │ Phase 1：manager.py → 路由决策（JSON）
  │ Phase 2：specialists/visualizer.py
  │          specialists/analyst.py
  │          specialists/researcher.py  (可并行)
  │ Phase 3：manager.py → 综合回答（Markdown）
  └────────────────────────────────────────────
  ↓
backend/app/core/tooling.py + backend/app/tools/**
  ↓ (化学计算委托给)
backend/app/chem/<rdkit_ops|babel_ops>.py
  ↓
结构化事件（含 sender 字段）回流前端
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

### `backend/app/agents/chemist.py`
**职责**
- 本地 smoke test 入口
- 使用当前 Visualizer 运行时做快速手工验证

**关键函数**
- `run_local_test()`

**注意事项**
- 正式运行时的共享配置已迁移到 `backend/app/agents/config.py`

### `backend/app/agents/config.py`
**职责**
- 加载 `.env`
- 规范化 OpenAI 兼容 `base_url`
- 提供 `build_llm_config(model)` / `get_fast_llm_config()`

### `backend/app/agents/factory.py`
**职责**
- 统一创建 `AssistantAgent` / `UserProxyAgent`
- 统一工具筛选、描述与注册逻辑
- 消除 Manager / Specialist 中重复样板代码

**后续建议**
- 如果未来继续新增 specialist，优先复用这里的工厂层

---

## 3.3 API 层

### `backend/app/api/chat.py`
**职责**
- WebSocket 主入口
- 初始化或恢复 session
- 接收用户消息
- 启动单轮运行
- 启动后台事件流线程
- 将结构化事件持续发回前端

**部署补充**
- 在 `websocket.accept()` 之前校验 `Origin`
- 用于避免线上任意来源直接连入 WebSocket

**关键函数**
- `_pump_queue_to_websocket()`
- `_stream_turn()`
- `_init_session()`
- `websocket_chat()`

**这是排障第一现场**
如果出现以下问题，先看这里：
- 前端收不到事件
- 工具调用有了，但 UI 不更新
- assistant.message 文本异常
- run 不结束
- WebSocket 协议不一致

### `backend/app/api/event_bridge.py`
**职责**
- 将 AG2 原始事件映射为前端协议帧
- 负责 specialist 并行/串行 draining（Phase 2）
- Phase 3 综合回答通过直接调用 OpenAI 流式接口实现 token 级实时输出，更绕过 AG2 缓冲

**关键函数**
- `sanitize_assistant_message()`
- `_stream_synthesis_direct()` — Phase 3 直接流式输出
- `stream_multi_agent_run()`

### `backend/app/api/protocol.py`
**职责**
- 定义 WebSocket 输入输出的数据模型

**核心模型**
- `SessionControlMessage`
- `UserMessage`
- `EventEnvelope`

**修改时机**
- 新增事件类型
- 调整协议字段命名
- 统一协议版本

### `backend/app/api/sessions.py`
**职责**
- 管理多轮会话
- 组织三阶段 multi-agent run（路由 → 专家执行 → 综合回答）
- 维护 session TTL
- 在同一 session 内复用 agent 历史与路由 agent 实例

**核心对象**
- `AgentTeam` — 持有 manager / router / router_trigger / visualizer / researcher 等所有 agent 实例
- `MultiAgentRunPlan` — 描述本轮三阶段执行计划
- `ChatSession` — 含 `turn_history: list`（跨轮消歧义）
- `SessionManager` — 单例，管理所有 session 生命周期
- `session_manager` — 全局实例

**关键函数**
- `build_synthesis_prompt()` — 将专家报告组装为综合回答输入
- `_do_routing()` — Phase 1，调用路由 agent 并解析 JSON 决策
- `run_turn()` — 返回 `MultiAgentRunPlan`，供 chat.py 驱动事件流

### `backend/app/api/runtime.py`
**职责**
- 定义运行期数据模型
- 提供历史上下文格式化与 synthesis prompt 拼装

**核心对象**
- `AgentTeam`
- `SpecialistSummary`
- `MultiAgentRunPlan`

**后续高频改造点**
- 持久化 session 到 Redis / DB
- 加租户维度
- 加 session 级别权限控制

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
- 定义工具协议和注册中心
- 统一工具输出模型
- 将 Python 函数包装成 AG2 tool
- 维护工具结果缓存，支持模型侧脱敏、前端侧全量 artifact 回放

**核心类型**
- `ToolArtifact`
- `ToolExecutionResult`
- `ToolSpec`
- `ToolRegistry`
- `ToolResultStore`

**核心对象**
- `tool_registry`
- `tool_result_store`

**核心函数**
- `parse_tool_payload()`

**这是最重要的扩展点之一**
新增工具时，通常围绕这里的契约工作。
**自动发现机制**
使用 `pkgutil.walk_packages`（递归，区别于旧版 `iter_modules` 的浅层扫描）自动 import `app/tools/` 下所有子包中的非下划线命名模块。添加新工具无需修改任何清单文件。
**设计约束**
- 模型看到的是“结构化摘要 + artifact 元信息”
- 前端收到的是完整 artifact
- 工具执行结果必须尽量统一，不要返回随意字符串

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

## 3.6 Tool Modules 层（`app/tools/`，按平台分组）

Agent 适配器，只包装 `app/chem/` 函数或外部 API，不含化学逻辑。

### `backend/app/tools/rdkit/image.py`
**导出工具**
- `draw_molecules_by_name` — 批量名称→PubChem SMILES→RDKit 2D 渲染，单次调用返回全部 artifacts
- `generate_2d_image_from_smiles` — SMILES→PNG（备用单次渲染）

### `backend/app/tools/rdkit/analysis.py`
**导出工具**
- `analyze_molecule_from_smiles` — SMILES → Lipinski RoF5，完整委托给 `chem/rdkit_ops.compute_lipinski()`

### `backend/app/tools/pubchem/lookup.py`
**导出工具**
- `get_smiles_by_name` — PubChem REST API 单次 SMILES 检索

### `backend/app/tools/search/web.py`
**导出工具**
- `web_search` — Serper API 真实搜索（供 Researcher 专家使用）；需在 `.env` 中配置 `SERPER_API_KEY`

### `backend/app/tools/babel/__init__.py`
Phase 2 占位。待 REST 端点充分验证后实现：
- `convert_molecule_format`
- `generate_3d_conformer`
- `prepare_docking_pdbqt`

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

### `session.started`
用于初始化工具目录和 session id。

### `run.started`
一轮开始。

### `tool.call`
模型决定调用某个工具。含 `sender` 字段标识来源专家。

### `tool.result`
工具返回结构化结果。含 `sender` 字段。

### `assistant.message`
助手自然语言消息。含 `sender` 字段：
- `sender === 'Manager'` → 路由至 `Turn.finalAnswer`，由 MessageBubble 以 Markdown 渲染
- 其他 sender（Visualizer / Researcher）→ 路由至 `Turn.steps`，展示在 ThinkingLog

### `run.finished`
一轮正常结束。

### `run.failed`
一轮异常结束。

---

## 7. 新增工具的标准做法（Phase 1 → Phase 2 两步走）

**Phase 1 — 独立 REST 端点（先做，先验证）**
1. 在 `backend/app/chem/` 下实现纯计算核函数（只依赖第三方库，零框架依赖）
2. 在 `backend/app/api/` 下新增对应 `APIRouter`，薄薄包一层 HTTP
3. 在 `backend/app/main.py` 中注册路由
4. 用 curl 烟雾测试验证输入输出正确性
5. 在前端 `lib/chem-api.ts` 中添加对应 fetch 函数，`lib/types.ts` 中添加响应类型

**Phase 2 — Agent 工具包装（REST 验证通过后）**
1. 在 `backend/app/tools/<平台>/` 子包下新增模块
2. 调用 Phase 1 中的 `app/chem/<xxx_ops>.py` 函数，**不重复写化学逻辑**
3. 使用 `@tool_registry.register(...)`，返回 `ToolExecutionResult`
4. Registry 通过 `walk_packages` 自动发现并挂载，无需修改主流程
5. 在对应 Specialist Agent 的工具授权列表中注册

**最小示例心智模型**
- 计算逻辑 → `app/chem/`
- HTTP 层 → `app/api/`（薄）
- Agent 适配器 → `app/tools/<平台>/`（薄）
- 输出：统一 `ToolExecutionResult`，不返回随意字符串

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

- 想改路由逻辑 / 系统提示词：看 `backend/app/agents/manager.py`
- 想改专家能力 / 工具授权：看 `backend/app/agents/specialists/`
- 想改 LLM 配置：看 `backend/app/agents/config.py`
- 想加化学计算逻辑：看 `backend/app/chem/rdkit_ops.py` 或 `backend/app/chem/babel_ops.py`
- 想加 REST 端点：看 `backend/app/api/rdkit_api.py` 或 `backend/app/api/babel_api.py`
- 想加 Agent 工具：看 `backend/app/tools/<平台>/` + 参考 `backend/app/core/tooling.py` 契约
- 想改工具自动发现机制：看 `backend/app/core/tooling.py`（`walk_packages`）
- 想改协议：看 `backend/app/api/protocol.py` 和 `frontend/lib/types.ts`
- 想查流式事件 / sender 注入：看 `backend/app/api/event_bridge.py`
- 想查 session / 三阶段编排：看 `backend/app/api/sessions.py`
- 想查前端状态 / finalAnswer 路由：看 `frontend/store/chatStore.ts`
- 想改最终气泡渲染：看 `frontend/components/chat/MessageBubble.tsx`
- 想改思考日志 / 溯源徽章：看 `frontend/components/chat/ThinkingLog.tsx`
- 想调用 Open Babel REST 端点（前端）：看 `frontend/lib/chem-api.ts`
