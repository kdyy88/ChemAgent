# Backend

## 环境变量

在 `backend` 目录下创建 `.env`（可参考 `.env.example`）：

- `OPENAI_API_KEY`：必填
- `OPENAI_BASE_URL`：可选（代理或私有部署，建议填到 `/v1` 级别）
- `REDIS_URL`：可选，默认 `redis://127.0.0.1:6379/0`（本地）或 `redis://redis:6379/0`（Compose）
- `CHEMAGENT_WORKER_MAX_JOBS`：可选，默认 `2`
- `CHEMAGENT_WORKER_JOB_TIMEOUT_SECONDS`：可选，默认 `120`
- `CHEMAGENT_GRAPH_RECURSION_LIMIT`：可选，默认 `60`。当 LangGraph 运行复杂任务出现“Recursion limit reached”错误时，可将其调高，例如 `120`。
- `TASK_POLL_INTERVAL_SECONDS`：可选，默认 `0.2`
- `TASK_RESULT_TTL_SECONDS` / `ARTIFACT_TTL_SECONDS`：可选，默认 `300`

说明：如果误填为包含 `/responses` 或 `/chat/completions` 的完整接口路径，程序会在启动时自动规范化。

`app/agents/chemist.py` 在启动时会自动加载 `backend/.env`。

## 本地运行

在 `backend` 目录执行：

- `uv run python -m app.agents.chemist`（智能体 smoke test）
- `uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`（API / WebSocket 网关）
- `uv run arq app.worker.WorkerSettings`（RDKit / OpenBabel 计算 worker）

## Docker / 线上环境

后端容器默认监听 `3030` 端口，并通过独立 `worker` 容器执行重计算任务。

可用环境变量：
- `OPENAI_API_KEY`：必填
- `OPENAI_BASE_URL`：可选
- `CORS_ALLOWED_ORIGINS`：逗号分隔的允许来源列表，用于 HTTP CORS 与 WebSocket Origin 校验
- `REDIS_URL`：Redis 连接串
- `CHEMAGENT_WORKER_MAX_JOBS`：worker 并发上限
- `CHEMAGENT_WORKER_JOB_TIMEOUT_SECONDS`：单任务超时秒数

示例：
- `CORS_ALLOWED_ORIGINS=http://your-server-ip,http://localhost,http://127.0.0.1`

如果通过根目录 [compose.yaml](../compose.yaml) 部署，浏览器默认会经由同域名 nginx 反代访问后端，无需在前端写死后端公网 IP。当前线上拓扑为单 `backend` worker + Redis + 独立 `worker` 进程，保证 WebSocket session 一致性。

