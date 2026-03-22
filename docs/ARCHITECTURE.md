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
│ SmilesPanelSheet (Analyze / Prep tabs)      │
└─────────────────────────────────────────────┘
                     │
           WebSocket │  REST (rdkit/babel)
                     ▼
┌─────────────────────────────────────────────┐
│                 API Layer                   │
│ FastAPI WebSocket / rdkit_api / babel_api   │
│ Protocol / Sessions / EventBridge           │
└─────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────┐
│               Agent Runtime                 │
│ AG2 AssistantAgent + UserProxyAgent         │
│ Manager / Visualizer / Analyst / Researcher │
└─────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────┐
│             Tooling Core Layer              │
│ ToolRegistry / ToolSpec / Result Models     │
│ walk_packages recursive auto-discovery      │
└─────────────────────────────────────────────┘
                     │
         ┌───────────┴───────────┐
         ▼                       ▼
┌─────────────────┐   ┌─────────────────────────┐
│  Tool Modules   │   │  Chem Computation        │
│  tools/rdkit/   │   │  Kernel (app/chem/)      │
│  tools/pubchem/ │──▶│  rdkit_ops.py            │
│  tools/search/  │   │  babel_ops.py            │
│  tools/babel/   │   │  (smina_ops.py …future)  │
└─────────────────┘   └─────────────────────────┘
         │                       │
         └───────────┬───────────┘
                     ▼
         External Libraries (RDKit / Open Babel /
                   requests / Serper)
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
- 接收用户消息并启动 agent run
- 将 AG2 内部事件桥接为统一协议帧
- 管理 session 生命周期

核心文件：
- `backend/app/api/chat.py`
- `backend/app/api/event_bridge.py`
- `backend/app/api/protocol.py`
- `backend/app/api/sessions.py`
- `backend/app/api/runtime.py`

### Session 模型

当前 session 是**内存态**：
- 每个 session 对应一组 agent 实例
- session 带有 TTL
- 同 session 内多轮消息复用历史

当前适合：
- 本地开发
- 单实例运行
- 原型验证

后续若要生产化，建议迁移到：
- Redis + 数据库存储 session 元信息
- 或按用户持久化会话记录

---

## 3.3 Agent Runtime 层

职责：
- 接收用户意图，路由到对应专家
- 专家执行工具调用与推理
- Manager 综合专家报告生成最终 Markdown 回答
- 在错误时进行自愈/重试

核心文件：
- `backend/app/agents/config.py` — LLM 配置工厂
- `backend/app/agents/factory.py` — agent / executor 组装工厂
- `backend/app/agents/chemist.py` — 本地 smoke test 入口
- `backend/app/agents/manager.py` — 路由 agent + 综合回答 agent
- `backend/app/agents/specialists/visualizer.py` — 可视化专家
- `backend/app/agents/specialists/analyst.py` — 分子分析专家
- `backend/app/agents/specialists/researcher.py` — 研究检索专家

当前采用**多智能体三阶段模式**：

```text
Phase 1 — 路由
  Manager Router (AssistantAgent + UserProxyAgent, session 级持久)
  → parse_routing_decision()
  → {"route": ["visualizer"] | ["analyst"] | ["researcher"] | 多者组合}

Phase 2 — 专家执行（可并行）
  Visualizer (AssistantAgent + UserProxyAgent)
    工具：draw_molecules_by_name（批量检索 SMILES + 渲染 2D 图，单次调用返回全部 artifacts）
  Analyst (AssistantAgent + UserProxyAgent)
    工具：analyze_molecule_from_smiles（SMILES → Lipinski RoF5 + 2D 图）
          委托给 app.chem.rdkit_ops.compute_lipinski()，与 Phase 1 REST 端点共享同一实现
  Researcher (AssistantAgent + UserProxyAgent)
    工具：web_search（Serper API 真实搜索）

Phase 3 — 综合回答（双轨制流式输出）
  绕过 AG2 缓冲，由 event_bridge._stream_synthesis_direct() 直接调用 OpenAI 客户端
  → stream=True，token 级实时推送 assistant.message 帧
  → 前端追加拼接 Turn.finalAnswer，即时渲染打字机效果
```

### 为什么保留双智能体（AssistantAgent + UserProxyAgent）

优点：
- 执行边界清晰，工具执行独立安全
- 每个专家只授权自身需要的工具子集
- 便于独立扩展各专家能力

代价：
- 协作链路复杂，对事件桥接要求更高
- 需要 `_event_to_frames()` 中精确注入 `sender` 字段

---

## 3.4 Tooling Core 层

职责：
- 定义统一工具契约
- 维护工具注册中心
- 将业务函数包装为 AG2/OpenAI 风格 tools
- 统一工具输出结果结构
- 缓存完整工具结果，支持模型侧脱敏、前端侧完整回放

核心文件：
- `backend/app/core/tooling.py`

核心对象：
- `ToolArtifact`
- `ToolExecutionResult`
- `ToolSpec`
- `ToolRegistry`
- `ToolResultStore`

### 自动发现机制

工具注册通过 `pkgutil.walk_packages` 递归扫描 `app/tools/` 下所有子包，自动 import 所有非下划线命名模块。每个模块内凡是被 `@tool_registry.register(...)` 装饰的函数均自动注册入 `ToolRegistry`，无需在任何清单文件中手动维护。

```python
# app/core/tooling.py
for module_info in pkgutil.walk_packages(package.__path__, prefix=f"{package_name}."):
    leaf = module_info.name.rsplit(".", 1)[-1]
    if leaf.startswith("_"):
        continue
    importlib.import_module(module_info.name)
```

### 设计动机

旧式方案的问题通常是：
- 工具返回纯字符串
- 前端/后端靠正则做分类
- 图片/base64 直接混入模型上下文
- 新增工具需要改多个硬编码位置

当前方案通过统一结构解决了这些问题。

---

## 3.5 Tool Modules 层

### 目录结构（按平台分组）

```text
app/tools/
  rdkit/
    __init__.py
    image.py       ← draw_molecules_by_name, generate_2d_image_from_smiles
    analysis.py    ← analyze_molecule_from_smiles
  pubchem/
    __init__.py
    lookup.py      ← get_smiles_by_name
  search/
    __init__.py
    web.py         ← web_search
  babel/
    __init__.py    ← Phase 2 占位（convert_molecule_format 等，待实现）
```

### 原则

`tools/` 层是**纯粹的 Agent 适配器**，只负责：
1. 接受结构化输入
2. 调用 `app/chem/` 中的计算核函数（或外部 API）
3. 将结果包装为 `ToolExecutionResult`

`tools/` 层**不含任何化学逻辑**，所有计算均委托给 `app/chem/` 层。例如 `analysis.py` 中的 `analyze_molecule_from_smiles` 完整委托给 `app.chem.rdkit_ops.compute_lipinski()`，与 REST 端点 `POST /api/rdkit/analyze` 共享同一实现，杜绝重复。

### Chem Computation Kernel（`app/chem/`）

| 文件 | 职责 | 暴露接口 |
|------|------|----------|
| `rdkit_ops.py` | RDKit 2D 渲染 + Lipinski 计算 | `mol_to_png_b64()`, `compute_lipinski()` |
| `babel_ops.py` | Open Babel 格式转换 / 3D 构象 / PDBQT 对接准备 | `convert_format()`, `build_3d_conformer()`, `prepare_pdbqt()` |

`app/chem/` 只依赖第三方库（rdkit、openbabel-wheel），不依赖框架层（FastAPI、AG2），可以在任何上下文中单独测试。

### 当前已注册工具（Phase 1 完毕）

| 工具名 | 所在模块 | 说明 |
|--------|----------|------|
| `draw_molecules_by_name` | `tools/rdkit/image.py` | 批量名称→PubChem→RDKit 2D 渲染 |
| `generate_2d_image_from_smiles` | `tools/rdkit/image.py` | SMILES→PNG（备用） |
| `analyze_molecule_from_smiles` | `tools/rdkit/analysis.py` | SMILES→Lipinski RoF5 + 2D 图 |
| `get_smiles_by_name` | `tools/pubchem/lookup.py` | PubChem SMILES 单次检索 |
| `web_search` | `tools/search/web.py` | Serper API 真实搜索 |

### Phase 2 计划（Open Babel Agent 工具）

`tools/babel/` 占位，待 Phase 1 REST 端点充分验证后实现：
- `convert_molecule_format` — 包装 `babel_ops.convert_format()`
- `generate_3d_conformer` — 包装 `babel_ops.build_3d_conformer()`
- `prepare_docking_pdbqt` — 包装 `babel_ops.prepare_pdbqt()`

---

## 4. 核心运行时序

## 4.1 单轮请求时序

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
FastAPI websocket_chat
  │
  │ 4. 获取 ChatSession
  ▼
ChatSession.run_turn() → MultiAgentRunPlan
  │
  │ 5. Phase 1：路由 — Manager Router 解析意图
  ▼
parse_routing_decision() → route=["visualizer"] | ["researcher"] | both
  │
  │ 6. Phase 2：专家执行（ThreadPoolExecutor 并行）
  ▼
Visualizer / Researcher 各自运行 AG2 + 工具
  │
  │ 7. 工具调用 → ToolRegistry → ToolExecutionResult
  │    event_bridge.py 注入 sender 字段，流式发送事件
  ▼
Frontend chatStore
  │  tool.call / tool.result → Turn.steps（ThinkingLog）
  │
  │ 8. Phase 3：Manager Synthesizer 综合报告
  ▼
assistant.message (sender='Manager')
  │
  │ 9. chatStore 路由：sender=Manager → Turn.finalAnswer
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

下一轮继续提问
→ 前端复用同一个 WebSocket / session_id
→ backend 恢复对应 ChatSession
→ agent 继续在已有 history 上运行
```

---

## 5. 事件协议架构

前后端之间不传“拼接日志文本”，而是传**结构化事件**。

当前事件集合：
- `session.started`
- `run.started`
- `tool.call`
- `tool.result`
- `assistant.message`
- `run.finished`
- `run.failed`

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
- 步骤列表 `steps`（专家工具链，展示在 ThinkingLog）
- `finalAnswer?: string`（Manager 综合回答，独立字段，由 MessageBubble 以 Markdown 渲染）
- artifacts 列表
- 状态 `thinking / done`

**设计动机**：Manager 综合回答与专家工具链日志分离，避免最终答案混入 ThinkingLog 造成重复展示。

## 6.2 Step 模型

步骤分为四类，每类均含可选 `sender?: string` 字段：
- `tool_call`（来源专家：Visualizer / Researcher）
- `tool_result`（来源专家：Visualizer / Researcher）
- `agent_reply`（专家自然语言阶段性总结，不含 Manager 综合回答）
- `error`

ThinkingLog 根据 `sender` 显示颜色溯源徽章（Visualizer=绿 / Researcher=紫 / Manager=蓝）。

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

## 8.1 新增工具（Phase 1 → Phase 2 两步走）

新增工具时，严格遵循"先 REST 后 Agent"的两阶段纪律，确保计算核心在接入 Agent 前已通过独立验证。

**Phase 1 — 独立 REST 端点**
1. 在 `backend/app/chem/` 下实现纯计算核函数（只依赖第三方库，零框架依赖）
2. 在 `backend/app/api/` 下新增对应 `APIRouter`，薄薄包一层 HTTP
3. 在 `backend/app/main.py` 中注册路由
4. 用 curl 烟雾测试验证输入输出正确性
5. 在前端 `lib/chem-api.ts` 中添加对应 fetch 函数，`lib/types.ts` 中添加响应类型

**Phase 2 — Agent 工具包装**
1. 在 `backend/app/tools/<平台>/` 子包下新增模块
2. 调用 Phase 1 中的 `app/chem/<xxx_ops>.py` 函数，**不重复写化学逻辑**
3. 使用 `tool_registry.register(...)`，返回 `ToolExecutionResult`
4. Registry 通过 `walk_packages` 自动发现并挂载，无需修改主流程
5. 在对应 Specialist Agent 的工具授权列表中注册

## 8.2 新增 artifact 类型

标准路径：
1. 后端输出新的 `kind` / `mime_type`
2. 前端在 `ArtifactRenderer` 中新增对应渲染分支
3. 必要时增加专门组件

## 8.3 新增专家 agent

当前已有 Visualizer + Researcher，扩展新专家的标准路径：
1. 在 `backend/app/agents/specialists/` 下新建文件
2. 实现 `create_xxx()` 返回 `(AssistantAgent, UserProxyAgent)`，仅授权该专家需要的工具
3. 在 `backend/app/api/sessions.py` 的 `AgentTeam` 中注册
4. 在 `backend/app/agents/manager.py` 的 `_ROUTING_SYSTEM_MESSAGE` 中增加路由选项
5. 在 `frontend/components/chat/ThinkingLog.tsx` 的 `SENDER_BADGE` 中增加颜色映射

未来候选专家：
- Validator Agent：交叉验证与一致性检查
- Reaction Expert：逆合成与反应预测
- Property Estimator：ADMET / 理化性质

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
- `frontend/store/chatStore.ts` → 前端状态编排层
- `frontend/lib/chat/socket.ts` → 传输层
- `frontend/lib/chat/state.ts` → 事件归并层
- `frontend/lib/chat/session.ts` → session 持久化层
- `frontend/hooks/useChemAgent.ts` → 公共业务接口层
- `frontend/lib/types.ts` → 协议/状态类型层
- `frontend/components/chat/*` → 可解释交互展示层

### 后端
- `backend/app/main.py` → 应用入口层
- `backend/app/api/chat.py` → WebSocket 入口层
- `backend/app/api/event_bridge.py` → 事件桥接层
- `backend/app/api/sessions.py` → 会话管理层
- `backend/app/api/runtime.py` → 运行期模型层
- `backend/app/api/protocol.py` → 协议模型层
- `backend/app/agents/config.py` → LLM 配置层
- `backend/app/agents/factory.py` → 智能体工厂层
- `backend/app/agents/chemist.py` → 本地验证入口
- `backend/app/core/tooling.py` → 工具核心抽象层
- `backend/app/tools/*` → 具体领域能力层

---

## 13. 一句话架构总结

ChemAgent 当前采用的是一种**前端事件驱动 + 后端 session 驱动 + 三阶段多智能体路由编排 + 插件化专家扩展**的分层架构，重点不是“单次回答”，而是“可信、可解释、可扩展的化学任务执行系统”。
