## Plan: ChemAgent SaaS 存储底座全量重构（V2）

**TL;DR**：以"存储矩阵"为核心建立五条数据通路——①PostgreSQL 存聊天历史（LangGraph AsyncPostgresSaver）+ 元数据；②本地文件系统隔离存用户上传附件；③Redis 继续管热数据；④artifacts 智能路由（<1MB→Redis，≥1MB→本地FS）；⑤全程通过 `core/context.py` 的 `contextvars` 注入三层租户隔离。前端、现有 Redis artifact 路由、Worker 逻辑**零破坏**。

---

### 存储矩阵（最终确认）

| 资产类型 | 存储介质 | 隔离键路径 |
|---------|---------|-----------|
| 聊天历史 & LangGraph 状态 | PostgreSQL (`langgraph_checkpoints` 表，由官方包管理) | `thread_id = {tenant_id}:{workspace_id}:{session_id}` |
| 租户/用户/工作区元数据 | PostgreSQL (SQLModel 管理) | `tenant_id` FK 行级过滤 |
| 上传附件（PDB/SDF/PDF 等） | 本地文件系统 | `{UPLOAD_ROOT}/{tenant_id}/{workspace_id}/uploads/{file_id}.ext` |
| 生成产物（≥1MB） | 本地文件系统 | `{UPLOAD_ROOT}/{tenant_id}/{workspace_id}/artifacts/{artifact_id}` |
| 生成产物（<1MB/运行时） | Redis（现有）| key: `{tenant_id}:{workspace_id}:artifact:{artifact_id}` |
| 分布式锁/限流/队列 | Redis（不动） | 不变 |

---

### Phase 1 — 统一配置层

1. **修改 core/config/__init__.py** → 用 `pydantic-settings` 创建 `Settings` 单例（`@lru_cache`），统一管理所有环境变量：
   - `database_url: str`（默认 `sqlite+aiosqlite:///./chemagent.db`）
   - `redis_url: str`
   - `cors_origins: list[str]`
   - `upload_root: Path`（默认 `./data/uploads`）
   - `artifact_size_threshold_bytes: int = 1_048_576`（1MB 智能路由阈值）
   - `artifact_temp_ttl_seconds`, `artifact_workspace_ttl_seconds`
   - `worker_max_jobs`, `worker_job_timeout`
   - `dev_mode: bool = True`（控制 auth bypass）
   - `auto_create_tables: bool = True`（dev 自动建表，prod 走 Alembic）
2. **逐步替换** core/redis_pool.py、core/network.py、main.py、services/task_runner/worker.py 中散落的 `os.getenv()` 调用，改为 `get_settings()`。

---

### Phase 2 — 租户上下文枢纽

3. **新建 core/context.py**：
   - `TenantContext` dataclass：`tenant_id: str`、`workspace_id: str`、`user_id: str`、`session_id: str | None = None`
   - `_ctx_var: ContextVar[TenantContext | None] = ContextVar("tenant_ctx", default=None)`
   - 四个函数：`get_current_context()`、`set_context(ctx) → Token`、`reset_context(token)`、`require_context() → TenantContext`（无 context 时抛 401）
   - 异步上下文管理器 `context_scope(ctx)` 供 Worker 手动设置
4. **新建 api/middleware/context.py** — `TenantContextMiddleware(BaseHTTPMiddleware)`：
   - 调用 `auth.resolve_tenant_context(request)` 获取 `TenantContext`
   - 用 `context_scope()` 包裹 `await call_next(request)`，确保请求结束后自动清理
5. **修改 api/middleware/auth.py** — 实现 `resolve_tenant_context(request) → TenantContext`：
   - `dev_mode=True`：从请求头 `X-Tenant-Id`、`X-Workspace-Id`、`X-User-Id` 读取，缺失时使用默认值 `tenant_id="dev"` 等（允许现有无 header 的调用无缝兼容）
   - `dev_mode=False`：骨架函数 + `# TODO: validate Bearer token via MSAL/Azure AD B2C`，返回 401
6. **修改 main.py** — CORS middleware 之后注册 `TenantContextMiddleware`。

---

### Phase 3 — 基础设施防腐层

**3a — 数据库层** *(依赖 Phase 1)*

7. **新建 `infrastructure/database/__init__.py`** — `create_async_engine` + `async_sessionmaker`，URL 读 `settings.database_url`；暴露 `get_db_session()` FastAPI Depends 函数。
8. **新建 `infrastructure/database/models.py`** — SQLModel 表定义（所有主键用 `uuid4`，`tenant_id` 上建索引）：
   - `Tenant(id, name, slug, plan_tier, created_at)`
   - `User(id, tenant_id FK, external_id[MS OID预留], email, role, created_at)`
   - `Workspace(id, tenant_id FK, name, description, created_at)`
   - `Session(id, workspace_id FK, user_id FK, thread_id UNIQUE, created_at, last_active_at)` — `thread_id` 格式：`{tenant_id}:{workspace_id}:{session_uuid}`，这是 LangGraph checkpointer 的 `thread_id`
   - `FileRecord(id, workspace_id FK, uploader_id FK, filename, content_type, size_bytes, local_path, created_at)` — `local_path` 存相对路径如 `{tenant_id}/{workspace_id}/uploads/{file_id}.ext`
   - `ArtifactRecord(id, workspace_id FK, session_id FK, kind, size_bytes, storage_backend[redis|local], storage_ref, created_at)` — `storage_ref` 对 Redis 是 key，对本地是相对路径

**3b — 本地文件存储层** *(依赖 Phase 1)*

9. **新建 `infrastructure/local_store/__init__.py`** — `LocalFileStore` 类：
   - `async def save(tenant_id, workspace_id, category, filename, content: bytes) → str`（返回相对 path）
   - `async def read(relative_path) → bytes`
   - `async def delete(relative_path) → None`
   - `async def read_stream(relative_path) → AsyncIterator[bytes]`（供大文件流式下载）
   - 内部路径拼接：`settings.upload_root / tenant_id / workspace_id / category / filename`，自动 `mkdir -p`
   - 路径安全：对所有 ID 做 `re.match(r'^[A-Za-z0-9_-]{1,64}$')` 校验，防 path traversal

**3c — 转发层（向后兼容）**

10. **新建 `infrastructure/cache/__init__.py`** → re-export `core/redis_pool`（旧代码 import 路径不变）
11. **新建 `infrastructure/message_queue/__init__.py`** → re-export `core/task_queue`

---

### Phase 4 — LangGraph Postgres Checkpointer *(依赖 Phase 3a)*

12. **修改 agents/memory/checkpointer.py** — 替换现有 SQLite Checkpointer：
    - 导入 `langgraph_checkpoint_postgres.AsyncPostgresSaver`
    - `initialize_graph_runtime()` 中：若 `settings.database_url` 含 `sqlite` 则用旧 `SqliteSaver`（dev 兜底），否则用 `AsyncPostgresSaver`
    - 调用 `saver.setup()` 自动创建 `langgraph_checkpoints`、`langgraph_checkpoint_writes` 等表（官方包负责 schema）
    - `thread_id` 生成规则统一为 `{tenant_id}:{workspace_id}:{session_id}`，在 `agents/main_agent/engine.py` 的 `config` 字典里设置

---

### Phase 5 — 数据层多租户命名空间 *(依赖 Phase 2)*

13. **修改 domain/store/artifact_store.py** — 智能路由升级：
    - 读 `get_current_context()` 获取 tenant/workspace（无 context 时用空字符串，保持现有 key 格式向后兼容）
    - Redis key 变为 `{tenant_id}:{workspace_id}:artifact:{artifact_id}`（有 context）或 `artifact:{artifact_id}`（无 context）
    - `store_engine_artifact()` 新增 `size_bytes` 判断：`<= settings.artifact_size_threshold_bytes` → 存 Redis；超出 → 存本地 FS via `LocalFileStore`，返回 `ArtifactRecord`
14. **修改 domain/store/plan_store.py** — 路径注入 TenantContext（有 context：`{tenant_id}/{workspace_id}/{session_id}/{plan_id}.md`；无 context：现有格式）
15. **修改 domain/store/scratchpad_store.py** — 同上，路径前缀注入。
16. **新建 `domain/store/file_store.py`** — 用户上传附件的门面层：
    - `async def register_upload(filename, content_type, size_bytes, local_path) → FileRecord` → 写入 PostgreSQL `file_records` 表
    - `async def get_file(file_id) → FileRecord | None` → 校验 `workspace_id` 匹配 TenantContext（防越权访问）
    - `async def list_workspace_files(limit, offset) → list[FileRecord]`
17. **修改 domain/schemas/agent.py** — `ChemState` 添加 `tenant_id: str | None`、`workspace_id: str | None`，默认 `None`。

---

### Phase 6 — 文件上传 API *(依赖 Phase 3b + Phase 5)*

18. **新建 api/v1/assets.py** — 三个端点：
    - `POST /api/v1/assets/upload` — 接收 multipart/form-data，大小上限由 `settings.max_upload_bytes`（默认 200MB）控制；内部调用 `LocalFileStore.save()` + `file_store.register_upload()`；返回 `{file_id, filename, size_bytes}`
    - `GET /api/v1/assets/{file_id}` — 流式下载（`StreamingResponse`），先校验 TenantContext 中 workspace_id 与 FileRecord 匹配，再 `LocalFileStore.read_stream()`
    - `GET /api/v1/assets/` — 列出当前 workspace 的文件列表
    - 在 main.py 中注册该 router

---

### Phase 7 — 依赖与基础设施更新

19. **修改 pyproject.toml** — 新增依赖：
    - `pydantic-settings>=2.0`
    - `sqlmodel>=0.0.21`
    - `alembic>=1.13`
    - `aiosqlite>=0.20`（dev SQLite 异步驱动）
    - `asyncpg>=0.29`（prod PostgreSQL 异步驱动）
    - `langgraph-checkpoint-postgres>=2.0`（官方 PG checkpointer）
    - `python-multipart>=0.0.22`（已有，确认版本）
20. **修改 compose.yaml** — 新增 `postgres` 服务（`postgres:16-alpine`），配置 healthcheck；backend/worker `depends_on` 加 postgres 条件；新增环境变量 `DATABASE_URL`、`CHEMAGENT_UPLOAD_ROOT`。
21. **修改 main.py** — `lifespan` startup 中：调用 `SQLModel.metadata.create_all(engine)` 建非 LangGraph 的表（Tenant/User/Workspace/Session/FileRecord/ArtifactRecord）。

---

### 新增文件清单

```
backend/app/
├── core/
│   └── context.py                       🆕
├── infrastructure/
│   ├── __init__.py                      🆕
│   ├── cache/__init__.py                🆕
│   ├── database/
│   │   ├── __init__.py                  🆕
│   │   └── models.py                    🆕
│   ├── local_store/
│   │   └── __init__.py                  🆕
│   └── message_queue/__init__.py        🆕
├── api/
│   ├── middleware/context.py            🆕
│   └── v1/assets.py                     🆕
└── domain/
    └── store/file_store.py              🆕
```

### 修改文件清单

```
core/config/__init__.py                  大改（占位→真实 Settings）
api/middleware/auth.py                   实现 resolve_tenant_context()
agents/memory/checkpointer.py           SQLite → AsyncPostgresSaver 双模
domain/store/artifact_store.py          Redis key 命名空间 + 大文件路由本地 FS
domain/store/plan_store.py              路径注入 TenantContext
domain/store/scratchpad_store.py        路径注入 TenantContext
domain/schemas/agent.py                 ChemState 添加 tenant_id/workspace_id
main.py                                 注册中间件 + 注册 assets router + DB 建表
pyproject.toml                         5 个新依赖
compose.yaml                           postgres 服务 + 环境变量
```

---

### 验证步骤

1. `uv add pydantic-settings sqlmodel alembic aiosqlite asyncpg langgraph-checkpoint-postgres` → `uv run pytest tests/` 全绿
2. `uv run uvicorn app.main:app --reload` → 启动日志无报错，`chemagent.db`（SQLite dev）自动创建
3. `uv run arq app.worker.WorkerSettings` → Worker 启动无报错
4. `curl -H "X-Tenant-Id: t1" -H "X-Workspace-Id: ws1" -H "X-User-Id: u1" http://localhost:8000/health` → 200
5. 文件上传测试：`curl -F file=@test.pdb -H "X-Tenant-Id: t1" -H "X-Workspace-Id: ws1" -H "X-User-Id: u1" http://localhost:8000/api/v1/assets/upload` → 返回 `{file_id, filename, size_bytes}`，检查 `./data/uploads/t1/ws1/uploads/` 目录出现文件
6. 发一条 chat，检查 Redis `KEYS *` → artifact key 带 `t1:ws1:` 前缀
7. 跑 `docker compose up postgres backend` → backend 连接 Postgres，`langgraph_checkpoints` 表自动出现
8. 再次全量跑 `pytest` → 全绿（尤其 `test_artifact_store.py`、`test_executor.py`）

---

### 决策备忘

- **MinIO/S3 不引入**：`LocalFileStore` 路径结构设计为 `{tenant_id}/{workspace_id}/{category}/{uuid}.ext`，未来无缝迁移 S3（只需替换底层 `save()`/`read()` 实现）
- **LangGraph Checkpointer 双模**：`database_url` 含 `sqlite` → 用 `SqliteSaver`（dev），含 `postgresql` → 用 `AsyncPostgresSaver`（prod/CI）
- **Alembic 留空**：dev 用 `create_all` 自动建表，`auto_create_tables=True`；生产环境关闭 `auto_create_tables`，改走 `alembic upgrade head`
- **Worker 中租户上下文恢复**：ARQ worker 从队列取任务时无 HTTP 请求，在 `task_runner/worker.py` 的 `run_chem_task()` 中从任务 kwargs 读取 `_tenant_ctx` 字典，调用 `set_context()` 手动恢复——这是 Phase 5 中必须处理的细节
- **path traversal 防护**：`LocalFileStore` 对所有 ID 参数做严格 `^[A-Za-z0-9_-]{1,64}$` 正则校验，不依赖 `os.path.join` 的自然行为



---

### 新建文件（14 个）

| 文件 | 说明 |
|------|------|
| core/context.py | **完整可用**的 `TenantContext` + `ContextVar` 实现，无任何外部依赖（stdlib 纯享） |
| infrastructure/__init__.py | 整层职责说明 + 依赖规则 |
| infrastructure/cache/__init__.py | Redis 热数据边界说明 + 待取消注释的 re-export |
| infrastructure/database/__init__.py | 完整 engine+session 骨架（注释态），待 `sqlmodel` 依赖引入后取消注释 |
| infrastructure/database/README.md | 6 张表完整 Schema、双模 URL 表格、LangGraph Checkpointer 切换方案、行级隔离策略 |
| infrastructure/database/models.py | SQLModel 表定义骨架（带完整字段注释例子） |
| infrastructure/local_store/__init__.py | `LocalFileStore` 接口注释 + path traversal 防护说明 |
| infrastructure/local_store/README.md | 路径布局、安全边界、S3 迁移替换边界、智能路由阈值说明 |
| infrastructure/message_queue/__init__.py | `enqueue_task` 包装器设计 + TenantContext 序列化方案 |
| api/middleware/context.py | `TenantContextMiddleware` 完整设计文档 + 骨架 + 豁免路径方案 |
| api/v1/assets.py | 三个端点骨架（`raise NotImplementedError`，**未挂载到 main.py**） |
| domain/store/file_store.py | `register_upload/get_file/list/delete` 四个函数骨架 |

### 修改文件（4 个，仅加注释）

| 文件 | 修改内容 |
|------|---------|
| core/config/__init__.py | 完整 `Settings` 类蓝图（注释态）+ 迁移顺序 |
| api/middleware/auth.py | dev header bypass + MSAL 接入方案（注释态），运行时行为不变 |
| agents/memory/checkpointer.py | `AsyncPostgresSaver` 切换方案 + `thread_id` 命名规范 |

Made changes.