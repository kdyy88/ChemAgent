# ChemAgent 公司电脑受限环境启动指南（Windows）

本文针对常见公司安全策略：

- 默认 `PowerShell 5.1`（不支持 `&&` 语法）
- 脚本执行受限（常见 `pnpm.ps1` 被拦截）
- Docker 不可用或不可安装

## 1. 结论（可直接用）

项目可以在受限环境启动，推荐路径是：

1. 使用 VS Code 任务 `🧪 Start ChemAgent (No Worker)`。
2. 不依赖 Redis / Worker（后端会自动降级为进程内执行）。
3. 前端通过 `pnpm.cmd` 启动，规避 `pnpm.ps1` 执行策略限制。

## 2. 本次已修复的兼容问题

已修改 `.vscode/tasks.json`：

- 去掉 `cd xxx && yyy`，改为任务 `options.cwd` + 直接命令。
- 前端任务从 `pnpm dev` 改为 `pnpm.cmd dev`。

这样可以兼容公司常见的 `PowerShell 5.1`。

## 3. 最小启动步骤（推荐）

### Step 1: 准备环境变量

在仓库根目录执行：

```powershell
Copy-Item .env.example .env
notepad .env
```

至少填写：

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`

### Step 2: 安装依赖

```powershell
Push-Location backend
uv sync
Pop-Location

Push-Location frontend
pnpm.cmd install
Pop-Location
```

### Step 3: 启动（无 Worker 模式）

在 VS Code 中运行任务：

- `🧪 Start ChemAgent (No Worker)`

该模式会启动：

- backend: `http://localhost:8000`
- frontend: `http://localhost:3000`

## 4. 健康检查

```powershell
Invoke-WebRequest http://localhost:8000/health -UseBasicParsing
```

正常返回应包含：

```json
{"status":"ok"}
```

## 5. 常见报错与处理

### 5.1 `&& 不是有效语句分隔符`

原因：PowerShell 5.1 不支持 `&&`。

处理：已在任务中修复；若手动执行命令，请使用 `;` 或分行。

### 5.2 `pnpm.ps1 cannot be loaded because running scripts is disabled`

原因：公司执行策略拦截 PowerShell 脚本。

处理：使用 `pnpm.cmd` 代替 `pnpm`。

### 5.3 Docker 无法使用

原因：公司策略禁用 Docker Desktop / WSL。

处理：使用 `🧪 Start ChemAgent (No Worker)`，无需 Docker、Redis、Worker。

### 5.4 `uv` / `pnpm` 不存在

处理：

- `uv`: 使用公司允许的软件分发方式安装（或请 IT 下发）。
- `pnpm`: 同上；安装后优先使用 `pnpm.cmd`。

### 5.5 端口被占用（8000/3000）

处理：

```powershell
Get-NetTCPConnection -LocalPort 8000,3000 -ErrorAction SilentlyContinue |
  Select-Object LocalPort,OwningProcess
```

结束占用进程后重试，或改端口启动。

## 6. 说明

- 无 Worker 模式下，RDKit/OpenBabel 任务会在 API 进程内执行，功能可用但吞吐量低于 Redis+Worker 模式。
- 若后续公司策略允许 Docker/Redis，可切换到 `🚀 Start ChemAgent (Full Stack)`。
