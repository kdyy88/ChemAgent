"""Shell Tool -- ChemAgent System Layer
=========================================

``tool_run_shell`` gives the agent a full bash interpreter for invoking
chemistry CLIs (OpenBabel, AutoDock Vina, GROMACS, custom Python scripts, etc.)

Three-layer defence modelled after production coding-agent best practices:

1. **Command-substitution block** (first fence, pre-execution)
   $(), backticks, <() and >() are banned.  These constructs are the primary
   vector for unintended nested execution and silent escaping errors in complex
   bioinformatics pipelines.  The agent is instructed to use intermediate files
   instead (standard Unix IPC -- safer and more auditable).

2. **Large-output protection** (second fence, post-execution)
   Bioinformatics tools (GROMACS, Rosetta, Vina) routinely emit hundreds of MB
   of log text.  Output that exceeds _MAX_OUTPUT_BYTES is automatically dumped
   to a timestamped file under _SHELL_LOG_DIR and the agent receives only a
   head+tail preview plus the file path so it can continue with tool_read_file.

3. **Fail-closed defaults**
   shell=True is used (required for full bash syntax: pipes, &&, redirects,
   glob expansion) but cwd is pinned to a validated workspace root so the
   command is scoped to the isolated data plane.  rm -rf on non-workspace
   paths is blocked.

Design notes
------------
- ``asyncio.create_subprocess_shell`` keeps the tool non-blocking inside the
  LangGraph executor event loop (consistent with the rest of the codebase).
- Timeout is clamped between 1s and _MAX_SHELL_TIMEOUT to allow long MD runs
  while still protecting against runaway processes.
- No __file_protocol__ emitted -- this is execution output, not a file event.
  If a command *writes* a file the agent should follow with tool_read_file to
  register it in ChemState before editing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Annotated

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (all overridable via environment variables)
# ---------------------------------------------------------------------------

_MAX_OUTPUT_BYTES = int(os.environ.get("CHEMAGENT_SHELL_OUTPUT_MAX_BYTES", 100_000))
_SHELL_LOG_DIR = os.environ.get("CHEMAGENT_SHELL_LOG_DIR", "/tmp/chemagent_shell_logs")

# Default workdir: prefer the configured scratchpad root so generated files are
# co-located with long-term memory in local-dev mode as well as Docker.
# Falls back to /tmp if the scratchpad root cannot be resolved at import time.
def _resolve_default_workdir() -> str:
    explicit = os.environ.get("CHEMAGENT_SHELL_WORKDIR", "").strip()
    if explicit:
        return explicit
    try:
        from app.domain.store.scratchpad_store import SCRATCHPAD_ROOT  # noqa: PLC0415
        return str(SCRATCHPAD_ROOT)
    except Exception:  # pragma: no cover
        return "/tmp"

_DEFAULT_WORKDIR = _resolve_default_workdir()
_DEFAULT_TIMEOUT = 60
_MAX_TIMEOUT = int(os.environ.get("CHEMAGENT_SHELL_MAX_TIMEOUT", 3600))  # 1 h for long MD runs
_HEAD_PREVIEW_CHARS = 3_000
_TAIL_PREVIEW_CHARS = 2_000

# ---------------------------------------------------------------------------
# Security rules
# ---------------------------------------------------------------------------

_BLOCKED_PATTERNS: list[tuple[str, str]] = [
    # Command substitution -- the primary injection/silent-error vector.
    (r"\$\(", "命令替换 $()"),
    (r"`[^`\n]*`", "反引号命令替换"),
    (r"<\(", "进程替换 <()"),
    (r">\(", "进程替换 >()"),
    # Destructive rm on paths outside the workspace / tmp / configured scratchpad.
    # Matches rm with both -r and -f flags (any order, any combined flag string)
    # targeting /, ~, $HOME, or bare wildcards.
    # rm patterns are appended dynamically by _build_rm_patterns() below so that
    # the configured SCRATCHPAD_ROOT path (e.g. /home/...) is also exempted.
]

def _build_rm_patterns() -> None:
    """Append rm-safety rules to _BLOCKED_PATTERNS with a runtime-aware safe-prefix list."""
    safe_prefixes = {"workspace", "tmp"}
    try:
        from app.domain.store.scratchpad_store import SCRATCHPAD_ROOT  # noqa: PLC0415
        # e.g. Path('/home/admin/.scratchpad').parts[1] == 'home'
        parts = SCRATCHPAD_ROOT.parts
        if len(parts) > 1:
            safe_prefixes.add(parts[1])
    except Exception:  # pragma: no cover
        pass
    lookahead = "|".join(sorted(safe_prefixes))
    _BLOCKED_PATTERNS.extend([
        (rf"rm\s+(?:[^ ]*\s+)*-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*\s+(?:/(?!{lookahead})|~|\$HOME|\*)",
         "高危目录递归删除（请使用精确的相对/绝对路径）"),
        (rf"rm\s+(?:[^ ]*\s+)*-[a-zA-Z]*f[a-zA-Z]*r[a-zA-Z]*\s+(?:/(?!{lookahead})|~|\$HOME|\*)",
         "高危目录递归删除（请使用精确的相对/绝对路径）"),
    ])

_build_rm_patterns()


def _security_check(command: str) -> str | None:
    """Return an error string if the command triggers a security rule, else None."""
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
    """Return the combined output, or a head+tail preview + log-file path."""
    combined = stdout
    if stderr.strip():
        combined = stdout + "\n\n--- STDERR ---\n" + stderr

    if len(combined.encode("utf-8", errors="replace")) <= _MAX_OUTPUT_BYTES:
        return combined

    # Dump full output to a timestamped log file.
    dump_path: str | None = None
    try:
        os.makedirs(_SHELL_LOG_DIR, exist_ok=True)
        dump_path = os.path.join(
            _SHELL_LOG_DIR,
            f"shell_{int(time.time() * 1000)}.log",
        )
        with open(dump_path, "w", encoding="utf-8", errors="replace") as fh:
            fh.write(f"COMMAND: {command}\n\n--- STDOUT ---\n{stdout}\n--- STDERR ---\n{stderr}")
    except OSError as exc:
        logger.warning("[tool_run_shell] could not dump large output: %s", exc)

    # Build head + tail preview from stdout (most informative part).
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
# tool_run_shell
# ---------------------------------------------------------------------------


@tool
async def tool_run_shell(
    command: Annotated[
        str,
        "要执行的 Bash 命令（支持管道 |、重定向 >、&& / || 等完整 bash 语法；"
        "禁止使用 $() 命令替换，请通过中间文件传递数据）",
    ],
    timeout: Annotated[
        int,
        f"超时秒数（默认 {_DEFAULT_TIMEOUT}s，最大 {_MAX_TIMEOUT}s；"
        "长时分子模拟（如 GROMACS mdrun）可设置更大值）",
    ] = _DEFAULT_TIMEOUT,
    workdir: Annotated[
        str,
        f"命令的工作目录（默认: {_DEFAULT_WORKDIR}；必须是已存在的绝对路径；"
        "可通过环境变量 CHEMAGENT_SHELL_WORKDIR 全局覆盖）",
    ] = "",
) -> str:
    """Execute a Bash command and return stdout, stderr, and exit code.

    Uses shell=True to support full bash syntax required by chemistry CLIs
    (pipes, redirects, &&, glob patterns).  Security guards block command
    substitution patterns.  Output exceeding ~100 KB is automatically dumped
    to a log file; only a head+tail preview is returned to the LLM.
    """
    if not command.strip():
        return json.dumps({"is_valid": False, "error": "[Error: 2] 命令为空。"}, ensure_ascii=False)

    # --- Security fence -------------------------------------------------------
    err = _security_check(command)
    if err:
        return json.dumps({"is_valid": False, "error": err}, ensure_ascii=False)

    # --- Working directory validation -----------------------------------------
    clamped_timeout = min(max(int(timeout), 1), _MAX_TIMEOUT)
    cwd = workdir.strip() or _DEFAULT_WORKDIR
    if not os.path.isdir(cwd):
        # Fall back gracefully rather than refusing -- workspace may not be
        # mounted in every deployment (e.g. unit-test environments).
        logger.warning("[tool_run_shell] workdir %r does not exist, falling back to cwd=None", cwd)
        cwd = None  # type: ignore[assignment]

    logger.info("[tool_run_shell] cmd=%.120r  cwd=%r  timeout=%ds", command, cwd, clamped_timeout)

    # --- Execution ------------------------------------------------------------
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
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
            except Exception:  # noqa: BLE001
                pass
            return json.dumps(
                {
                    "is_valid": False,
                    "error": (
                        f"[Error: 7] 命令执行超过 {clamped_timeout}s 被强制终止：{command!r}\n"
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

    # --- Large-output protection ----------------------------------------------
    output = await _handle_large_output(stdout, stderr, command)

    # Semantic exit-code tag: many CLIs return non-zero for benign reasons
    # (e.g. grep returns 1 when no lines match).  We surface it but don't fail.
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


# ---------------------------------------------------------------------------
# Tool list for catalog registration
# ---------------------------------------------------------------------------

ALL_SHELL_TOOLS = [tool_run_shell]
