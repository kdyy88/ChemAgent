# Backend

## 环境变量

在 `backend` 目录下创建 `.env`（可参考 `.env.example`）：

- `OPENAI_API_KEY`：必填
- `OPENAI_BASE_URL`：可选（代理或私有部署，建议填到 `/v1` 级别）

说明：如果误填为包含 `/responses` 或 `/chat/completions` 的完整接口路径，程序会在启动时自动规范化。

`app/agents/chemist.py` 在启动时会自动加载 `backend/.env`。

## 本地运行

在 `backend` 目录执行：

- `uv run python -m app.agents.chemist`

## Docker / 线上环境

后端容器默认监听 `3030` 端口。

可用环境变量：
- `OPENAI_API_KEY`：必填
- `OPENAI_BASE_URL`：可选
- `CORS_ALLOWED_ORIGINS`：逗号分隔的允许来源列表，用于 HTTP CORS 与 WebSocket Origin 校验

示例：
- `CORS_ALLOWED_ORIGINS=http://your-server-ip,http://localhost,http://127.0.0.1`

如果通过根目录 [compose.yaml](../compose.yaml) 部署，浏览器默认会经由同域名 nginx 反代访问后端，无需在前端写死后端公网 IP。

