# 🌟 Context Initialization: ChemAgent Project (AIDD Multi-Agent System)

你好！我们需要继续开发当前的化学多智能体项目。为了让你快速了解上下文，以下是当前项目的架构设计、技术栈和已完成的功能清单：

## 1. 技术栈 (Tech Stack)
* **后端 (Backend)**: Python 3.12+, FastAPI, `uv` (包管理)
* **前端 (Frontend)**: Next.js (App Router), React, Tailwind CSS, Shadcn UI, Zustand (状态管理)
* **Agent 框架**: AG2 (`ag2` 包，非微软 `autogen-agentchat`)
* **化学引擎**: RDKit, Open Babel (`openbabel-wheel`)
* **可视化编排**: Waldiez (`@waldiez/react` + `waldiez` python 包)

## 2. 核心系统架构 (Core Architecture)
项目采用了**高内聚、插件化**的白盒多智能体架构，并在前端实现了现代化的 **三栏 IDE 响应式工作台**：

### 2.1 后端多智能体路由 (Three-Phase Routing)
Manager 接收请求 -> 路由给对应的 Specialist (专家智能体，如 Visualizer, Analyst, Preparator) -> 并行执行 -> Manager 综合输出最终 Markdown 回答。

### 2.2 前端三栏 IDE 布局 (v2.0 Workspace Layout)
基于 `react-resizable-panels` 实现了灵活的 15/60/25 拆分：
* **区域 A: 导航侧边栏 ([ToolSidebar.tsx](cci:7://file:///home/administrator/chem-agent-project/frontend/components/workspace/ToolSidebar.tsx:0:0-0:0) / 15%)**
  复刻了 VS Code 的双态侧边栏（50px 宽度 Activity Bar + 展开的二级 Tree Menu），支持按“底层软件 (RDKit/Babel)”和“业务场景 (数据准备/生信对接)”双重维度切换功能流。
* **区域 B: 主操作工作台 ([WorkspaceArea.tsx](cci:7://file:///home/administrator/chem-agent-project/frontend/components/workspace/WorkspaceArea.tsx:0:0-0:0) / 60%)**
  承载确定性的化学专业表单。最新版本已扩充至 **12 大专业化学工具**，覆盖四大领域：
  - 数据清洗（SMILES 验证、脱盐与中和）
  - 物化性质（综合描述符与 Lipinski、原子偏电荷）
  - 结构分析（指纹相似度、子结构与 PAINS、Murcko 骨架）
  - 3D 与对接处理（万能格式转换、力场 3D 构象并提取能量、PDBQT准备、SDF 高通量文件拆分合并）
  所有组件高度复用 `<ToolLayout>`，UI 加入了 `max-w-4xl` 版心约束以保障阅读体验。
* **区域 C: AI Copilot ([CopilotSidebar.tsx](cci:7://file:///home/administrator/chem-agent-project/frontend/components/chat/CopilotSidebar.tsx:0:0-0:0) / 25%)**
  停靠在屏幕最右侧的智能体对话面板。

## 3. 已实现的黑魔法机制 (Core Mechanics)

### 3.1 隐式上下文穿透 (Context Injection)
彻底打通了左右两侧的阻隔！用户在右侧 Copilot 输入纯自然语言时（如“帮我看看这个分子的毒性”），[ChatInput.tsx](cci:7://file:///home/administrator/chem-agent-project/frontend/components/chat/ChatInput.tsx:0:0-0:0) 会在底层自动调取 Zustand 状态库中的 `currentSmiles` 和 `activeFunctionId`，拼接成隐式的系统级提示语（`[系统附加信息：用户当前正在 xxx 功能操作分子：xxx]`）发给后端，AI 因此拥有了“视觉”。

### 3.2 Actionable UI (前端 Markdown 的逆向操纵)
赋能前端闭环互动：赋予 AI 生成 `<ApplySmiles smiles="..." />` 自定义标签的能力。前端 Markdown 渲染器会拦截该标签，将其渲染为可交互的 Shadcn `<Button>`。用户点击后，会直接触发 `Zustand.setSmiles()`，从而自动改变中栏工作台的输入框内容，达成“AI 建议 -> 自动落表”的体验。

### 3.3 极简原生交互 (Elegant Implementation)
在表单重构中，极其注重视图解耦与性能。果断抛弃了臃肿的第三方树状组件和 Select 交互状态，直接使用 Tailwind 手写侧边树，并使用原生 HTML5 的 `<input list="...">` 联合 `<datalist>` 极简实现了“既支持下拉选择，又支持手写”的双态格式选择器。

## 4. 当前目标 (Current Objective)
请阅读并理解以上系统状态。我们的前后端管道已打通，前端形态确立为三栏专业 IDE 级视图。我们将基于此进行下一步的深度开发或特性追加。
