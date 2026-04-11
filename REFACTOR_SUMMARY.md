# ChemAgent 后端重构说明（本轮）

本轮目标是将后端从“功能堆叠”调整为“结构即实现”：按职责拆分目录，稳定主链路，降低后续扩展成本。

## 一、重构目标

- 统一后端分层，明确 API、编排、领域、服务、工具的边界。
- 保留现有运行能力（FastAPI + SSE + Worker），避免破坏既有调用方。
- 为后续新增化学工具、子代理、任务队列能力预留稳定扩展点。

## 二、重构后的完整目录与文件清单

> 说明：以下为本轮重构后的后端完整结构（已排除运行时缓存如 `__pycache__`、`.venv`、`.pytest_cache` 以及 `server.log`）。

```text
backend/
├── app/
│   ├── agents/
│   │   ├── contracts/
│   │   │   ├── __init__.py
│   │   │   └── protocol.py
│   │   ├── main_agent/
│   │   │   ├── __init__.py
│   │   │   ├── engine.py
│   │   │   ├── engine_sse.py
│   │   │   ├── graph.py
│   │   │   └── runtime.py
│   │   ├── memory/
│   │   │   ├── __init__.py
│   │   │   ├── checkpointer.py
│   │   │   ├── history.py
│   │   │   └── scratchpad.py
│   │   ├── nodes/
│   │   │   ├── __init__.py
│   │   │   ├── agent.py
│   │   │   ├── executor.py
│   │   │   ├── planner.py
│   │   │   └── router.py
│   │   ├── sub_agents/
│   │   │   ├── __init__.py
│   │   │   ├── graph.py
│   │   │   ├── prompts.py
│   │   │   ├── runtime_tools.py
│   │   │   └── tool.py
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── postprocessors.py
│   │   ├── prompts.py
│   │   └── utils.py
│   ├── api/
│   │   ├── middleware/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py
│   │   │   └── rate_limit.py
│   │   ├── v1/
│   │   │   ├── __init__.py
│   │   │   ├── babel.py
│   │   │   ├── chat.py
│   │   │   ├── protocol.py
│   │   │   ├── rdkit.py
│   │   │   └── scratchpad.py
│   │   └── __init__.py
│   ├── core/
│   │   ├── config/
│   │   │   └── __init__.py
│   │   ├── exceptions/
│   │   │   └── __init__.py
│   │   ├── security/
│   │   │   └── __init__.py
│   │   ├── __init__.py
│   │   ├── network.py
│   │   ├── redis_pool.py
│   │   └── task_queue.py
│   ├── domain/
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   ├── agent.py
│   │   │   ├── api.py
│   │   │   ├── chem.py
│   │   │   └── workflow.py
│   │   ├── store/
│   │   │   ├── __init__.py
│   │   │   ├── artifact_store.py
│   │   │   ├── plan_store.py
│   │   │   └── scratchpad_store.py
│   │   └── __init__.py
│   ├── services/
│   │   ├── bio_engine/
│   │   │   └── __init__.py
│   │   ├── chem_engine/
│   │   │   ├── __init__.py
│   │   │   ├── babel_ops.py
│   │   │   └── rdkit_ops.py
│   │   ├── task_runner/
│   │   │   ├── __init__.py
│   │   │   ├── bridge.py
│   │   │   ├── registry.py
│   │   │   └── worker.py
│   │   └── __init__.py
│   ├── skills/
│   │   ├── builtin/
│   │   │   └── __init__.py
│   │   ├── custom/
│   │   │   └── __init__.py
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── loader.py
│   ├── tools/
│   │   ├── babel/
│   │   │   ├── __init__.py
│   │   │   └── prep.py
│   │   ├── pubchem/
│   │   │   ├── __init__.py
│   │   │   └── search.py
│   │   ├── rdkit/
│   │   │   ├── __init__.py
│   │   │   └── chem_tools.py
│   │   ├── system/
│   │   │   ├── __init__.py
│   │   │   └── task_control.py
│   │   ├── catalog.py
│   │   ├── decorators.py
│   │   ├── metadata.py
│   │   └── registry.py
│   ├── main.py
│   └── worker.py
├── tests/
│   ├── __init__.py
│   ├── test_artifact_store.py
│   ├── test_chat_models_api.py
│   ├── test_engine.py
│   ├── test_executor.py
│   ├── test_prompts.py
│   ├── test_safe_chem_tool.py
│   ├── test_sub_agent.py
│   └── test_subagent_protocol.py
├── .dockerignore
├── .gitignore
├── .python-version
├── Dockerfile
├── pyproject.toml
├── README.md
└── uv.lock
```

## 三、关键设计决策

- `app/main.py` 仅负责应用装配（生命周期、路由挂载、中间件），业务逻辑下沉到对应层。
- `app/worker.py` 保留为兼容入口，真实 worker 配置位于 `services/task_runner/worker.py`。
- `agents` 只做“决策与编排”，`tools/services` 只做“执行与计算”，避免互相侵入。
- `domain/schemas` 作为统一输入输出契约，减少跨层隐式字典协议。

## 四、兼容性与运行方式

当前建议启动方式：

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
uv run arq app.worker.WorkerSettings
```

接口前缀维持在 `/api/v1/*`，现有客户端调用路径不需要迁移。

## 五、`__pycache__` 处理说明

- `__pycache__` 是 Python 运行时自动生成的字节码缓存目录，不是源码。
- 已执行清理：当前工作区内 `__pycache__` 数量为 `0`。
- 可安全删除；后续运行 Python 时会自动再生成。
- 仓库已通过 `backend/.gitignore` 忽略：
  - `__pycache__/`
  - `*.py[oc]`

## 六、后续建议

- 在新增能力时遵循“先分层再实现”：API → agent/service → tool/domain。
- 新增工具优先落在 `tools/*`，通过 `skills` 或 `agents` 进行编排接入。
- 保持 `domain/schemas` 的单一事实来源，避免重复定义请求/响应结构。
