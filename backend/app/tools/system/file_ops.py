"""File Operation Tools -- ChemAgent System Layer
=================================================

Three tools that give the LLM controlled access to the host file system:

  tool_read_file   -- read a file; emits a FileRead protocol event so
                     the executor registers mtime into ChemState
  tool_write_file  -- create or overwrite a file entirely (with read-guard
                     for existing files and LF normalisation)
  tool_edit_file   -- search-and-replace edit with anti-hallucination guards

Shell execution has been moved to ``app/tools/system/shell.py``
(``tool_run_shell``) which adds full bash support, command-substitution
blocking, and large-output auto-dump.

State model
-----------
``tool_read_file`` and ``tool_write_file`` return a JSON payload that carries
a ``__file_protocol__: "FileRead"`` marker.  The executor intercepts this and
writes ``{path -> {mtime}}`` into ``ChemState.read_file_state`` via the
``merge_file_read_state`` reducer -- so the checkpointer can persist and
time-travel the file-access window.

``tool_edit_file`` and ``tool_write_file`` receive the *current*
``read_file_state`` injected into ``config["configurable"]["read_file_state"]``
by the executor just before the call.  They never touch any module-level dict.

Security model
--------------
- Path traversal guard: ``os.path.realpath`` resolves ``..`` and symlinks;
  paths must start with one of ``_ALLOWED_PATH_PREFIXES``.
- Read-before-edit/write guard: both mutating tools refuse if the path is
  absent from the injected ``read_file_state`` or if mtime has advanced.
- Output truncation: reads are capped so the LLM context budget is not
  accidentally exhausted.

No module-level mutable state: this module is stateless; all session context
flows through ChemState and the LangGraph checkpointer.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

_DEFAULT_ALLOWED_PREFIXES: tuple[str, ...] = (
    "/home/",
    "/workspace/",
    "/tmp/",
    "/app/",
)


def _allowed_prefixes() -> tuple[str, ...]:
    extra = os.environ.get("CHEMAGENT_ALLOWED_FILE_PREFIXES", "")
    additional = tuple(p.strip() for p in extra.split(":") if p.strip())
    return _DEFAULT_ALLOWED_PREFIXES + additional


_MAX_READ_BYTES = int(os.environ.get("CHEMAGENT_FILE_READ_MAX_BYTES", 80_000))

# ---------------------------------------------------------------------------
# Path validation helper
# ---------------------------------------------------------------------------


def _resolve_and_validate(raw_path: str) -> tuple[str, str | None]:
    """Return (resolved_absolute_path, error_string_or_None)."""
    try:
        resolved = os.path.realpath(os.path.abspath(os.path.expanduser(raw_path)))
    except Exception as exc:
        return raw_path, f"[Error: 3] 路径解析失败：{exc}"

    allowed = _allowed_prefixes()
    if not any(resolved.startswith(p) for p in allowed):
        return resolved, (
            f"[Error: 3] 路径访问被拒绝：{resolved!r} 不在允许的目录范围内。\n"
            f"允许前缀: {', '.join(allowed)}"
        )
    return resolved, None


# ---------------------------------------------------------------------------
# Read-guard helper — reads from injected state, not a global dict
# ---------------------------------------------------------------------------


def _check_read_guard(
    resolved_path: str,
    current_mtime: float,
    read_file_state: dict,
) -> str | None:
    """Return an error string if the read guard fails, else None.

    ``read_file_state`` is the value injected by the executor from ChemState.
    """
    entry = (read_file_state or {}).get(resolved_path)
    if entry is None:
        return (
            "[Error: 6] 安全拦截：编辑前必须先调用 tool_read_file 读取该文件。"
            f"\n文件路径: {resolved_path}"
        )
    last_mtime = float(entry.get("mtime") or 0)
    if current_mtime > last_mtime + 0.002:
        return (
            "[Error: 6] 安全拦截：文件自上次读取后已被外部修改（mtime 变化）。"
            f"\n请重新调用 tool_read_file 获取最新内容后再编辑。\n文件路径: {resolved_path}"
        )
    return None


# ---------------------------------------------------------------------------
# tool_read_file
# ---------------------------------------------------------------------------


@tool
def tool_read_file(
    path: Annotated[str, "要读取的文件绝对路径"],
    start_line: Annotated[int, "从第几行开始读取（1-indexed，0 表示从头）"] = 0,
    end_line: Annotated[int, "读取到第几行（含，0 表示读到结尾）"] = 0,
) -> str:
    """Read a file and register it so tool_edit_file can proceed safely.

    Emits a ``__file_protocol__: "FileRead"`` marker that the executor picks
    up to write the file's mtime into ``ChemState.read_file_state``.
    """
    resolved, err = _resolve_and_validate(path)
    if err:
        return json.dumps({"is_valid": False, "error": err}, ensure_ascii=False)

    if not os.path.exists(resolved):
        return json.dumps(
            {"is_valid": False, "error": f"[Error: 4] 文件不存在：{resolved}"},
            ensure_ascii=False,
        )
    if not os.path.isfile(resolved):
        return json.dumps(
            {"is_valid": False, "error": f"[Error: 4] 路径不是普通文件：{resolved}"},
            ensure_ascii=False,
        )

    try:
        mtime = os.path.getmtime(resolved)
        with open(resolved, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError as exc:
        return json.dumps({"is_valid": False, "error": f"[Error: 5] 读取失败：{exc}"}, ensure_ascii=False)

    total_lines = len(lines)
    s = max(0, (start_line - 1) if start_line > 0 else 0)
    e = end_line if end_line > 0 else total_lines
    content = "".join(lines[s:e])

    truncated = False
    if len(content.encode()) > _MAX_READ_BYTES:
        content = content.encode()[:_MAX_READ_BYTES].decode(errors="replace")
        truncated = True

    return json.dumps(
        {
            # ── Protocol marker — executor writes mtime into ChemState ──────
            "__file_protocol__": "FileRead",
            "path": resolved,
            "mtime": mtime,
            # ── Content fields returned to the LLM ─────────────────────────
            "is_valid": True,
            "total_lines": total_lines,
            "lines_returned": f"{s + 1}-{min(e, total_lines)}",
            "truncated": truncated,
            "content": content,
        },
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# tool_write_file
# ---------------------------------------------------------------------------


@tool
def tool_write_file(
    path: Annotated[str, "要写入的文件绝对路径（不存在则创建，已存在则覆盖）"],
    content: Annotated[str, "要写入的完整文件内容"],
    config: Annotated[RunnableConfig | None, "LangGraph session config — executor injects read_file_state here"] = None,
) -> str:
    """Create a new file or completely overwrite an existing one.

    Guards (same philosophy as tool_edit_file):
    - If the target file **already exists**, requires a prior tool_read_file call
      (mtime check via ChemState.read_file_state) to prevent blindly clobbering
      edits the scientist made in their IDE while the agent wasn't looking.
    - New files (path does not yet exist) are created freely — parent dirs are
      created with ``os.makedirs(exist_ok=True)``.

    LF normalisation:
    - All ``\\r\\n`` sequences are rewritten to ``\\n`` before writing, and the
      file is opened with ``newline='\\n'`` to prevent Python's universal-newline
      layer from re-introducing ``\\r\\n`` on Windows hosts.
    - This keeps shell scripts and Python source files cross-platform safe.

    Also emits ``__file_protocol__: "FileRead"`` so the executor registers the
    freshly-written file's mtime — allowing chained tool_edit_file calls without
    requiring a separate read step.
    """
    resolved, err = _resolve_and_validate(path)
    if err:
        return json.dumps({"is_valid": False, "error": err}, ensure_ascii=False)

    # Read-guard: if the file already exists, the agent must have seen it first.
    if os.path.exists(resolved):
        if not os.path.isfile(resolved):
            return json.dumps(
                {"is_valid": False, "error": f"[Error: 4] 路径已存在但不是普通文件（可能是目录）：{resolved}"},
                ensure_ascii=False,
            )
        try:
            current_mtime = os.path.getmtime(resolved)
        except OSError as exc:
            return json.dumps({"is_valid": False, "error": f"[Error: 5] 无法获取文件状态：{exc}"}, ensure_ascii=False)

        injected_state: dict = (
            ((config or {}).get("configurable") or {}).get("read_file_state") or {}
        )
        guard_err = _check_read_guard(resolved, current_mtime, injected_state)
        if guard_err:
            # Reframe the message for a write context.
            return json.dumps(
                {
                    "is_valid": False,
                    "error": guard_err.replace(
                        "编辑前必须先调用 tool_read_file",
                        "覆盖写入前必须先调用 tool_read_file",
                    ).replace(
                        "文件已被外部修改（mtime 变化）。\n请重新调用 tool_read_file 获取最新内容后再编辑",
                        "文件已被外部修改（mtime 变化）。\n请重新调用 tool_read_file 获取最新内容后再覆盖写入",
                    ),
                },
                ensure_ascii=False,
            )

    # LF normalisation — rewrite \r\n → \n, open with newline='\n' so Python's
    # universal-newline layer does not re-introduce \r\n on Windows hosts.
    content_lf = content.replace("\r\n", "\n")

    try:
        parent_dir = os.path.dirname(resolved)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        with open(resolved, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content_lf)
        mtime = os.path.getmtime(resolved)
    except OSError as exc:
        return json.dumps({"is_valid": False, "error": f"[Error: 5] 写入失败：{exc}"}, ensure_ascii=False)

    lines_written = content_lf.count("\n") + (1 if content_lf and not content_lf.endswith("\n") else 0)
    return json.dumps(
        {
            "__file_protocol__": "FileRead",
            "path": resolved,
            "mtime": mtime,
            "is_valid": True,
            "lines_written": lines_written,
            "chars_written": len(content_lf),
        },
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# tool_edit_file
# ---------------------------------------------------------------------------


@tool
def tool_edit_file(
    path: Annotated[str, "要编辑的文件绝对路径"],
    old_string: Annotated[str, "要被替换的精确文本片段（必须与文件内容完全一致，包含缩进和换行）"],
    new_string: Annotated[str, "替换后的新文本片段"],
    replace_all: Annotated[bool, "True = 替换所有匹配；False（默认）= old_string 必须全文唯一，否则报错"] = False,
    config: Annotated[RunnableConfig | None, "LangGraph session config — executor injects read_file_state here"] = None,
) -> str:
    """Edit a file using exact search-and-replace.

    Anti-hallucination guards:
    - Refuses unless tool_read_file was called first (mtime from ChemState).
    - Refuses if old_string appears 0 times (hallucinated content).
    - Refuses if old_string appears >1 time and replace_all=False (ambiguous).

    After a successful write emits ``__file_protocol__: "FileRead"`` so the
    executor refreshes the mtime in ChemState — allowing chained edits.
    """
    resolved, err = _resolve_and_validate(path)
    if err:
        return json.dumps({"is_valid": False, "error": err}, ensure_ascii=False)

    if not os.path.exists(resolved):
        return json.dumps(
            {"is_valid": False, "error": f"[Error: 4] 文件不存在：{resolved}。如需创建请用 tool_write_file。"},
            ensure_ascii=False,
        )

    try:
        current_mtime = os.path.getmtime(resolved)
    except OSError as exc:
        return json.dumps({"is_valid": False, "error": f"[Error: 5] 无法获取文件状态：{exc}"}, ensure_ascii=False)

    # Read the guard state injected by the executor from ChemState.
    injected_state: dict = (
        ((config or {}).get("configurable") or {}).get("read_file_state") or {}
    )
    guard_err = _check_read_guard(resolved, current_mtime, injected_state)
    if guard_err:
        return json.dumps({"is_valid": False, "error": guard_err}, ensure_ascii=False)

    try:
        with open(resolved, encoding="utf-8") as fh:
            content = fh.read()
    except OSError as exc:
        return json.dumps({"is_valid": False, "error": f"[Error: 5] 读取失败：{exc}"}, ensure_ascii=False)

    if old_string == new_string:
        return json.dumps(
            {"is_valid": False, "error": "[Error: 1] old_string 与 new_string 完全相同，无需修改。"},
            ensure_ascii=False,
        )

    occurrences = content.count(old_string)
    if occurrences == 0:
        excerpt = old_string[:200] + ("…" if len(old_string) > 200 else "")
        return json.dumps(
            {
                "is_valid": False,
                "error": (
                    "[Error: 8] 在文件中找不到 old_string。"
                    "请确认缩进、换行和空白字符均与文件内容完全一致。"
                    f"\n你提供的 old_string 前 200 字符:\n{excerpt}"
                ),
            },
            ensure_ascii=False,
        )
    if occurrences > 1 and not replace_all:
        return json.dumps(
            {
                "is_valid": False,
                "error": (
                    f"[Error: 9] 发现 {occurrences} 处匹配，但 replace_all=False。"
                    "请在 old_string 中增加更多上下文行以确保唯一性。"
                ),
            },
            ensure_ascii=False,
        )

    updated = content.replace(old_string, new_string) if replace_all else content.replace(old_string, new_string, 1)

    try:
        with open(resolved, "w", encoding="utf-8") as fh:
            fh.write(updated)
        new_mtime = os.path.getmtime(resolved)
    except OSError as exc:
        return json.dumps({"is_valid": False, "error": f"[Error: 5] 写入失败：{exc}"}, ensure_ascii=False)

    return json.dumps(
        {
            # Refresh mtime in ChemState so chained edits work without re-read.
            "__file_protocol__": "FileRead",
            "path": resolved,
            "mtime": new_mtime,
            "is_valid": True,
            "replacements_made": occurrences if replace_all else 1,
        },
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# Tool list for catalog registration
# ---------------------------------------------------------------------------

ALL_FILE_OPS_TOOLS = [
    tool_read_file,
    tool_write_file,
    tool_edit_file,
]
