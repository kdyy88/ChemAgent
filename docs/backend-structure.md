backend/app/
├── api/
│   ├── v1/                    ✅ chat.py, rdkit.py, babel.py, scratchpad.py, protocol.py
│   ├── middleware/            ✅ rate_limit.py, auth.py (占位入口)
│   ├── protocol.py            ← 已收敛到 v1/protocol.py + domain/schemas/api.py
│   ├── sse_chat.py / *_api.py ← 如需 legacy /api/* 再补兼容层
│
├── core/
│   ├── config/ security/ exceptions/  ✅ 占位骨架
│   ├── redis_pool.py          ✅ Redis / ARQ 连接池 canonical 入口
│   ├── task_queue.py          ✅ 任务结果 / artifact KV 读写 + 复用 redis_pool
│   ├── task_bridge.py / task_registry.py ← 兼容或编排层
│
├── agents/
│   ├── main_agent/            ✅ graph.py + runtime.py + engine.py + engine_sse.py
│   ├── sub_agents/            ✅ graph.py + prompts.py + runtime_tools.py
│   ├── memory/                ✅ checkpointer.py + scratchpad.py + history.py
│   ├── contracts/             ✅ protocol.py（主/子 agent 强类型契约）
│   ├── nodes/                 ✅ 真正保留在 agents 的节点实现
│   ├── state.py               ✅ shim → domain/schemas/agent.py
│   ├── config.py / prompts.py / postprocessors.py / utils.py ← agent orchestration 本地支持模块
│
├── tools/
│   ├── registry.py            ✅ deny-by-default 权限与 root/sub-agent tool 解析
│   ├── catalog.py             ✅ root tool catalog 唯一装配入口
│   ├── metadata.py            ✅ ChemToolTier 等中立元数据
│   ├── decorators.py          ✅ safe_chem_tool / chem_tool canonical 入口
│   ├── rdkit/chem_tools.py    ✅ 全部 RDKit @tool 包装器
│   ├── babel/prep.py          ✅ Open Babel @tool 包装器
│   ├── system/task_control.py ✅ tool_ask_human + tool_update_task_status
│   ├── pubchem/search.py      ✅ PubChem / Tavily 查询工具
│
├── skills/                    ✅ 全新顶级域
│   ├── base.py                ✅ SkillManifest 协议
│   ├── loader.py              ✅ Per-session 动态加载器 + Redis 存储
│   ├── builtin/rdkit_analysis/✅ 自注册 manifest（11 个工具）
│   ├── builtin/mol_3d/        ✅ 自注册 manifest（8 个工具）
│   ├── builtin/docking_prep/  ✅ 占位
│   └── custom/                ✅ 用户热加载目录
│
├── services/
│   ├── chem_engine/           ✅ rdkit_ops.py + babel_ops.py（canonical 位置）
│   ├── bio_engine/            ✅ README + 占位
│   └── task_runner/           ✅ registry.py + bridge.py + worker.py
│
└── domain/
    ├── schemas/               ✅ agent.py + api.py + chem.py + workflow.py
    └── store/                 ✅ artifact_store.py + plan_store.py + scratchpad_store.py

说明
- 当前实现已经去掉 root-level 的 graph.py / runtime.py / engine.py / sub_graph.py / lg_tools.py / decorators.py 等旧入口，避免 `backend/app/agents` 根目录继续堆积实现文件。
- tools 与 domain 现在承担真实所有权，不再只是“规划上的壳”。