backend/app/
├── api/
│   ├── v1/                    ✅ chat.py, rdkit.py, babel.py, artifacts.py
│   ├── middleware/             ✅ rate_limit.py, auth.py (占位)
│   ├── protocol.py            ← shim → domain/schemas/api.py
│   ├── sse_chat.py / *_api.py ← 保留为向后兼容 (legacy /api/*)
│
├── core/
│   ├── config/ security/ exceptions/  ✅ 占位骨架
│   ├── redis_pool.py          ✅ 连接池（从 task_queue.py 提取）
│   ├── task_queue.py / task_bridge.py / task_registry.py ← shims
│
├── agents/
│   ├── main_agent/            ✅ graph.py + runtime.py
│   ├── sub_agents/            ✅ explore/ compute/ plan/ custom/
│   ├── memory/                ✅ checkpointer.py + scratchpad/ history/
│   ├── contracts/             ✅ delegation.py + report.py (强类型契约)
│   ├── state.py / graph.py / runtime.py / lg_tools.py ← shims
│
├── tools/
│   ├── registry.py            ✅ ToolPermission + ToolEntry + ToolRegistry
│   ├── rdkit/chem_tools.py    ✅ 全部 @tool 包装器（从 lg_tools.py 迁移）
│   ├── babel/prep.py          ✅ 更新 imports → services/chem_engine/
│   ├── system/task_status.py  ✅ tool_ask_human + tool_update_task_status
│   ├── pubchem/ execution/    ✅ 占位扩展点
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
    ├── schemas/               ✅ agent.py + api.py + chem.py
    └── store/                 ✅ artifact_store.py + plan_store.py