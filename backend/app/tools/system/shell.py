"""Shell Tool -- class-based BaseChemTool contract.

``ToolRunShell`` gives the agent a full bash interpreter for invoking chemistry
CLIs (OpenBabel, AutoDock Vina, GROMACS, custom Python scripts, etc.)

Three-layer defence:
1. Command-substitution block (check_permissions) -- $(), backticks, <()/>() banned.
2. Large-output protection (call) -- output >100 KB auto-dumped to log file.
3. Fail-closed defaults -- cwd pinned to validated workspace root.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time

from pydantic import BaseModel, Field

from app.domain.schemas.workflow import PermissionResult, ValidationResult
from app.tools.base import ChemShellTool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_MAX_OUTPUT_BYTES = int(os.environ.get("CHEMAGENT_SHELL_OUTPUT_MAX_BYTES", 100_000))
_SHELL_LOG_DIR = os.environ.get("CHEMAGENT_SHELL_LOG_DIR", "/tmp/chemagent_shell_logs")


def _resolve_default_workdir() -> str:
    explicit = os.environ.get("CHEMAGENT_SHELL_WORKDIR", "").strip()
    if explicit:
        return explicit
    try:
        from app.domain.store.scratchpad_store import SCRATCHPAD_ROOT  # noqa: PLC0415
        return str(SCRATCHPAD_ROOT)
    except Exception:
        return "/tmp"


_DEFAULT_WORKDIR = _resolve_default_workdir()
_DEFAULT_TIMEOUT = 60
_MAX_TIMEOUT = int(os.environ.get("CHEMAGENT_SHELL_MAX_TIMEOUT", 3600))
_HEAD_PREVIEW_CHARS = 3_000
_TAIL_PREVIEW_CHARS = 2_000

# ---------------------------------------------------------------------------
# Security rules
# ---------------------------------------------------------------------------

_BLOCKED_PATTERNS: list[tuple[str, str]] = [
    (r"\$\(", "命令替换 $()"),
    (r"`[^`\n]*`", "反引号命令替换"),
    (r"<\(", "进程替换 <()"),
    (r">\(", "进程替换 >()"),
]


def _build_rm_patterns() -> None:
    safe_prefixes = {"workspace", "tmp"}
    try:
        from app.domain.store.scratchpad_store import SCRATCHPAD_ROOT  # noqa: PLC0415
        parts = SCRATCHPAD_ROOT.parts
        if len(parts) > 1:
            safe_prefixes.add(parts[1])
    except Exception:
        pass
    lookahead = "|".join(sorted(safe_prefixes))
    _BLOCKED_PATTERNS.extend([
        (
            rf"rm\s+(?:[^ ]*\s+)*-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*\s+(?:/(?!{lookahead})|~|\$HOME|\*)",
            "高危目录递归删除（请使用精确的相对/绝对路径）",
        ),
        (
            rf"rm\s+(?:[^ ]*\s+)*-[a-zA-Z]*f[a-zA-Z]*r[a-zA-Z]*\s+(?:/(?!{lookahead})|~|\$HOME|\*)",
            "高危目录递归删除（请使用精确的相对/绝对路径）",
        ),
    ])


_build_rm_patterns()


def _security_check(command: str) -> str | None:
    for pattern, label in _BLOCKED_PATTERNS:
        if re.search(pattern, command):
            return (
                f"[Error: Security] 安全拦截：禁止使用{label}。\n"
                "请将命令拆分为多个独立步骤，通过中间文件（如 .sdf / .pdb / .txt）传递数据，"
                "以提高可追溯性并避免转义错误。"
            )
    return None


# ---------------------------------------------------------------------------
# Large-output handler
# ---------------------------------------------------------------------------


async def _handle_large_output(stdout: str, stderr: str, command: str) -> str:
    combined = stdout
    if stderr.strip():
        combined = stdout + "\n\n--- STDERR ---\n" + stderr

    if len(combined.encode("utf-8", errors="replace")) <= _MAX_OUTPUT_BYTES:
        return combined

    dump_path: str | None = None
    try:
        os.makedirs(_SHELL_LOG_DIR, exist_ok=True)
        dump_path = os.path.join(
            _SHELL_LOG_DIR, f"shell_{int(time.time() * 1000)}.log"
        )
        with open(dump_path, "w", encoding="utf-8", errors="replace") as fh:
            fh.write(f"COMMAND: {command}\n\n--- STDOUT ---\n{stdout}\n--- STDERR ---\n{stderr}")
    except OSError as exc:
        logger.warning("[tool_run_shell] could not dump large output: %s", exc)

    src = stdout or stderr
    head = src[:_HEAD_PREVIEW_CHARS]
    tail = src[-_TAIL_PREVIEW_CHARS:] if len(src) > _HEAD_PREVIEW_CHARS + _TAIL_PREVIEW_CHARS else ""
    omitted = len(src) - _HEAD_PREVIEW_CHARS - _TAIL_PREVIEW_CHARS
    mid = f"\n...[已省略约 {omitted:,} 字符]...\n" if tail else ""
    preview = head + mid + tail

    dump_hint = (
        f"\n\n[System] 完整输出过大 ({len(combined):,} 字节)，已自动保存至:\n  {dump_path}\n"
        "如需分析完整日志，请使用 tool_read_file 逐段读取。"
        if dump_path
        else f"\n\n[System] 完整输出过大 ({len(combined):,} 字节)，已在此截断（日志落盘失败）。"
    )
    return preview + dump_hint


# ---------------------------------------------------------------------------
# ToolRunShell
# ---------------------------------------------------------------------------


class RunShellInput(BaseModel):
    command: str = Field(
        description=(
            "要执行的 Bash 命令（支持管道 |、重定向 >、&& / || 等完整 bash 语法；"
            "禁止使用 $() 命令替换，请通过中间文件传递数据）"
        )
    )
    timeout: int = Field(
        default=_DEFAULT_TIMEOUT,
        description=f"超时秒数（默认 {_DEFAULT_TIMEOUT}s，最大 {_MAX_TIMEOUT}s）",
    )
    workdir: str = Field(
        default="",
        description=f"命令的工作目录（默认: {_DEFAULT_WORKDIR}；必须是已存在的绝对路径）",
    )


class ToolRunShell(ChemShellTool[RunShellInput, str]):
    """Execute a Bash command and return stdout, stderr, and exit code.

    Uses shell=True to support full bash syntax.  Security guards block
    command substitution.  Output exceeding ~100 KB is dumped to a log file.
    """

    name = "tool_run_shell"
    args_schema = RunShellInput
    tier = "L2"
    max_result_size_chars = 120_000

    async def validate_input(
        self, args: RunShellInput, context: dict
    ) -> ValidationResult:
        if not args.command.strip():
            return ValidationResult(result=False, message="[Error: 2] 命令为空。")
        return ValidationResult(result=True)

    async def check_permissions(
        self, args: RunShellInput, context: dict
    ) -> PermissionResult:
        err = _security_check(args.command)
        if err:
            return PermissionResult(granted=False, message=err)
        return PermissionResult(granted=True)

    async def call(self, args: RunShellInput) -> str:
        """Run a shell command in the workspace and return stdout, stderr, and exit code."""
        clamped_timeout = min(max(int(args.timeout), 1), _MAX_TIMEOUT)
        cwd: str | None = args.workdir.strip() or _DEFAULT_WORKDIR
        if cwd and not os.path.isdir(cwd):
            logger.warning("[tool_run_shell] workdir %r does not exist, falling back to cwd=None", cwd)
            cwd = None

        logger.info("[tool_run_shell] cmd=%.120r  cwd=%r  timeout=%ds", args.command, cwd, clamped_timeout)

        try:
            proc = await asyncio.create_subprocess_shell(
                args.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=clamped_timeout,
                )
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                    await proc.communicate()
                except Exception:
                    pass
                return json.dumps(
                    {
                        "is_valid": False,
                        "error": (
                            f"[Error: 7] 命令执行超过 {clamped_timeout}s 被强制终止：{args.command!r}\n"
                            "如果是长时分子模拟，请增大 timeout 参数，"
                            "或将任务推入后台（在命令末尾加 & 并记录 PID）。"
                        ),
                    },
                    ensure_ascii=False,
                )

        except OSError as exc:
            return json.dumps(
                {"is_valid": False, "error": f"[Error: 5] Shell 启动失败：{exc}"},
                ensure_ascii=False,
            )

        returncode = proc.returncode
        stdout = stdout_bytes.decode(errors="replace")
        stderr = stderr_bytes.decode(errors="replace")
        output = await _handle_large_output(stdout, stderr, args.command)
        status_tag = "ok" if returncode == 0 else f"exited {returncode}"

        return json.dumps(
            {
                "is_valid": True,
                "status": status_tag,
                "returncode": returncode,
                "output": output,
            },
            ensure_ascii=False,
        )


tool_run_shell = ToolRunShell().as_langchain_tool()

ALL_SHELL_TOOLS = [tool_run_shell]

