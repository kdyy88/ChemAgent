# ChemAgent

ChemAgent 是一个面向化学场景的全栈智能体项目，目标是通过**权威检索 + 结构化工具调用 + 可解释流式过程展示**，尽量减少化学幻觉，并为后续分子分析工具扩展提供稳定底座。

当前版本已经完成：
- 后端插件化工具注册
- 结构化事件流式协议
- 多轮 session memory
- **多智能体协作架构**（Manager 路由 + Visualizer / Researcher 专家 + 综合回答器）
- 前端白盒推理/工具链展示（专家溯源徽章）
- 通用 artifact 渲染（当前已支持图片类产物）
- 最终回答 Markdown 渲染（react-markdown + remark-gfm）

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
- requests
- websockets
- python-dotenv

---

## 3. 项目结构

```text
chem-agent-project/
├── backend/                  # FastAPI + AG2 + RDKit
│   ├── app/
│   │   ├── agents/
│   │   │   ├── config.py         # 共享 LLM 配置加载
│   │   │   ├── factory.py        # 通用 agent / tool 注册工厂
│   │   │   ├── chemist.py        # 本地 smoke test 入口
│   │   │   ├── manager.py        # 路由 agent + 综合回答 agent
│   │   │   └── specialists/
│   │   │       ├── visualizer.py # 可视化专家 agent
│   │   │       └── researcher.py # 研究检索专家 agent
│   │   ├── api/              # WebSocket 协议、会话管理、事件桥接
│   │   ├── core/             # 工具注册中心、结果模型、缓存
│   │   └── tools/            # 具体化学工具实现
│   ├── .env.example
│   └── pyproject.toml
├── frontend/                 # Next.js UI
│   ├── app/                  # App Router 入口
│   ├── components/chat/      # 聊天、日志、artifact 展示组件
│   ├── hooks/                # 对外暴露的业务 hook
│   ├── lib/                  # 类型与工具函数
│   └── store/                # Zustand 状态管理
├── README.md                 # 项目总说明
└── SOURCE_MAP.md             # 面向后续开发的源码地图
```

---

## 4. 当前能力

### 已有工具
- `get_smiles_by_name`  
  基于 PubChem 名称检索标准 Canonical SMILES
- `generate_2d_image_from_smiles`  
  基于 RDKit 将 SMILES 渲染为 2D 结构图
- `web_search`  
  通用网页搜索（当前为存根实现，可替换为 Serper / Bing 等真实接口）

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
- 当前 `web_search` 仍为 mock/stub，若要正式科研检索，建议先替换真实搜索提供方

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

### 新增后端工具
1. 在 `backend/app/tools/` 下新增文件
2. 使用 `tool_registry.register(...)` 注册
3. 返回 `ToolExecutionResult`
4. 如有产物，使用 `ToolArtifact`
5. 无需手动到 agent 中硬编码注册

### 新增前端 artifact 类型
1. 在 `frontend/components/chat/ArtifactRenderer.tsx` 中增加分支
2. 根据 `kind` / `mimeType` 渲染对应组件
3. 保持 `Artifact` 类型契约稳定

---

## 8.1 最近一次结构清理

本轮额外完成：
- 抽离共享 LLM 配置到 `backend/app/agents/config.py`
- 抽离通用 agent / executor 工厂到 `backend/app/agents/factory.py`
- 抽离运行期 plan / summary 模型到 `backend/app/api/runtime.py`
- 抽离事件桥接到 `backend/app/api/event_bridge.py`
- 去掉前端 store 中的模块级 `pendingTurn` 全局变量
- 修复 artifact 下载对象 URL 生命周期
- 删除空占位文件与过时的 `backend/main.py`

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

优先级较高：

1. **持久化 session**  
   当前 session 仍是内存态，适合开发，不适合生产

2. **补充更多化学工具**  
   如分子式、分子量、InChI、3D conformer、相似性搜索

3. **增强 artifact 体系**  
   支持 JSON 表格、结构化报告、可下载文件等

4. **补充观测与审计**  
   增加 run trace、tool latency、错误统计

5. **收敛生产配置**  
   包括鉴权、CORS、部署域名、WSS、日志与限流

---

## 11. 相关文档

- 后端说明：见 `backend/README.md`
- 前端默认模板说明：`frontend/README.md` 可后续替换为项目专属文档
- 源码地图：见 `SOURCE_MAP.md`

---

## 12. 一句话总结

ChemAgent 当前已经从“能跑的 demo”升级为“具备插件化工具能力、结构化协议能力、多轮会话能力、前后端协同能力”的化学智能体工程骨架。
