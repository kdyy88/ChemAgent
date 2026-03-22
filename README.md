# ChemAgent

ChemAgent 是一个面向化学场景的全栈智能体项目，目标是通过**权威检索 + 结构化工具调用 + 可解释流式过程展示**，尽量减少化学幻觉，并为后续分子分析工具扩展提供稳定底座。

当前版本已经完成：
- 后端**三层解耦架构**：纯计算层（`chem/`）→ HTTP 层（`api/`）→ 智能体工具层（`tools/`）
- 后端插件化工具注册（`tools/` 按平台分组，`walk_packages` 递归自动发现）
- 结构化事件流式协议与多轮 session memory
- **多智能体协作架构**（Manager 路由 + Visualizer / Analyst / Researcher 专家 + 综合回答器）
- 前端白盒推理/工具链展示（专家溯源徽章）与通用 artifact 渲染
- **RDKit 与 Open Babel 的 12 大 API 工具集群**：覆盖数据清洗、物化性质、结构分析、3D 构象优化与对接预处理，以及高通量 SDF 库批量合并与拆分。
- 前端侧边栏重构：支持“基础组件库”与“业务场景流”双视角切换，并完美接入所有 12 个强力交互表单。

---

## 1. 项目目标

ChemAgent 聚焦三个核心问题：

1. **减少化学幻觉**  
   不直接“猜结构”，而是优先通过检索工具获取依据，再进入后续计算或可视化步骤。

2. **让智能体过程透明**  
   前端会展示工具调用、工具结果、最终回答，而不是只返回黑盒结论。

3. **为后续工具生态做准备**  
   当前已落地工具注册中心，后续可以平滑接入：分子量、分子式、3D 构象、子结构搜索、反应预测等。

---

## 2. 技术栈

### 前端
- Next.js 16
- React 19
- TypeScript
- Zustand
- Tailwind CSS 4
- Framer Motion
- shadcn/ui

### 后端
- FastAPI
- AG2 / AutoGen
- Pydantic v2
- RDKit
- **Open Babel**（`openbabel-wheel`）
- requests
- websockets
- python-dotenv

---

## 3. 项目结构

```text
chem-agent-project/
├── backend/                      # FastAPI + AG2 + RDKit + Open Babel
│   ├── app/
│   │   ├── chem/                 # ★ 纯计算核心层（不含 HTTP/Agent 依赖）
│   │   │   ├── rdkit_ops.py      #   RDKit：2D 渲染、Lipinski 计算
│   │   │   └── babel_ops.py      #   Open Babel：格式转换、3D 构象、PDBQT 准备
│   │   ├── agents/
│   │   │   ├── config.py         #   共享 LLM 配置加载
│   │   │   ├── factory.py        #   通用 agent / tool 注册工厂
│   │   │   ├── chemist.py        #   本地 smoke test 入口
│   │   │   ├── manager.py        #   路由 agent + 综合回答 agent
│   │   │   └── specialists/
│   │   │       ├── visualizer.py #   可视化专家（draw_molecules_by_name）
│   │   │       ├── analyst.py    #   分析专家（analyze_molecule_from_smiles）
│   │   │       └── researcher.py #   检索专家（web_search）
│   │   ├── api/                  # HTTP 层：仅路由，不含化学逻辑
│   │   │   ├── rdkit_api.py      #   POST /api/rdkit/analyze
│   │   │   ├── babel_api.py      #   POST /api/babel/{convert,conformer3d,pdbqt}
│   │   │   ├── chat.py           #   WebSocket 主入口
│   │   │   ├── event_bridge.py   #   AG2 事件 → 前端协议帧
│   │   │   ├── sessions.py       #   会话管理与三阶段编排
│   │   │   ├── runtime.py        #   运行期数据模型
│   │   │   └── protocol.py       #   WebSocket 输入输出模型
│   │   ├── core/
│   │   │   └── tooling.py        #   工具注册中心、结果模型、缓存
│   │   └── tools/                # Agent 工具层（按平台分组）
│   │       ├── rdkit/
│   │       │   ├── image.py      #   draw_molecules_by_name, generate_2d_image_from_smiles
│   │       │   └── analysis.py   #   analyze_molecule_from_smiles
│   │       ├── pubchem/
│   │       │   └── lookup.py     #   get_smiles_by_name
│   │       ├── search/
│   │       │   └── web.py        #   web_search
│   │       └── babel/            #   Open Babel agent 工具（Phase 2 占位）
│   ├── .env.example
│   └── pyproject.toml
├── frontend/                     # Next.js UI
│   ├── app/                      #   App Router 入口
│   ├── components/chat/          #   聊天、日志、artifact 展示组件
│   │   └── BabelResultCard.tsx   #   格式转换 / 3D 结构 / PDBQT 结果卡片
│   ├── hooks/                    #   对外暴露的业务 hook
│   ├── lib/
│   │   ├── chem-api.ts           #   REST API 调用（rdkit + babel）
│   │   └── types.ts              #   前端类型定义
│   └── store/                    #   Zustand 状态管理
├── docs/
│   └── API.md                    # REST API 完整文档
├── README.md
├── ARCHITECTURE.md
└── SOURCE_MAP.md
```

### 依赖方向（严格执行）

```
外部库（RDKit / Open Babel / requests）
        ↓
   app/chem/          ← 纯计算，不依赖 FastAPI 或 Agent 框架
      ↙       ↘
 app/api/    app/tools/    ← 两者只调用 chem/，互不依赖
        ↓
   app/agents/        ← 调度专家，不直接执行计算
```

新软件（如 Smina、xTB）接入时：新增 `chem/smina_ops.py` → `api/smina_api.py` → `tools/smina/`，**不修改任何现有文件**。

---

## 4. 当前能力

### REST API（Phase 1 — 12 大功能集群，无需 Agent 直接可用）

**RDKit 工具簇：**
| 端点 | 功能 | 核心依赖 |
|---|---|---|
| `POST /api/rdkit/validate` | SMILES 验证与规范化 | RDKit |
| `POST /api/rdkit/salt-strip` | 分子脱盐与电荷中和 | RDKit |
| `POST /api/rdkit/descriptors` | 综合性分子描述符（替代旧 Lipinski，含 SA Score 与 QED） | RDKit + SA_Score |
| `POST /api/rdkit/similarity` | 摩根指纹 Tanimoto 相似度比对 | RDKit |
| `POST /api/rdkit/substructure` | SMARTS 子结构搜索与 PAINS 获取警告 | RDKit |
| `POST /api/rdkit/scaffold` | Bemis-Murcko 核心骨架提取 | RDKit |

**Open Babel 工具簇：**
| 端点 | 功能 | 核心依赖 |
|---|---|---|
| `POST /api/babel/properties` | 提取精确分子质量、净电荷、自旋多重度等核心属性 | Open Babel |
| `POST /api/babel/partial-charges` | 计算 Gasteiger/MMFF94/QEq 等模型的原子偏电荷 | Open Babel |
| `POST /api/babel/convert` | 格式万能转换（SMILES ↔ SDF ↔ MOL2 ↔ PDB ↔ InChI…） | Open Babel |
| `POST /api/babel/conformer3d` | SMILES → 力场优化 3D 构象（附带力场 `energy_kcal_mol`） | Open Babel |
| `POST /api/babel/pdbqt` | PDBQT 对接预处理（加质子 → 3D 优化 → Gasteiger 电荷 → 转子） | Open Babel |
| `POST /api/babel/sdf-split` | 高通量拆分：上传单个包含多个分子的 SDF，返回 zip 压缩包 | Open Babel + FastAPI |
| `POST /api/babel/sdf-merge` | 高通量合并：批量上传多个 SDF，合并成单个 SDF 库文件 | Open Babel + FastAPI |
| `GET /api/babel/formats` | 工具接口：枚举支持的所有化学格式字典 | Open Babel |

详细请求/响应格式见 [docs/API.md](docs/API.md)。

### Agent 工具（Phase 2 — 由 AI 按需调用）

| 工具名 | 平台 | 位置 | 功能 |
|---|---|---|---|
| `draw_molecules_by_name` | RDKit + PubChem | `tools/rdkit/image.py` | 批量名称 → 2D 结构图 |
| `generate_2d_image_from_smiles` | RDKit | `tools/rdkit/image.py` | SMILES → 2D 结构图 |
| `analyze_molecule_from_smiles` | RDKit | `tools/rdkit/analysis.py` | SMILES → Lipinski 分析 |
| `get_smiles_by_name` | PubChem | `tools/pubchem/lookup.py` | 化合物名 → SMILES |
| `web_search` | Serper | `tools/search/web.py` | 药物/文献检索 |

### 已有协议事件
- `session.started`
- `run.started`
- `tool.call`
- `tool.result`
- `assistant.message`
- `run.finished`
- `run.failed`

### 已有前端表现
- 聊天输入与多轮会话
- 工具链思考日志（含专家溯源徽章：Visualizer 绿 / Researcher 紫 / Manager 蓝）
- 最终回答 Markdown 渲染（粗体、有序列表、代码块等完整支持）
- artifact 独立渲染
- session 恢复与清空

---

## 5. 本地启动

## 5.1 后端准备

进入 backend：

```bash
cd backend
```

创建环境变量文件：

```bash
cp .env.example .env
```

至少配置：
- `OPENAI_API_KEY` 必填
- `OPENAI_BASE_URL` 可选
- `SERPER_API_KEY` 可选（缺失时 web_search 返回错误提示）

同步依赖并启动：

```bash
uv sync
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

后端健康检查：
- http://localhost:8000/
- WebSocket: `ws://localhost:8000/api/chat/ws`

## 5.2 前端准备

进入 frontend：

```bash
cd frontend
pnpm install
```

开发启动：

```bash
pnpm dev
```

默认前端地址：
- http://localhost:3000

如果前端需要显式指定后端地址，可配置：
- `NEXT_PUBLIC_WS_URL=ws://localhost:8000`

---

## 5.3 Docker 部署（单机上线）

当前仓库已补充：
- 根目录 [compose.yaml](compose.yaml)
- 前端镜像 [frontend/Dockerfile](frontend/Dockerfile)
- 后端镜像 [backend/Dockerfile](backend/Dockerfile)
- 同域名反代配置 [deploy/nginx/default.conf](deploy/nginx/default.conf)

默认上线拓扑：
- 对外前端入口：`80`
- 对外后端入口：`3030`
- 浏览器默认通过同域名 `/api/chat/ws` 访问后端，不再依赖写死某个 IP

部署前先在根目录创建 `.env`（参考 [.env.example](.env.example)）：
- `OPENAI_API_KEY`：必填
- `OPENAI_BASE_URL`：可选
- `SERPER_API_KEY`：可选，接入真实网页搜索
- `CORS_ALLOWED_ORIGINS`：建议填写你的实际公网域名或 IP，例如 `http://your-server-ip`
- `NEXT_PUBLIC_WS_URL`：通常留空；留空时前端会自动走同源 WebSocket

启动：

```bash
docker compose up -d --build
```

启动后：
- 前端访问：`http://your-server-ip/`
- 后端健康检查：`http://your-server-ip:3030/`

说明：
- 如果未来接入 HTTPS，前端会根据页面协议自动切换到 `wss://`
- 当前 session 仍是内存态，因此建议单机单后端实例部署
- 当前 `web_search` 已接入 Serper 真实搜索接口

---

## 6. 开发工作流

推荐使用两个终端：

### 终端 A：后端
```bash
cd backend
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 终端 B：前端
```bash
cd frontend
pnpm dev
```

常用检查：

### 前端 lint
```bash
cd frontend
pnpm lint
```

### 后端快速本地 agent 测试
```bash
cd backend
uv run python -m app.agents.chemist
```

---

## 7. 核心架构说明

## 7.1 后端：插件化工具架构

后端不再把工具硬编码在 agent 文件中，而是通过 `ToolRegistry` 统一注册。

每个工具需要声明：
- 工具名
- 描述
- 展示名称
- 分类
- 输出类型
- 反思提示

工具执行后统一返回 `ToolExecutionResult`，包含：
- `status`
- `summary`
- `data`
- `artifacts`
- `retry_hint`
- `error_code`

这使前端、模型、协议层都可以围绕一套稳定结构进行处理。

## 7.2 后端：结构化事件层

WebSocket 层会把 AG2 的事件转换成统一前端协议，而不是解析 stdout 文本。

当前这层已经拆成：
- `backend/app/api/chat.py`：处理 WebSocket 生命周期与 turn 启动
- `backend/app/api/event_bridge.py`：负责 AG2 事件到协议帧的转换

优点：
- 更稳定
- 更适合前端增量渲染
- 更适合调试与扩展
- 更容易接入更多工具类型

## 7.2 后端：多智能体路由架构

当前采用三阶段协作模式：

1. **Phase 1 — 路由**：Manager 路由 agent 判断本轮需要哪些专家（Visualizer / Researcher / 两者都要），结果为 JSON，带跨轮上下文消歧义。
2. **Phase 2 — 专家执行**：多个专家可并行运行（ThreadPoolExecutor），每个专家只拥有与自身职责相关的工具。事件流上携带 `sender` 字段用于前端溯源。
3. **Phase 3 — 综合回答**：Manager 综合 agent 基于专家报告生成 Markdown 格式最终答案，通过 `assistant.message` 事件发回前端，被路由至 `Turn.finalAnswer` 而非工具链日志。

## 7.3 前端：白盒 UI

前端状态流也已拆分为：
- `frontend/store/chatStore.ts`：公开状态与动作
- `frontend/lib/chat/socket.ts`：WebSocket 连接封装
- `frontend/lib/chat/state.ts`：事件归并纯函数
- `frontend/lib/chat/session.ts`：session 持久化

前端将每一轮会话拆成：
- 用户消息
- **ThinkingLog**：仅展示专家工具调用链（tool_call / tool_result / specialist agent_reply），带颜色溯源徽章
- **最终回答气泡**：展示 Manager 综合回答，使用 react-markdown + remark-gfm 渲染 Markdown
- artifact 展示（独立区域）

因此后续新增工具时，通常只需要：
1. 后端注册工具
2. 返回结构化结果
3. 如有新 artifact 类型，再扩展渲染器

---

## 8. 扩展方式

### 接入新化学软件（如 Smina、xTB、GNINA）

遵循 Phase 1 → Phase 2 路线，**先 API 测通再接入 Agent**：

**Phase 1（必做）**
1. `app/chem/smina_ops.py` — 纯 Python 计算函数，无 FastAPI 依赖
2. `app/api/smina_api.py` — 薄路由层，调用 `smina_ops`，注册到 `main.py`
3. `curl` / 脚本验证 API 正确性

**Phase 2（测通后再做）**
4. `app/tools/smina/` — Agent tool 包装，调用同一 `smina_ops` 函数
5. 可选：`app/agents/specialists/` 新增专家 agent
6. 更新 `manager.py` 路由规则

### 新增 Agent 工具（现有平台）
1. 在 `backend/app/tools/<platform>/` 下新增 `.py` 文件
2. 使用 `@tool_registry.register(...)` 装饰器
3. 从 `app/chem/<platform>_ops.py` 导入计算逻辑（禁止在 `tools/` 里写化学计算）
4. 返回 `ToolExecutionResult`，如有产物附带 `ToolArtifact`
5. `walk_packages` 自动发现，无需手动注册

### 新增前端 artifact 渲染
1. 在 `frontend/components/chat/ArtifactRenderer.tsx` 增加分支
2. 用 `kind` / `mimeType` / `data.type` 区分
3. 保持 `Artifact` TypeScript 类型契约稳定

---

## 9. 当前已验证的关键能力

- 单轮结构化流式完成闭环
- 生成分子 2D 结构图后能正确结束 run
- 图片 artifact 不再塞进正文流，而是独立渲染
- 多轮会话能保留上下文（`turn_history` 跨轮消歧义）
- 第二轮可引用上一轮分子结果继续回答
- 多智能体路由：Visualizer / Researcher 按需单路或并行执行
- Manager 综合回答 Markdown 格式化，在气泡中正确渲染
- ThinkingLog 专家溯源徽章（颜色区分 Manager / Visualizer / Researcher）

---

## 10. 后续建议路线

### 近期（化学能力扩展）

1. **Open Babel Agent 工具（Phase 2）**  
   `app/tools/babel/` 已占位，`chem/babel_ops.py` 已测通，直接包装即可

2. **Smina / GNINA 分子对接**  
   PDBQT 准备（`/api/babel/pdbqt`）已就绪；下一步接入 `smina_ops.py` 执行对接打分

3. **3D 可视化**  
   前端接入 NGL Viewer 或 3Dmol.js，渲染 `conformer3d` 返回的 SDF 内容

4. **更多 RDKit 工具**  
   分子指纹相似度、子结构搜索、ADMET 理化性质估算

### 中期（工程稳态）

5. **持久化 session**  
   当前 session 为内存态，正式上线前需接入 Redis 或 DB

6. **补充观测与审计**  
   run trace、tool latency、错误统计、工具调用日志

7. **收敛生产配置**  
   鉴权、CORS 收紧、WSS、限流、多实例部署

---

## 11. 相关文档

| 文档 | 说明 |
|---|---|
| [docs/API.md](docs/API.md) | REST API 完整请求/响应文档（含 curl 示例） |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 系统分层架构、设计决策、可扩展性分析 |
| [SOURCE_MAP.md](SOURCE_MAP.md) | 面向维护者的文件职责索引与排障指北 |

---

## 12. 一句话总结

ChemAgent 采用**计算核心层（chem/）→ HTTP API 层（api/）→ Agent 工具层（tools/）**严格三层解耦架构，任何新化学软件只需新增对应目录，不修改现有代码，即可同时服务 REST UI 和多智能体工作流。
