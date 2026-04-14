"""File Operation Tools -- class-based BaseChemTool contract.

Three tools that give the LLM controlled access to the host file system:
  ToolReadFile   -- read a file; emits FileRead protocol for mtime tracking
  ToolWriteFile  -- create or overwrite a file with read-guard + LF normalisation
  ToolEditFile   -- search-and-replace edit with anti-hallucination guards
"""

from __future__ import annotations

import json
import logging
import os

from pydantic import BaseModel, Field

from app.domain.schemas.workflow import ValidationResult
from app.tools.base import ChemIOTool, _current_tool_config

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
# Read-guard helper
# ---------------------------------------------------------------------------


def _check_read_guard(
    resolved_path: str,
    current_mtime: float,
    read_file_state: dict,
) -> str | None:
    """Return an error string if the read guard fails, else None."""
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


# ── 1. tool_read_file ─────────────────────────────────────────────────────────


class ReadFileInput(BaseModel):
    path: str = Field(description="要读取的文件绝对路径")
    start_line: int = Field(default=0, description="从第几行开始读取（1-indexed，0 表示从头）")
    end_line: int = Field(default=0, description="读取到第几行（含，0 表示读到结尾）")


class ToolReadFile(ChemIOTool[ReadFileInput, str]):
    """Read a file and register it so tool_edit_file can proceed safely.

    Emits a ``__file_protocol__: "FileRead"`` marker that the executor picks
    up to write the file's mtime into ``ChemState.read_file_state``.
    """

    name = "tool_read_file"
    args_schema = ReadFileInput
    tier = "L1"
    read_only = True
    max_result_size_chars = 100_000

    async def validate_input(
        self, args: ReadFileInput, context: dict
    ) -> ValidationResult:
        if not args.path.strip():
            return ValidationResult(result=False, message="path 不能为空。")
        _, err = _resolve_and_validate(args.path)
        if err:
            return ValidationResult(result=False, message=err)
        return ValidationResult(result=True)

    def call(self, args: ReadFileInput) -> str:
        """Read a text file from the workspace and return its contents."""
        resolved, err = _resolve_and_validate(args.path)
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
        s = max(0, (args.start_line - 1) if args.start_line > 0 else 0)
        e = args.end_line if args.end_line > 0 else total_lines
        content = "".join(lines[s:e])

        truncated = False
        if len(content.encode()) > _MAX_READ_BYTES:
            content = content.encode()[:_MAX_READ_BYTES].decode(errors="replace")
            truncated = True

        return json.dumps(
            {
                "__file_protocol__": "FileRead",
                "path": resolved,
                "mtime": mtime,
                "is_valid": True,
                "total_lines": total_lines,
                "lines_returned": f"{s + 1}-{min(e, total_lines)}",
                "truncated": truncated,
                "content": content,
            },
            ensure_ascii=False,
        )


tool_read_file = ToolReadFile().as_langchain_tool()


# ── 2. tool_write_file ────────────────────────────────────────────────────────


class WriteFileInput(BaseModel):
    path: str = Field(description="要写入的文件绝对路径（不存在则创建，已存在则覆盖）")
    content: str = Field(description="要写入的完整文件内容")


class ToolWriteFile(ChemIOTool[WriteFileInput, str]):
    """Create a new file or completely overwrite an existing one.

    Guards: if the target file already exists, requires a prior tool_read_file
    call (mtime check via ChemState.read_file_state).  Emits FileRead so
    chained tool_edit_file calls work without a separate read step.
    """

    name = "tool_write_file"
    args_schema = WriteFileInput
    tier = "L2"
    read_only = False
    max_result_size_chars = 500

    async def validate_input(
        self, args: WriteFileInput, context: dict
    ) -> ValidationResult:
        if not args.path.strip():
            return ValidationResult(result=False, message="path 不能为空。")
        _, err = _resolve_and_validate(args.path)
        if err:
            return ValidationResult(result=False, message=err)
        return ValidationResult(result=True)

    def call(self, args: WriteFileInput) -> str:
        """Write or overwrite a file in the workspace with the given content."""
        resolved, err = _resolve_and_validate(args.path)
        if err:
            return json.dumps({"is_valid": False, "error": err}, ensure_ascii=False)

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

            config = _current_tool_config.get()
            injected_state: dict = (
                ((config or {}).get("configurable") or {}).get("read_file_state") or {}
            )
            guard_err = _check_read_guard(resolved, current_mtime, injected_state)
            if guard_err:
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

        content_lf = args.content.replace("\r\n", "\n")

        try:
            parent_dir = os.path.dirname(resolved)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)
            with open(resolved, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(content_lf)
            mtime = os.path.getmtime(resolved)
        except OSError as exc:
            return json.dumps({"is_valid": False, "error": f"[Error: 5] 写入失败：{exc}"}, ensure_ascii=False)

        lines_written = content_lf.count("\n") + (
            1 if content_lf and not content_lf.endswith("\n") else 0
        )
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


tool_write_file = ToolWriteFile().as_langchain_tool()


# ── 3. tool_edit_file ─────────────────────────────────────────────────────────


class EditFileInput(BaseModel):
    path: str = Field(description="要编辑的文件绝对路径")
    old_string: str = Field(
        description="要被替换的精确文本片段（必须与文件内容完全一致，包含缩进和换行）"
    )
    new_string: str = Field(description="替换后的新文本片段")
    replace_all: bool = Field(
        default=False,
        description="True = 替换所有匹配；False（默认）= old_string 必须全文唯一，否则报错",
    )


class ToolEditFile(ChemIOTool[EditFileInput, str]):
    """Edit a file using exact search-and-replace.

    Anti-hallucination guards:
    - Refuses unless tool_read_file was called first (mtime from ChemState).
    - Refuses if old_string appears 0 times (hallucinated content).
    - Refuses if old_string appears >1 time and replace_all=False (ambiguous).
    """

    name = "tool_edit_file"
    args_schema = EditFileInput
    tier = "L2"
    read_only = False
    max_result_size_chars = 500

    async def validate_input(
        self, args: EditFileInput, context: dict
    ) -> ValidationResult:
        if not args.path.strip():
            return ValidationResult(result=False, message="path 不能为空。")
        _, err = _resolve_and_validate(args.path)
        if err:
            return ValidationResult(result=False, message=err)
        if args.old_string == args.new_string:
            return ValidationResult(
                result=False, message="[Error: 1] old_string 与 new_string 完全相同，无需修改。"
            )
        return ValidationResult(result=True)

    def call(self, args: EditFileInput) -> str:
        """Apply an exact string replacement to a file in the workspace (requires prior read)."""
        resolved, err = _resolve_and_validate(args.path)
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

        config = _current_tool_config.get()
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

        occurrences = content.count(args.old_string)
        if occurrences == 0:
            excerpt = args.old_string[:200] + ("…" if len(args.old_string) > 200 else "")
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
        if occurrences > 1 and not args.replace_all:
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

        updated = content.replace(args.old_string, args.new_string) if args.replace_all else content.replace(args.old_string, args.new_string, 1)

        try:
            with open(resolved, "w", encoding="utf-8") as fh:
                fh.write(updated)
            new_mtime = os.path.getmtime(resolved)
        except OSError as exc:
            return json.dumps({"is_valid": False, "error": f"[Error: 5] 写入失败：{exc}"}, ensure_ascii=False)

        return json.dumps(
            {
                "__file_protocol__": "FileRead",
                "path": resolved,
                "mtime": new_mtime,
                "is_valid": True,
                "replacements_made": occurrences if args.replace_all else 1,
            },
            ensure_ascii=False,
        )


tool_edit_file = ToolEditFile().as_langchain_tool()


# ── Catalog ───────────────────────────────────────────────────────────────────

ALL_FILE_OPS_TOOLS = [
    tool_read_file,
    tool_write_file,
    tool_edit_file,
]

