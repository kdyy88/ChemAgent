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

当前仍然保持白盒多智能体设计：

1. Manager 接收用户请求
2. 路由给不同 Specialist
3. Specialist 并行分析 / 处理
4. Manager 汇总输出最终 Markdown 结果

前端与多智能体系统之间还保留两个重要机制：

### 4.1 隐式上下文穿透
右侧 Copilot 会自动读取当前：
- `currentSmiles`
- `activeFunctionId`

并拼接为系统附加信息发给后端，使 AI 知道用户当前正在操作什么分子、处于哪个工具流。

### 4.2 Actionable UI
AI 可以输出类似 `<ApplySmiles smiles="..." />` 的自定义标签，前端会把它渲染为按钮，并在点击后自动把建议结构写回工作台输入框。

---

## 5. 最近完成的重要改造

以下内容是上一轮开发中已经完成的关键升级：

### 5.1 并发与性能优化
- 引入 Redis + ARQ
- 重计算接口迁移到 Worker
- 后端 API 进程降为单 `uvicorn` worker
- Worker 并发由环境变量控制
- 通过 TTL 和 LRU 约束 Redis 内存占用

### 5.2 SDF 文件流重构
- 旧的进程内 latest cache 已移除
- SDF split / merge 的下载制品改为 Redis TTL 存储
- 下载接口改为基于 `result_id` / `download_id`

### 5.3 WebSocket 稳定性增强
- 新增 `ping` / `pong` 心跳
- 前端加入自动重连
- 前端持久化 `session_id`

### 5.4 前端 API 访问修正
- 本地 `pnpm dev` + Docker 后端 模式下：
  - 前端 REST 应访问 `http://127.0.0.1:3030/api/...`
  - 前端 WS 应访问 `ws://127.0.0.1:3030/api/chat/ws`
- 前端新增独立 REST 基址变量：`NEXT_PUBLIC_API_BASE_URL`
- 不再把 REST 地址和 WS 地址做复杂联动推导

### 5.5 CORS 问题已修复
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

在上一轮变更后，以下链路已经验证通过：

- `POST /api/rdkit/validate`
- `POST /api/babel/conformer3d`
- `POST /api/babel/sdf-split`
- `GET /api/babel/sdf-split-download?result_id=...`
- `POST /api/babel/sdf-merge`
- `GET /api/babel/sdf-merge-download?result_id=...`
- CORS 预检与跨域 POST（本地前端 -> Docker 后端）

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

---

## 9. 建议 AI 在新对话中默认知道的事情

如果你是下一轮对话中的 AI，请默认理解以下事实：

- 这是一个 **化学专业工具 + 多智能体 Copilot** 的混合系统
- 前端是 **三栏专业 IDE**，而不是普通聊天页面
- 后端已经完成 **Redis + ARQ 并发架构改造**
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

1. **前端错误提示优化**
	- 将 `Failed to fetch`、队列错误、CORS 错误转为更明确的人类可读提示

2. **运行态可观测性**
	- 展示 worker 状态、活跃 session 数、队列积压情况

3. **工具结果可复用性增强**
	- 将确定性工具结果与 AI Copilot 更紧密联动

4. **工作流编排增强**
	- 将 Waldiez/工作流编辑器与当前工具链做更深集成

---

## 11. 结论

ChemAgent 当前已经不是一个简单 Demo，而是：

- 前端：专业三栏化学 IDE
- 后端：轻网关 + Redis + Worker 并发系统
- AI：具备上下文感知与可回填交互能力的化学 Copilot

后续所有开发都应建立在这一事实上：

**要在保持架构清晰的前提下，继续提升稳定性、专业性与工作流闭环能力。**
