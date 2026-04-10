# ChemAgent — API 文档

> 最后更新：2026-04-10  
> 所有路径均相对于后端根 URL（默认 `http://localhost:8000`）。

---

## 目录

1. [SSE 对话接口（`/api/chat`）](#1-sse-对话接口apichat)
2. [RDKit REST 接口（`/api/rdkit`）](#2-rdkit-rest-接口apirdkit)
3. [OpenBabel REST 接口（`/api/babel`）](#3-openbabel-rest-接口apibabel)
4. [Scratchpad 接口（`/api/scratchpad`）](#4-scratchpad-接口apiscratchpad)
5. [SSE 事件参考](#5-sse-事件参考)
6. [通用约定](#6-通用约定)

---

## 1. SSE 对话接口（`/api/chat`）

### 1.1 POST `/api/chat/stream`

启动一轮对话并以 Server-Sent Events 流式返回响应。

**请求头**

```
Content-Type: application/json
```

**请求体** `StreamChatRequest`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `message` | `string` | ✓ | 用户输入的化学问题或指令 |
| `session_id` | `string` | — | 会话唯一 ID，省略时服务端自动生成（`uuid4().hex`）；传入相同 ID 可延续历史对话 |
| `turn_id` | `string` | — | 客户端生成的轮次 ID，回传至所有 SSE 事件以供关联 |
| `model` | `string\|null` | — | 本轮使用的模型 ID；省略时使用 `OPENAI_MODEL` 环境变量默认值 |
| `active_smiles` | `string\|null` | — | 当前画布激活的 SMILES（前端状态同步） |
| `interrupt_context` | `object\|null` | — | HITL 恢复上下文；包含 `interrupt_id` 等字段，用于从已暂停的图断点继续 |
| `history` | `HistoryMessage[]` | — | 前序对话历史（按时间正序；`role` 为 `"human"` 或 `"assistant"`） |

**响应** `text/event-stream`

每个 SSE 帧格式：

```
data: {"type": "<event_type>", "session_id": "...", "turn_id": "...", ...}\n\n
```

参见 [§5 SSE 事件参考](#5-sse-事件参考)。

---

### 1.2 POST `/api/chat/approve`

在 Hard Breakpoint 暂停后，提交用户对重量级工具或计划的审批决定，恢复流式执行。

**请求体** `ApproveToolRequest`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `session_id` | `string` | ✓ | 正在等待审批的会话 ID |
| `turn_id` | `string` | — | 客户端生成的新轮次 ID |
| `action` | `"approve"\|"reject"\|"modify"` | ✓ | 审批决定 |
| `args` | `object\|null` | — | 修改后的工具参数（仅 `action="modify"` 时有效） |
| `plan_id` | `string\|null` | — | 计划审批流的稳定 ID；有此字段表示针对计划审批而非普通工具断点 |

**响应** `text/event-stream`（同 `/stream`）

---

### 1.3 GET `/api/chat/models`

获取当前可用模型列表。

**响应** `ModelCatalogResponse`

```json
{
  "source": "provider",
  "models": [
    { "id": "gpt-4o", "object": "model", "created": 0, "owned_by": "openai" }
  ],
  "warning": null
}
```

---

### 1.4 GET `/api/chat/artifacts/{artifact_id}`

按 Artifact ID 取回数据面内容（图像 base64、SDF 文本、PDBQT 等）。

**路径参数**

| 参数 | 说明 |
|------|------|
| `artifact_id` | 由 SSE `artifact` 事件中 `artifact_id` 字段提供 |

**响应**

```json
{
  "artifact_id": "art_1a2b3c4d",
  "data": { ... }
}
```

**错误** `404` — Artifact 不存在或已过期（默认 TTL 300 秒）。

---

### 1.5 GET `/api/chat/plans/{plan_id}`

按计划 ID 取回文件型计划文档（Markdown 或 JSON）。

**路径参数 + 查询参数**

| 参数 | 位置 | 说明 |
|------|------|------|
| `plan_id` | path | 计划稳定 ID（由 SSE `interrupt` 事件中 `plan_id` 字段提供） |
| `session_id` | query ✓ | 所属会话 ID |

**错误** `404` — 计划不存在；`422` — 参数非法。

---

## 2. RDKit REST 接口（`/api/rdkit`）

所有端点均接受 JSON 请求体，返回 JSON。由 ARQ Worker 执行（Redis 不可用时进程内 fallback）。

### 2.1 POST `/api/rdkit/validate`

验证 SMILES 合法性并返回标准化形式。

**请求体**

```json
{ "smiles": "CC(=O)Oc1ccccc1C(=O)O" }
```

**响应（成功）**

```json
{
  "is_valid": true,
  "canonical_smiles": "CC(=O)Oc1ccccc1C(=O)O",
  "inchi": "InChI=1S/...",
  "molecular_formula": "C9H8O4",
  "molecular_weight": 180.16
}
```

---

### 2.2 POST `/api/rdkit/descriptors`

计算全套分子描述符（分子量、logP、TPSA、Lipinski 规则等）。

**请求体**

```json
{ "smiles": "CC(=O)Oc1ccccc1C(=O)O", "name": "aspirin" }
```

---

### 2.3 POST `/api/rdkit/similarity`

计算两分子之间的摩根指纹 Tanimoto 相似度。

**请求体**

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `smiles1` | `string` | — | 第一个分子 SMILES |
| `smiles2` | `string` | — | 第二个分子 SMILES |
| `radius` | `int` | `2` | Morgan 半径（`2` = ECFP4），范围 1–6 |
| `n_bits` | `int` | `2048` | 指纹位长 |

---

### 2.4 POST `/api/rdkit/substructure`

SMARTS 子结构匹配。

**请求体**

```json
{ "smiles": "CC(=O)Oc1ccccc1C(=O)O", "smarts_pattern": "c1ccccc1" }
```

---

### 2.5 POST `/api/rdkit/scaffold`

提取 Bemis-Murcko 骨架及通用骨架。

**请求体**

```json
{ "smiles": "CC(=O)Oc1ccccc1C(=O)O" }
```

---

### 2.6 POST `/api/rdkit/salt-strip`

去除盐片段并中性化。

**请求体**

```json
{ "smiles": "[Na+].[O-]c1ccccc1" }
```

---

### 2.7 POST `/api/rdkit/analyze` *(deprecated)*

兼容旧版接口，行为等同 `/descriptors`，建议迁移。

---

## 3. OpenBabel REST 接口（`/api/babel`）

### 3.1 POST `/api/babel/convert`

分子格式互转（支持 Open Babel 所有格式）。

**请求体**

| 字段 | 类型 | 说明 |
|------|------|------|
| `molecule` | `string` | 输入分子字符串（SMILES、InChI、SDF 文本等） |
| `input_format` | `string` | Open Babel 格式代码，如 `"smi"`、`"inchi"`、`"sdf"` |
| `output_format` | `string` | 目标格式代码，如 `"sdf"`、`"mol2"`、`"pdb"`、`"inchi"` |

---

### 3.2 POST `/api/babel/conformer3d`

生成力场优化后的 3D 构象（输出 SDF）。

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `smiles` | `string` | — | 标准 SMILES |
| `name` | `string` | `""` | 化合物名称（用于文件名） |
| `forcefield` | `string` | `"mmff94"` | 力场：`"mmff94"` 或 `"uff"` |
| `steps` | `int` | `500` | 共轭梯度优化步数，范围 10–5000 |

---

### 3.3 POST `/api/babel/pdbqt`

为 AutoDock Vina 等分子对接软件准备配体 PDBQT 文件。

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `smiles` | `string` | — | 标准 SMILES |
| `name` | `string` | `""` | 化合物名称 |
| `ph` | `float` | `7.4` | 质子化 pH，范围 0–14 |

---

### 3.4 POST `/api/babel/properties`

使用 OpenBabel 计算核心分子属性。

**请求体**

```json
{ "smiles": "CC(=O)Oc1ccccc1C(=O)O" }
```

---

### 3.5 POST `/api/babel/partial-charges`

计算每原子部分电荷。

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `smiles` | `string` | — | 标准 SMILES |
| `method` | `string` | `"gasteiger"` | 电荷模型：`gasteiger`、`mmff94`、`qeq`、`eem` |

---

### 3.6 GET `/api/babel/formats`

列出所有 Open Babel 支持的输入/输出格式。

---

### 3.7 POST `/api/babel/sdf-split`

将多分子 SDF 文件拆分为独立 SDF 文件 ZIP 包。

**请求** `multipart/form-data`

| 字段 | 说明 |
|------|------|
| `file` | 待拆分的 SDF 文件（`.sdf`） |

**响应**

```json
{
  "result_id": "sdf_split_xxxx",
  "molecule_count": 42,
  "filenames": ["mol_001.sdf", "mol_002.sdf", "..."]
}
```

用 `result_id` 调用 [`GET /api/babel/sdf-split-download`](#38-get-apibabelsdf-split-download) 下载 ZIP。

---

### 3.8 GET `/api/babel/sdf-split-download`

按 `result_id` 下载 SDF 拆分 ZIP。

**查询参数** `?result_id=sdf_split_xxxx`

**响应** `application/zip`（`Content-Disposition: attachment`）

---

### 3.9 POST `/api/babel/sdf-merge`

将多个 SDF 文件合并为单一 SDF 文件。

**请求** `multipart/form-data`，字段名 `files`（多文件）

---

### 3.10 GET `/api/babel/sdf-merge-download`

按 `result_id` 下载合并后的 SDF 文件。

---

## 4. Scratchpad 接口（`/api/scratchpad`）

### 4.1 GET `/api/scratchpad/{scratchpad_id}`

读取子 agent 写入的暂存条目。

**路径参数**

| 参数 | 说明 |
|------|------|
| `scratchpad_id` | 必须匹配 `^sp_[A-Za-z0-9]{12}$` |

**查询参数**

| 参数 | 必填 | 说明 |
|------|------|------|
| `session_id` | ✓ | 父会话 ID |
| `sub_thread_id` | ✓ | 子 agent 线程 ID |

**响应** `ScratchpadResponse`

```json
{
  "scratchpad_id": "sp_AbCdEfGhIjKl",
  "kind": "report",
  "summary": "Sub-agent 计算摘要",
  "size_bytes": 1024,
  "created_by": "sub_agent",
  "content": "..."
}
```

**错误** `400` — 参数不合法（ID 格式或路径安全校验失败）；`404` — 条目不存在。

---

## 5. SSE 事件参考

所有 SSE 事件均以 `data: <JSON>\n\n` 格式发送，每条 JSON 包含通用字段：

| 字段 | 说明 |
|------|------|
| `type` | 事件类型（见下表） |
| `session_id` | 会话 ID |
| `turn_id` | 轮次 ID |

### 事件类型

| `type` | 含义 | 附加字段 |
|--------|------|----------|
| `token` | LLM 流式 token | `content: string` |
| `thinking` | Agent 推理 / UI 状态文本 | `content: string` |
| `node_start` | LangGraph 节点开始执行 | `node: string` |
| `node_end` | LangGraph 节点执行结束 | `node: string` |
| `tool_start` | `@tool` 调用开始 | `tool_name: string`, `tool_call_id: string`, `args: object` |
| `tool_end` | `@tool` 调用完成 | `tool_name: string`, `tool_call_id: string`, `result: object` |
| `artifact` | 富 Artifact 可用（图像 / SDF / PDBQT） | `artifact_id: string`, `kind: string`, `title: string`，以及原始数据字段 |
| `task_update` | 计划任务状态更新 | `tasks: Task[]` |
| `interrupt` | HITL 暂停：等待用户决策 | `interrupt_type: "approval_required"\|"plan_approval_request"\|"ask_human"`, 附完整上下文 |
| `shadow_error` | 检测到无效 SMILES（Shadow Lab） | `smiles: string`, `error: string` |
| `done` | 图执行完成（最终事件） | — |
| `error` | 不可恢复错误，流终止 | `message: string` |

### `interrupt` 事件详解

**工具 Hard Breakpoint**（`interrupt_type: "approval_required"`）

```json
{
  "type": "interrupt",
  "interrupt_type": "approval_required",
  "tool_call_id": "call_abc",
  "tool_name": "tool_prepare_pdbqt",
  "args": { ... }
}
```

使用 `POST /api/chat/approve` 传 `action: "approve"/"reject"/"modify"` 恢复。

**计划审批**（`interrupt_type: "plan_approval_request"`）

```json
{
  "type": "interrupt",
  "interrupt_type": "plan_approval_request",
  "plan_id": "plan_xxxx",
  "plan_file_ref": "...",
  "summary": "计划概要"
}
```

使用 `POST /api/chat/approve` 传 `plan_id: "plan_xxxx"` + `action: "approve"/"reject_plan"` 恢复。  
审批前可用 `GET /api/chat/plans/{plan_id}?session_id=` 取回计划全文。

**人机提问**（`interrupt_type: "ask_human"`）

```json
{
  "type": "interrupt",
  "interrupt_type": "ask_human",
  "question": "请确认目标受体 PDB ID：",
  "options": ["3EML", "4J9C"]
}
```

使用 `POST /api/chat/stream` 发送答案（在同一 `session_id` 下发新消息）恢复。

---

## 6. 通用约定

### 错误响应

FastAPI 标准格式：

```json
{ "detail": "错误原因描述" }
```

| 状态码 | 含义 |
|--------|------|
| `400` | 请求参数非法（格式错误、安全校验失败） |
| `404` | 资源不存在（Artifact 过期、计划不存在等） |
| `422` | Pydantic 验证失败 |
| `500` | 服务端内部错误 |

### 分子格式

- 所有 SMILES 字段均接受标准 SMILES 或 Kekulé 形式；服务端输出统一为 RDKit 标准 canonical SMILES。
- Open Babel 接口的 `input_format` / `output_format` 使用 Open Babel 简写代码（可通过 `GET /api/babel/formats` 查询完整列表）。

### Artifact 生命周期

1. 工具执行时，引擎自动将大体积结果（SDF / PDB / 图像 base64）存入 Redis Artifact Store。
2. SSE `artifact` 事件携带 `artifact_id` 指针，不含原始数据。
3. 前端用 `GET /api/chat/artifacts/{artifact_id}` 按需拉取原始数据。
4. Artifact TTL 默认 300 秒（可通过 `ARTIFACT_TTL_SECONDS` 配置）；过期后返回 `404`。

### CORS

生产环境需设置 `CORS_ALLOWED_ORIGINS` 环境变量（逗号分隔），否则跨域请求将被拒绝。
