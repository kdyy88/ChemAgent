# AG2 Agent Layer Refactor — 更新日志

**日期**: 2026-03-25  
**范围**: 后端多智能体架构完全重构  
**目标**: 从旧的多 Specialist 路由—合成三阶段管线迁移到 ChemBrain + Executor 双 Agent HITL 状态机

---

## 一、架构变更概要

### Before（旧架构）
```
User → Manager → Router → [Analyst | Researcher | Visualizer] → Synthesis → Response
```
- 8 个 Agent 实例（Manager + 3 Specialist × 各自 UserProxy）
- `AssistantAgent` / `UserProxyAgent`（已废弃 API）
- `config_list` 裸 dict 配置
- `ToolSpec` + `ToolRegistry` 自动发现机制
- 三阶段管线：路由 → 并行 Specialist → Manager 汇总

### After（新架构）
```
User → ChemBrain (caller) ←→ Executor (executor) → Response
```
- 2 个 Agent 实例（ChemBrain + Executor）
- `ConversableAgent` + `LLMConfig` 现代 AG2 API
- `register_function(tool, caller=brain, executor=executor)` 双绑定
- 两阶段 HITL 状态机：规划 → `[AWAITING_APPROVAL]` → 执行 → `[TERMINATE]`

---

## 二、文件变更清单

### 新建文件（5 个）

| 文件 | 用途 |
|------|------|
| `app/tools/chem_tools.py` | 7 个化学工具函数，`Annotated` 类型注释 + slim payload 模式 |
| `app/agents/brain.py` | ChemBrain 系统提示词 + `create_chem_brain()` 工厂 |
| `app/agents/executor.py` | Executor 哨兵 Agent（无 LLM），双终止检测 |
| `app/agents/__init__.py` | `create_agent_pair()` + `register_function()` 批量注册 |
| `app/api/events.py` | AG2 事件 → WebSocket 帧转换，`stream_full_turn()`, `stream_greeting()` |

### 修改文件（6 个）

| 文件 | 变更内容 |
|------|----------|
| `app/tools/__init__.py` | 重写：导出 `ALL_TOOLS` 列表 + `public_catalog()` 元数据 |
| `app/core/tooling.py` | 移除 `ToolSpec`, `ToolRegistry`, `tool_registry` 单例；保留 `ToolArtifact`, `ToolExecutionResult`, `ToolResultStore` |
| `app/agents/config.py` | `build_llm_config()` → 返回 `LLMConfig(config_dict)`；新增 `get_resolved_model_name()` |
| `app/api/protocol.py` | 新增 HITL 事件类型：`plan.proposed`, `plan.status`, `todo.progress`；客户端类型：`plan.approve/reject/modify` |
| `app/api/sessions.py` | 完全重写：`ChatSession` 持有 2 个 Agent（非 8 个）；新增 `run_planning()`, `run_execution()`, `generate_greeting()` |
| `app/api/chat.py` | 导入更新 + `_stream_turn()` 重写：使用 `stream_full_turn()` 替代旧三阶段流 |

### 删除文件（8+ 个）

| 文件/目录 | 原用途 |
|-----------|--------|
| `app/agents/factory.py` | 旧 Agent 工厂（`create_assistant_agent`, `create_tool_agent_pair`） |
| `app/agents/manager.py` | 旧 Manager Agent（路由 + 汇总） |
| `app/agents/specialists/` | 旧 Specialist 目录（`analyst.py`, `researcher.py`, `visualizer.py`） |
| `app/api/event_bridge.py` | 旧事件桥接（`stream_multi_agent_run`） |
| `app/api/runtime.py` | 旧运行时模型（`MultiAgentRunPlan`, `SpecialistSummary`） |
| `app/tools/rdkit/` | 旧 RDKit 工具包装器 |
| `app/tools/search/` | 旧搜索工具包装器 |
| `app/tools/babel/` | 旧 Babel 工具包装器 |

---

## 三、关键技术决策

### 3.1 AG2 API 迁移

| 旧 API | 新 API |
|--------|--------|
| `AssistantAgent` | `ConversableAgent` |
| `UserProxyAgent` | `ConversableAgent(llm_config=False)` |
| `{"config_list": [config]}` | `LLMConfig(config_dict)` |
| `functions=[]` 单 Agent 注册 | `register_function(f, caller=brain, executor=executor)` |
| `initiate_chat()` | `.run()` → `RunResponseProtocol` |

### 3.2 工具系统

7 个工具函数，全部使用 `Annotated` 类型注释 + docstring 作为 LLM 工具 schema：

1. **`get_molecule_smiles`** — 名称/CAS → SMILES（PubChem）
2. **`analyze_molecule`** — 综合描述符 + Lipinski
3. **`extract_murcko_scaffold`** — Murcko 骨架提取
4. **`draw_molecule_structure`** — 2D SVG 渲染
5. **`search_web`** — DuckDuckGo 文献检索
6. **`compute_molecular_similarity`** — Tanimoto 相似度
7. **`check_substructure`** — 子结构 / SMARTS 匹配

**Slim Payload 模式**：工具返回给 LLM 的是精简 JSON（`{"success", "result_id", "summary"}`），重型制品（SVG、完整描述符表）存入 `ToolResultStore`，通过 WebSocket `tool.result` 事件推送给前端。

### 3.3 两阶段 HITL 状态机

```
Phase 1: 规划
  ChemBrain 输出 <plan>...</plan> + [AWAITING_APPROVAL]
  → Executor 检测哨兵，暂停对话

Phase 2: 执行（当前自动批准）
  Executor 发送 "[SYSTEM] 计划已批准，立即执行工具调用"
  → ChemBrain 逐步执行工具调用 + 输出 <todo> 进度
  → 最终输出 [TERMINATE]
```

### 3.4 事件流架构

- AG2 `.events` 是同步阻塞迭代器 → daemon thread 中消费
- `Queue` 作为 thread→async 桥接
- `_pump_queue_to_websocket()` 异步读取 Queue → 写入 WebSocket
- 向后兼容：保持 `assistant.message`, `tool.call`, `tool.result` 事件名
- 新增：`plan.proposed`, `plan.status`, `todo.progress`

### 3.5 Executor 哨兵注入

```python
override = (
    "[SYSTEM] 计划已批准。请立即开始执行工具调用，"
    "不要重复计划内容。直接调用第一个工具。"
)
```
通过 `[SYSTEM]` 前缀注入覆盖消息，强制 LLM 立即开始工具调用而非再次输出文本。

---

## 四、WebSocket 协议变更

### 新增服务器事件

| 事件类型 | 触发条件 | Payload |
|----------|----------|---------|
| `plan.proposed` | Brain 输出 `<plan>` 标签 | `{"plan": "..."}` |
| `plan.status` | 检测到 `[AWAITING_APPROVAL]` | `{"status": "approved", "auto": true}` |
| `todo.progress` | Brain 输出 `<todo>` 标签 | `{"todo": "..."}` |

### 新增客户端消息（预留，前端尚未实现）

| 消息类型 | 用途 |
|----------|------|
| `plan.approve` | 人工批准执行计划 |
| `plan.reject` | 拒绝并要求重新规划 |
| `plan.modify` | 修改计划后批准 |

### 保持不变的事件

`session.started`, `run.started`, `run.completed`, `run.failed`, `assistant.message`, `tool.call`, `tool.result`, `turn.status`, `ping`/`pong`

---

## 五、后端文件结构（重构后）

```
backend/app/
├── main.py                     # FastAPI 入口（无变更）
├── worker.py                   # ARQ Worker（无变更）
├── agents/
│   ├── __init__.py             # create_agent_pair() 工厂
│   ├── brain.py                # ChemBrain 系统提示 + 工厂
│   ├── config.py               # LLMConfig 构建
│   └── executor.py             # Executor 哨兵工厂
├── api/
│   ├── __init__.py
│   ├── babel_api.py            # Babel REST 接口（无变更）
│   ├── chat.py                 # WebSocket 主处理器
│   ├── events.py               # AG2 事件 → WS 帧转换
│   ├── protocol.py             # 事件/消息 schema
│   ├── rdkit_api.py            # RDKit REST 接口（无变更）
│   └── sessions.py             # 会话管理
├── chem/
│   ├── __init__.py
│   ├── babel_ops.py            # Open Babel 操作（无变更）
│   └── rdkit_ops.py            # RDKit 操作（无变更）
├── core/
│   ├── __init__.py
│   ├── network.py              # CORS / 网络配置（无变更）
│   ├── task_bridge.py          # Worker 任务桥接（无变更）
│   ├── task_queue.py           # ARQ 队列配置（无变更）
│   └── tooling.py              # ToolArtifact / ToolResultStore
└── tools/
    ├── __init__.py             # ALL_TOOLS + public_catalog()
    └── chem_tools.py           # 7 个工具函数实现
```

---

## 六、验证结果

| 验证项 | 状态 |
|--------|------|
| 12 个源文件 AST 语法检查 | ✅ 全部通过 |
| 全链路运行时 import 测试 | ✅ 全部通过 |
| `create_agent_pair()` 端到端创建 | ✅ Brain + Executor + 7 tools 已注册 |
| `session_manager.get_or_create()` 创建/恢复 | ✅ 正常 |
| FastAPI `app` 加载 + 路由注册 | ✅ 全部路由就位 |
| 旧文件清理 | ✅ 已删除 |
| `__pycache__` 清理 | ✅ 已清理 |

---

## 七、后续待办

1. **端到端对话测试**：配置真实 API Key 后验证完整对话流
2. **前端 HITL 支持**：实现 `plan.approve` / `plan.reject` 按钮，替换当前自动批准
3. **Worker 集成**：为重计算工具（如 3D 构象）添加 `run_via_worker()` 调用路径
4. **错误恢复**：工具执行失败时的重试 / fallback 机制
5. **Context.next.md 更新**：同步项目上下文文档
