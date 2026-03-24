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
├── .env                          # ★ 统一环境变量（本地开发 + Docker 共用）
├── .env.example                  #   环境变量模板，复制后填写真实值
├── dev.sh                        #   一键本地启动脚本
├── compose.yaml                  #   Docker Compose 全栈配置
├── backend/                      # FastAPI + AG2 + RDKit + Open Babel
│   ├── app/
│   │   ├── chem/                 # ★ 纯计算核心层（不含 HTTP/Agent 依赖）
│   │   │   ├── rdkit_ops.py      #   RDKit：描述符、相似度、骨架、SA Score
│   │   │   └── babel_ops.py      #   Open Babel：格式转换、3D 构象、PDBQT 准备
│   │   ├── agents/
│   │   │   ├── config.py         #   共享 LLM 配置加载
│   │   │   ├── factory.py        #   通用 agent / tool 注册工厂
│   │   │   ├── manager.py        #   路由 agent + 综合回答 agent
│   │   │   └── specialists/
│   │   │       ├── visualizer.py #   可视化专家（draw_molecules_by_name）
│   │   │       ├── analyst.py    #   分析专家（analyze_molecule_from_smiles）
│   │   │       └── researcher.py #   检索专家（web_search）
│   │   ├── api/                  # HTTP 层：仅路由，不含化学逻辑
│   │   │   ├── rdkit_api.py      #   POST /api/rdkit/*
│   │   │   ├── babel_api.py      #   POST /api/babel/*
│   │   │   ├── chat.py           #   WebSocket 主入口
│   │   │   ├── event_bridge.py   #   AG2 事件 → 前端协议帧
│   │   │   ├── sessions.py       #   会话管理与三阶段编排
│   │   │   ├── runtime.py        #   运行期数据模型
│   │   │   └── protocol.py       #   WebSocket 输入输出模型
│   │   ├── core/
│   │   │   └── tooling.py        #   工具注册中心、结果模型、缓存
│   │   └── tools/                # Agent 工具层（按平台分组）
│   │       ├── rdkit/
│   │       │   └── analysis.py   #   analyze_molecule_from_smiles
│   │       ├── search/
│   │       │   └── web.py        #   web_search
│   │       └── babel/            #   Open Babel agent 工具（Phase 2 占位）
│   └── pyproject.toml
├── frontend/                     # Next.js UI
│   ├── app/                      #   App Router 入口
│   ├── components/chat/          #   聊天、日志、artifact 展示组件
│   ├── hooks/                    #   对外暴露的业务 hook
│   ├── lib/
│   │   ├── chem-api.ts           #   REST API 调用（rdkit + babel）
│   │   └── types.ts              #   前端类型定义
│   └── store/                    #   Zustand 状态管理
├── docs/
│   └── API.md                    # REST API 完整文档
├── README.md
└── deploy/nginx/default.conf     # nginx 反代配置
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
| `analyze_molecule_from_smiles` | RDKit | `tools/rdkit/analysis.py` | SMILES → 描述符分析 |
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

### 前置准备（三种方式共用）

**1. 配置环境变量**

根目录的 `.env` 是整个项目唯一的环境变量文件，本地开发和 Docker 均从此处读取。

```bash
cp .env.example .env
# 用编辑器填写真实值：
vim .env
```

至少需要填写：

| 变量 | 说明 |
|---|---|
| `OPENAI_API_KEY` | **必填**，LLM API Key |
| `OPENAI_BASE_URL` | 可选，中转站 URL |
| `SERPER_API_KEY` | 可选，填写后启用真实网页搜索 |

其余变量均有合理默认值，开箱即用。

**2. 安装依赖（首次）**

```bash
# 后端
cd backend && uv sync && cd ..
# 前端
cd frontend && pnpm install && cd ..
```

---

### 方式一：手动分终端启动

适合需要单独观察每个进程日志、调试单一服务的场景。开 4 个终端：

**终端 1 — Redis**
```bash
redis-server --port 6379 --maxmemory 128mb --maxmemory-policy allkeys-lru --save "" --appendonly no
```

**终端 2 — 后端 API**
```bash
cd backend
set -a && source ../.env && set +a
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 3030
```

**终端 3 — 计算 Worker**
```bash
cd backend
set -a && source ../.env && set +a
uv run arq app.worker.WorkerSettings
```

**终端 4 — 前端**
```bash
cd frontend
pnpm dev
```

服务地址：
- 前端：http://localhost:3000
- 后端文档：http://localhost:3030/docs

---

### 方式二：dev.sh 一键启动

适合日常开发，所有进程统一管理，**Ctrl+C 一次性关闭全部**。

```bash
./dev.sh
```

运行时终端输出会按颜色区分各进程：

| 颜色 | 服务 |
|---|---|
| 紫色 | Redis |
| 蓝色 | 后端 API |
| 绿色 | 计算 Worker |
| 黄色 | 前端 Next.js |

日志文件同步写入 `.dev-logs/` 目录（`redis.log`、`backend.log`、`worker.log`、`frontend.log`）。

可选参数：
```bash
./dev.sh --no-redis   # 跳过启动 Redis（已有外部 Redis 时使用）
```

---

### 方式三：Docker 启动基础服务 + 本地前端

适合**前端高频改动**的场景：Redis、后端、Worker 跑在 Docker 里保持稳定，前端在本地热更新。

**步骤 1：用 Docker 启动 Redis、后端、Worker**

```bash
docker compose up -d --build redis backend worker
```

服务启动后验证后端健康：
```bash
curl http://127.0.0.1:3030/health
```

**步骤 2：本地启动前端**

```bash
cd frontend
pnpm dev
```

前端会自动读取根目录 `.env` 中的 `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:3030`，直接对接 Docker 中的后端，无需任何额外配置。

> **说明：** `compose.yaml` 中 `REDIS_URL` 的 Docker 默认值是 `redis://redis:6379/0`（容器内部网络），会自动覆盖 `.env` 里的 `127.0.0.1:6379`，无需手动修改。

---

### 方式四：全栈 Docker 部署（生产 / 单机上线）

```bash
docker compose up -d --build
```

| 服务 | 对外地址 |
|---|---|
| 前端（nginx） | `http://your-server-ip/` |
| 后端 | `http://your-server-ip:3030/` |

> 接入 HTTPS 后，前端会自动切换到 `wss://` WebSocket。

---

## 6. 开发工作流

日常开发推荐使用 **方式二（dev.sh）** 一键拉起全栈，或 **方式三** 仅在本地跑前端。

### 常用检查命令

```bash
# 前端 TypeScript 类型检查
cd frontend && pnpm tsc --noEmit

# 前端 lint
cd frontend && pnpm lint

# 后端语法检查
cd backend && uv run python -m py_compile app/main.py

# 接口联调（验证后端是否正常）
curl http://127.0.0.1:3030/health
curl -s -X POST http://127.0.0.1:3030/api/rdkit/validate \
  -H 'Content-Type: application/json' \
  -d '{"smiles": "CC(=O)Oc1ccccc1C(=O)O"}'
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
