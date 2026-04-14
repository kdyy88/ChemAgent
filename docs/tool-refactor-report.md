# ChemAgent Tool 重构报告

**完成日期：** 2026-04-14  
**重构范围：** `backend/app/tools/` 全量（31 个工具）  
**关联 PR 范围：** Steps 1–10（workflow → base → registry → rdkit → executor → babel → lookup/skills → system → control/sub-agent → catalog/graph/cleanup）

---

## 一、重构做了什么

原始代码使用 `@chem_tool` / `@tool` 装饰器将工具实现为顶层函数。此次重构将全部 31 个工具迁移至 `BaseChemTool` 抽象基类层级，设计原型来自 Claude Code 的 `Tool.ts` / `buildTool()` 模式。

### 1.1 新类层级

```
BaseChemTool[T_Input, T_Output]           ← app.tools.base
│
├── ChemComputeTool    CPU 密集型（RDKit × 8，Babel × 6，fetch_chemistry_api × 1）
│     策略：同步 call() → 子进程隔离；异步 call() → asyncio.wait_for
│
├── ChemLookupTool     网络 I/O（PubChem × 1，WebSearch × 1）
│     策略：asyncio.wait_for 超时
│
├── ChemStateTool      纯状态写入（state × 4，screen × 1，invoke_skill × 1，read_skill_ref × 1）
│     策略：直接执行，无超时
│   │
│   ├── ChemIOTool     文件系统（read_file × 1，write_file × 1，edit_file × 1）
│   └── ChemShellTool  Shell 执行（run_shell × 1）
│
└── ChemControlTool    HITL / 编排（ask_human × 1，update_task_status × 1，run_sub_agent × 1）
      策略：直接执行，异常原样抛出（保留 LangGraph interrupt 信号）
```

### 1.2 每个工具强制声明的字段

| 字段 | 类型 | 作用 |
|---|---|---|
| `name` | `str` | 工具注册名 |
| `args_schema` | `type[BaseModel]` | Pydantic 入参模型（强类型） |
| `tier` | `"L1" \| "L2" \| None` | 执行等级，驱动 HITL 策略 |
| `max_result_size_chars` | `int` | 超出时自动截断，防止上下文爆炸 |

### 1.3 统一执行管道（`as_langchain_tool()`）

每次工具调用都经过固定的 7 步管道：

```
kwargs → T_Input(Pydantic) → validate_input() → check_permissions()
       → call() [mid-class 策略] → _translate_protocol() → _truncate_if_needed()
```

---

## 二、带来了哪些好处

### 2.1 安全分层：validate_input vs check_permissions

- **validate_input** 处理参数错误（格式、范围、路径穿越）→ 返回模型可重试错误，**不经过 UI**。
- **check_permissions** 处理鉴权（危险命令、SSRF 白名单）→ 触发 HITL 审批门，**用户可见**。

以前两类检查散落在函数体内，界限不清晰，偶尔会把参数错误误导至 HITL，造成不必要的人工干预。现在强制分离。

**示例：`ToolRunShell`**
```python
async def validate_input(self, args, context) -> ValidationResult:
    if not args.command.strip():
        return ValidationResult(result=False, message="[Error: 2] 命令为空。")
    return ValidationResult(result=True)

async def check_permissions(self, args, context) -> PermissionResult:
    err = _security_check(args.command)   # 危险命令检测
    if err:
        return PermissionResult(granted=False, message=err)
    return PermissionResult(granted=True)
```

### 2.2 max_result_size_chars：强制输出预算声明

每个工具现在**必须**声明输出上限，执行管道自动截断。旧代码没有这个机制，某些工具（如 `tool_run_shell` 执行 GROMACS 日志）可以将数十 MB 内容推入模型上下文而不警告。

### 2.3 _current_tool_config：配置无需透传

旧代码中，需要 `RunnableConfig` 的工具（如 `tool_invoke_skill`、`tool_edit_file`）必须在参数列表中加 `config: RunnableConfig = None`，LangChain 会将其视为工具 schema 的一部分并传给 LLM，产生噪音。

重构后，所有 mid-class `_afunc` 在调用 `call()` 之前设置：
```python
_current_tool_config.set(config)   # contextvars.ContextVar
```
工具在 `call()` 内通过 `_current_tool_config.get()` 读取，**LLM 永远看不到 config 参数**。

### 2.4 JIT prompt()：工具可以向 System Prompt 贡献内容

`BaseChemTool.prompt(context)` 默认返回空字符串。技能工具可覆盖此方法，在子代理分配时异步加载参考文档：
```python
async def prompt(self, context: dict) -> str:
    # 按需读取 .md 技能文件
    return load_skill_reference("rdkit")
```
`compile_tool_prompts(tools, context)` 聚合所有工具的贡献，注入子代理 System Prompt。这使得工具级文档与 LLM 提示**共同演进**，而不是维护两份分散的文档。

### 2.5 诊断键 SSOT（executor.py）

`chem_diagnostic_keys` 元数据字段取代了 `executor.py` 中的硬编码 `DIAGNOSTIC_SCHEMA` 查找表。工具现在自己声明哪些返回字段应自动写入 `molecule_tree` 诊断——新增工具无需修改 executor。

### 2.6 注册守卫（registry.py）

启动时调用一次：
```python
assert_explore_tools_are_read_only()
```
防止将可变工具（如 `tool_write_file`）意外加入 explore 白名单。以前此类错误只在运行时暴露。

### 2.7 Pydantic 入参模型：输入文档化 + 验证一体

旧代码：
```python
def tool_convert_format(
    input_file: Annotated[str, "输入文件路径"],
    output_format: Annotated[str, "输出格式"],
) -> str:
```
新代码：
```python
class ConvertFormatInput(BaseModel):
    input_file: str = Field(description="输入文件路径")
    output_format: str = Field(description="输出格式")
    # validate_input() 中可引用 args.output_format 做枚举检查
```
入参模型是独立的、可测试的单元，不与执行逻辑耦合。

### 2.8 子进程注册表（_SYNC_CALLABLE_REGISTRY）

`ChemComputeTool` 的同步 `call()` 方法被注册到 `_SYNC_CALLABLE_REGISTRY["module:ClassName.call"] = self.call`，与 `decorators.py` 共享同一个注册表，保持子进程 worker 反序列化路径的向后兼容。

---

## 三、潜在风险

### 3.1 DeprecationWarning 会在生产日志中出现

`@chem_tool` 装饰器现在在被调用时发出 `DeprecationWarning`。目前代码库中没有剩余的 `@chem_tool` 使用（`.bak` 文件除外），但如果有外部插件或测试 fixture 引用了它，日志会出现警告。

**缓解：** 已添加 `stacklevel=3`，警告会正确指向调用方。外部插件应尽快迁移。

### 3.2 base.py 与 decorators.py 共享私有 API

`base.py` 从 `decorators.py` 导入 `_SYNC_CALLABLE_REGISTRY`、`_run_sync_with_timeout` 等私有符号（下划线前缀）。这是一个**内部耦合点**：如果 `decorators.py` 重构其子进程机制，`base.py` 也需要同步修改。

**缓解：** 这两个文件的职责是互补的（`decorators.py` = 执行基础设施，`base.py` = 类抽象层）。未来应将共享的子进程逻辑提取到 `app/tools/subprocess_runner.py`，让两者都从这里导入。

### 3.3 tool_run_sub_agent 的 call() 方法体很长

由于原始 `@tool` 函数体是通过 re-indent 整体迁入 `call()` 方法的，单个方法约 450 行，包含了模式解析、委派构造、子图执行、中断处理、结果序列化等多个关注点。

**缓解：** 功能上完全等价，逻辑没有变化，只是组织形式。后续可以将各阶段拆分为私有方法（`_resolve_mode`、`_execute_subgraph`、`_serialize_result`），但这属于代码整洁改进，不是正确性问题。

### 3.4 contextvars 在 sync-then-async 混用场景下有陷阱

`_current_tool_config` 使用 Python `contextvars.ContextVar`，在 `asyncio` 中每个 Task 继承父 Task 的 context。但如果工具在**线程池**（如 `asyncio.to_thread`）中调用，子线程会看到父线程的 ContextVar 值（Python 3.7+ 的 `copy_context()` 语义）。目前所有工具在主事件循环中执行，不存在问题，但未来如果引入 `concurrent.futures.ProcessPoolExecutor`，需要显式传递 context。

### 3.5 `max_result_size_chars` 的截断是字符级的

当前 `_truncate_if_needed()` 按字符数截断，对于 JSON 输出可能截断在一个不完整的 JSON 结构中间，导致下游解析失败。

**缓解：** 对于结构化 JSON 输出的工具，建议在 `call()` 内先做业务级裁剪（取 top-N 结果），再序列化，而不是依赖末尾截断。

---

## 四、新工具接入指南

### 4.1 选择正确的 mid-class

| 场景 | 选择 |
|---|---|
| RDKit / Babel / 任何 C 扩展同步运算 | `ChemComputeTool` |
| PubChem API / 外部 HTTP 调用（async） | `ChemLookupTool` |
| 向 ChemState 写入协议 payload | `ChemStateTool` |
| 读写本地文件系统 | `ChemIOTool` |
| 执行 Bash / CLI 工具 | `ChemShellTool` |
| HITL / 子代理委派 / 任务编排 | `ChemControlTool` |

### 4.2 最小实现模板

```python
# backend/app/tools/your_module/your_tool.py
from __future__ import annotations
from pydantic import BaseModel, Field
from app.domain.schemas.workflow import ValidationResult
from app.tools.base import ChemComputeTool   # 换成合适的 mid-class


class YourToolInput(BaseModel):
    smiles: str = Field(description="...")
    some_param: float = Field(default=1.0, description="...")


class ToolYourTool(ChemComputeTool[YourToolInput, str]):
    """一句话描述，作为 LLM 看到的工具描述（来自 call() docstring）。"""

    name = "tool_your_tool"
    args_schema = YourToolInput
    tier = "L1"                      # L1=无需审批, L2=危险操作需审批
    max_result_size_chars = 4_000    # 必填：输出预算
    read_only = True                 # 无副作用则设 True
    is_concurrency_safe = True       # 可并行则设 True
    diagnostic_keys = ["your_key"]  # 自动写入 molecule_tree.diagnostics 的字段

    async def validate_input(self, args: YourToolInput, context: dict) -> ValidationResult:
        # 仅做参数合法性检查，不做鉴权
        if not args.smiles.strip():
            return ValidationResult(result=False, message="smiles 不能为空。")
        return ValidationResult(result=True)

    # check_permissions() 只在有鉴权需求时覆盖（默认返回 granted=True）

    def call(self, args: YourToolInput) -> str:
        """Compute something from SMILES and return JSON.

        这里是真正的执行逻辑。同步 def = 子进程隔离；async def = asyncio.wait_for。
        """
        import json
        result = {"your_key": 42.0}   # 替换为实际计算
        return json.dumps(result, ensure_ascii=False)


# 模块级别 binding（工具名保持向后兼容）
tool_your_tool = ToolYourTool().as_langchain_tool()
```

### 4.3 注册到 catalog

在 `backend/app/tools/catalog.py` 中添加：

```python
from app.tools.your_module.your_tool import tool_your_tool

ALL_CHEM_TOOLS = [
    ...
    tool_your_tool,   # 加到合适位置
]
```

### 4.4 可选：声明诊断键（自动 patch molecule_tree）

如果工具返回 JSON 中包含分子属性（mw、logp、tpsa 等），在类中声明：

```python
diagnostic_keys = ["mw", "logp", "tpsa"]
```

executor 会自动将这些字段写入 `molecule_tree[artifact_id].diagnostics`，无需手动调用 `tool_patch_diagnostics`。

### 4.5 可选：JIT System Prompt 贡献

如果工具需要向子代理注入使用说明（如复杂参数约定、参考数据格式），覆盖 `prompt()`：

```python
async def prompt(self, context: dict) -> str:
    return """
## tool_your_tool 使用注意
- some_param 取值范围 0.1–10.0
- 输出字段 your_key 的单位是 kcal/mol
"""
```

`compile_tool_prompts()` 会在子代理分配时收集所有工具的贡献，拼接到 System Prompt 末尾。

### 4.6 validate_input 与 check_permissions 的分工

```
validate_input  →  参数格式、范围、业务规则（路径穿越检查也在这里）
                   失败 → {"is_retryable": true}，模型自动重试
                   用户看不到任何提示

check_permissions →  危险操作审批（命令注入检测、SSRF 白名单、文件覆盖确认）
                     失败 → HITL 门，用户会看到 reason 并被要求批准
                     仅在 validate_input 通过后调用
```

### 4.7 完整验证

```bash
cd backend
# 新工具 import 正常
uv run python -c "from app.tools.your_module.your_tool import tool_your_tool; print(tool_your_tool.name)"

# catalog 总数 +1
uv run python -c "from app.tools.catalog import ALL_CHEM_TOOLS; print(len(ALL_CHEM_TOOLS))"

# explore 白名单完整性（有 read_only=True 的工具才能加入 explore 模式）
uv run python -c "from app.tools.registry import assert_explore_tools_are_read_only; assert_explore_tools_are_read_only(); print('OK')"
```

---

## 五、文件索引

| 文件 | 作用 |
|---|---|
| `app/tools/base.py` | `BaseChemTool` ABC + 6 个 mid-class + `build_chem_tool()` 工厂 |
| `app/tools/metadata.py` | 所有元数据 key 常量 + `DIAGNOSTIC_SCHEMA` |
| `app/tools/registry.py` | 工具查找、模式过滤、JIT prompt 聚合、startup 守卫 |
| `app/tools/catalog.py` | `ALL_CHEM_TOOLS` 全量列表 |
| `app/tools/decorators.py` | 遗留 `@chem_tool` 装饰器（已标记 deprecated）+ 子进程基础设施 |
| `app/domain/schemas/workflow.py` | `ValidationResult`、`PermissionResult` 数据类 |
| `app/agents/nodes/executor.py` | 从 `chem_diagnostic_keys` 元数据读取 SSOT 诊断键 |
| `app/agents/sub_agents/graph.py` | 通过 `compile_tool_prompts()` 注入工具 JIT prompt |
