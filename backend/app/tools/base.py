"""BaseChemTool — Strong-contract tool base class for ChemAgent.

Design mirrors Claude Code ``Tool.ts`` / ``buildTool()`` philosophy:

  1. ``validate_input()``    — parameter correctness only; failure surfaces a
                               model-retryable error with no UI shown to the user.
  2. ``check_permissions()`` — authorisation; called ONLY after validate_input
                               passes; failure triggers the HITL approval gate.
  3. ``prompt()``            — per-tool JIT system prompt contribution; async-
                               capable so skill tools can read reference docs.
  4. ``description()``       — context-aware dynamic tool description.
  5. ``max_result_size_chars`` — mandatory output size declaration; executor
                               truncates and spills to file when exceeded.
  6. ``build_chem_tool()``   — factory function (mirrors ``buildTool()``) for
                               simple tools that do not need a full class.

Execution strategy mid-classes
-------------------------------
  ChemComputeTool  — subprocess-isolated CPU-bound ops (RDKit sync, Babel)
                     or asyncio.wait_for for async compute tools.
  ChemLookupTool   — async I/O with asyncio.wait_for timeout (PubChem, web,
                     database API calls).
  ChemStateTool    — pure state writes, no timeout, direct execution.
  ChemIOTool       — file system ops; path safety enforced in validate_input().
  ChemShellTool    — shell execution; dangerous-command check in
                     check_permissions() so blocked commands route to HITL.
  ChemControlTool  — HITL / orchestration (ask_human, update_task_status,
                     run_sub_agent); no timeout, no isolation.
"""

from __future__ import annotations

import asyncio
import contextvars
import inspect
import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Generic, TypeVar

# Tools that need the originating RunnableConfig (e.g. tool_invoke_skill for
# config-forwarding to sub-agents) can read this contextvar.  It is set by
# every mid-class _afunc before calling tool.call().
_current_tool_config: contextvars.ContextVar[RunnableConfig | None] = contextvars.ContextVar(
    "_current_tool_config", default=None
)

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from app.domain.schemas.workflow import PermissionResult, ValidationResult
from app.tools.metadata import (
    CHEM_TIMEOUT_METADATA_KEY,
    CHEM_TIER_METADATA_KEY,
    ChemToolTier,
)

# Re-use execution infrastructure from decorators to share _SYNC_CALLABLE_REGISTRY
# and the subprocess plumbing.  decorators.py does NOT import base.py so there
# is no circular dependency.
from app.tools.decorators import (
    DEFAULT_CHEM_TOOL_TIMEOUT_SECONDS,
    TimeoutException,
    _SubprocessToolError,
    _SYNC_CALLABLE_REGISTRY,
    _build_error_payload,
    _format_details,
    _run_sync_with_timeout,
    _translate_protocol,
)

logger = logging.getLogger(__name__)

T_Input = TypeVar("T_Input", bound=BaseModel)
T_Output = TypeVar("T_Output")

# ── New metadata keys ─────────────────────────────────────────────────────────

CHEM_READ_ONLY_KEY = "chem_read_only"
CHEM_DIAGNOSTIC_KEYS_KEY = "chem_diagnostic_keys"
CHEM_CONCURRENCY_SAFE_KEY = "chem_concurrency_safe"
CHEM_MAX_RESULT_SIZE_KEY = "chem_max_result_size_chars"


# ── Base class ────────────────────────────────────────────────────────────────


class BaseChemTool(ABC, Generic[T_Input, T_Output]):
    """Abstract base for all ChemAgent tools.

    Subclass the appropriate mid-class (ChemComputeTool, ChemLookupTool, …)
    rather than this class directly.  Each mid-class chooses the right
    execution strategy (subprocess, asyncio.wait_for, direct).

    Required class attributes
    -------------------------
    name              : str
    args_schema       : type[T_Input]   — Pydantic model for tool arguments
    max_result_size_chars : int         — mandatory; executor truncates above limit
    tier              : ChemToolTier | None

    Fail-closed defaults (override as needed)
    -----------------------------------------
    read_only         : bool = False     — assume write operations
    is_concurrency_safe : bool = False   — assume not safe to run in parallel
    diagnostic_keys   : list[str] = []  — keys auto-patched into molecule_tree
    timeout           : float = 0.0     — 0 = no timeout; mid-classes set sensible
                                          defaults via _default_timeout()
    """

    # Required — no defaults; subclass MUST set these as class attributes.
    name: str
    args_schema: type[T_Input]
    max_result_size_chars: int
    tier: ChemToolTier | None

    # Fail-closed defaults.
    read_only: bool = False
    is_concurrency_safe: bool = False
    diagnostic_keys: list[str] = []
    timeout: float = 0.0

    # ── Abstract ──────────────────────────────────────────────────────────────

    @abstractmethod
    def call(self, args: T_Input) -> T_Output | Awaitable[T_Output]:
        """Core execution logic.

        May be either a regular ``def`` (sync, run in subprocess/executor by
        ``ChemComputeTool``) or an ``async def`` (run under
        ``asyncio.wait_for`` by ``ChemComputeTool`` / ``ChemLookupTool``).
        The mid-class detects which form is in use via
        ``asyncio.iscoroutinefunction(self.call)`` at tool-registration time.

        The originating ``RunnableConfig`` is available at any call site via
        ``_current_tool_config.get()`` from ``app.tools.base``.
        """

    # ── Overridable with safe defaults ────────────────────────────────────────

    async def description(self, context: dict) -> str:
        """Dynamic tool description.

        Defaults to the ``call()`` docstring so existing docstrings continue
        to work.  Override to produce context-aware descriptions (e.g. expose
        different guidance for explore vs. general sub-agent modes).
        """
        return inspect.getdoc(self.call) or self.name

    async def prompt(self, context: dict) -> str:
        """JIT system prompt contribution for this tool.

        Returns an empty string by default.  Override — async is OK — to
        inject tool-specific guidance into the sub-agent's system prompt at
        allocation time (e.g. skill tools can asynchronously load reference
        documentation here).
        """
        return ""

    async def validate_input(self, args: T_Input, context: dict) -> ValidationResult:
        """Validate argument correctness.

        Failure → the executor surfaces the message to the model so it can
        correct its arguments and retry.  **No UI is shown to the user.**
        Only put parameter-level checks here (format, length, logic).
        Path-traversal guards for file tools belong here, NOT in
        check_permissions().
        """
        return ValidationResult(result=True)

    async def check_permissions(self, args: T_Input, context: dict) -> PermissionResult:
        """Check authorisation for this tool call.

        Only called when validate_input() passes.  Failure → HITL approval
        gate is triggered and the user sees ``reason``.
        Dangerous-shell-command guards belong here, NOT in validate_input().
        """
        return PermissionResult(granted=True)

    def is_destructive(self, args: T_Input) -> bool:
        """Return True for irreversible operations (delete, overwrite, send).

        Default False (fail-safe: assume reversible unless explicitly declared).
        """
        return False

    # ── Concrete adapter ──────────────────────────────────────────────────────

    def as_langchain_tool(self) -> StructuredTool:
        """Return a LangChain StructuredTool bound to this instance.

        The generated async wrapper:
        1. Extracts ``context`` from ``RunnableConfig["configurable"]``.
        2. Builds the Pydantic args model from LangChain kwargs.
        3. Calls ``validate_input(args, context)`` — returns model-retryable
           error on failure.
        4. Calls ``check_permissions(args, context)`` — triggers HITL on failure.
        5. Executes ``call(args)`` via the mid-class execution strategy.
        6. Applies ``_translate_protocol()`` for state-protocol-emitting tools.
        7. Enforces ``max_result_size_chars`` truncation.
        """
        return self._build_langchain_tool()

    # ── Internal helpers ──────────────────────────────────────────────────────

    @abstractmethod
    def _build_langchain_tool(self) -> StructuredTool:
        """Implemented by each mid-class with its execution strategy."""

    def _effective_timeout(self) -> float:
        """Return the timeout to enforce, using _default_timeout() as fallback."""
        if self.timeout > 0:
            return self.timeout
        return self._default_timeout()

    def _default_timeout(self) -> float:
        """Override in mid-classes to provide a sensible default."""
        return 0.0

    def _build_metadata(self) -> dict[str, Any]:
        meta: dict[str, Any] = {
            CHEM_READ_ONLY_KEY: self.read_only,
            CHEM_DIAGNOSTIC_KEYS_KEY: list(self.diagnostic_keys),
            CHEM_CONCURRENCY_SAFE_KEY: self.is_concurrency_safe,
            CHEM_MAX_RESULT_SIZE_KEY: self.max_result_size_chars,
        }
        if self.tier is not None:
            meta[CHEM_TIER_METADATA_KEY] = self.tier
        t = self._effective_timeout()
        if t > 0:
            meta[CHEM_TIMEOUT_METADATA_KEY] = t
        return meta

    def _truncate_if_needed(self, result: str) -> str:
        if len(result) <= self.max_result_size_chars:
            return result
        preview = result[: self.max_result_size_chars]
        return (
            preview
            + f"\n... [output truncated: {len(result)} chars total, limit {self.max_result_size_chars}]"
        )

    async def _gate(self, args: T_Input, context: dict) -> str | None:
        """Run validate_input → check_permissions gate.

        Returns a JSON error string on failure, None on success.
        The error string is returned directly as the tool result so the LLM
        (or executor) can decide how to proceed without touching the UI path.
        """
        validation = await self.validate_input(args, context)
        if not validation.result:
            return json.dumps(
                {
                    "status": "error",
                    "error_boundary": "validate_input",
                    "tool_name": self.name,
                    "error": validation.message or "Input validation failed.",
                    "error_code": validation.error_code,
                    "is_retryable": True,
                },
                ensure_ascii=False,
            )

        permission = await self.check_permissions(args, context)
        if not permission.granted:
            return json.dumps(
                {
                    "status": "permission_denied",
                    "error_boundary": "check_permissions",
                    "tool_name": self.name,
                    "error": permission.reason or "Permission denied.",
                    "is_retryable": False,
                },
                ensure_ascii=False,
            )

        return None

    def _make_description(self) -> str:
        """Synchronous description for StructuredTool construction."""
        return inspect.getdoc(self.call) or self.name


# ── Mid-class: ChemComputeTool ────────────────────────────────────────────────


class ChemComputeTool(BaseChemTool[T_Input, T_Output]):
    """Execution strategy: subprocess isolation for sync call(), asyncio.wait_for
    for async call().

    Use for CPU-bound chemistry operations (RDKit, Babel) where:
    - Subprocess isolation protects the main process from C-extension crashes.
    - Timeout enforcement is critical to avoid runaway computations.
    - Protocol translation (NodeCreate / NodeUpdate) may be needed.
    """

    def _default_timeout(self) -> float:
        return DEFAULT_CHEM_TOOL_TIMEOUT_SECONDS

    def _build_langchain_tool(self) -> StructuredTool:
        tool_instance = self
        tool_name = self.name
        timeout_seconds = self._effective_timeout()
        is_async_call = asyncio.iscoroutinefunction(self.call)

        # Register sync call() in the subprocess registry so that workers that
        # re-import this module can resolve and execute the method.
        if not is_async_call:
            _SYNC_CALLABLE_REGISTRY[
                f"{type(self).__module__}:{type(self).__qualname__}.call"
            ] = self.call

        async def _afunc(config: RunnableConfig | None = None, **kwargs: Any) -> Any:
            context = dict((config or {}).get("configurable", {}))
            _current_tool_config.set(config)
            args = tool_instance.args_schema(**kwargs)

            err = await tool_instance._gate(args, context)
            if err is not None:
                return err

            try:
                if is_async_call:
                    raw = await asyncio.wait_for(
                        tool_instance.call(args),  # type: ignore[arg-type]
                        timeout=timeout_seconds if timeout_seconds > 0 else None,
                    )
                else:
                    raw = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: _run_sync_with_timeout(
                            tool_instance.call,
                            (args,),
                            {},
                            timeout_seconds=timeout_seconds,
                        ),
                    )
            except TimeoutException:
                # Raised by _run_sync_with_timeout (subprocess timeout).
                return _build_error_payload(
                    tool_name=tool_name,
                    error_type="TimeoutException",
                    details=f"Execution exceeded {timeout_seconds:g}s timeout.",
                    traceback_text="",
                    timeout_seconds=timeout_seconds,
                )
            except asyncio.TimeoutError:
                # Raised by asyncio.wait_for (async tool timeout).
                return _build_error_payload(
                    tool_name=tool_name,
                    error_type="TimeoutException",
                    details=f"Execution exceeded {timeout_seconds:g}s timeout.",
                    traceback_text="",
                    timeout_seconds=timeout_seconds,
                )
            except _SubprocessToolError as exc:
                return _build_error_payload(
                    tool_name=tool_name,
                    error_type=exc.error_type,
                    details=exc.details,
                    traceback_text=exc.traceback_text,
                    timeout_seconds=timeout_seconds,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("ChemComputeTool %s failed", tool_name, exc_info=True)
                import traceback as _tb
                return _build_error_payload(
                    tool_name=tool_name,
                    error_type=type(exc).__name__,
                    details=_format_details(exc),
                    traceback_text=_tb.format_exc(),
                    timeout_seconds=timeout_seconds,
                )

            result = _translate_protocol(raw)
            if isinstance(result, str):
                result = tool_instance._truncate_if_needed(result)
            return result

        st = StructuredTool.from_function(
            coroutine=_afunc,
            name=self.name,
            description=self._make_description(),
            args_schema=self.args_schema,
        )
        st.metadata = {**(getattr(st, "metadata", None) or {}), **self._build_metadata()}
        return st


# ── Mid-class: ChemLookupTool ─────────────────────────────────────────────────


class ChemLookupTool(BaseChemTool[T_Input, T_Output]):
    """Execution strategy: asyncio.wait_for with timeout; no subprocess isolation.

    Use for async I/O tools (PubChem, web search, database API) that are
    network-bound and do not run CPU-heavy C extensions.
    """

    def _default_timeout(self) -> float:
        return DEFAULT_CHEM_TOOL_TIMEOUT_SECONDS

    def _build_langchain_tool(self) -> StructuredTool:
        tool_instance = self
        tool_name = self.name
        timeout_seconds = self._effective_timeout()

        async def _afunc(config: RunnableConfig | None = None, **kwargs: Any) -> Any:  # ChemLookupTool
            context = dict((config or {}).get("configurable", {}))
            _current_tool_config.set(config)
            args = tool_instance.args_schema(**kwargs)

            err = await tool_instance._gate(args, context)
            if err is not None:
                return err

            try:
                raw = await asyncio.wait_for(
                    tool_instance.call(args),  # type: ignore[arg-type]
                    timeout=timeout_seconds if timeout_seconds > 0 else None,
                )
            except asyncio.TimeoutError:
                return _build_error_payload(
                    tool_name=tool_name,
                    error_type="TimeoutException",
                    details=f"Execution exceeded {timeout_seconds:g}s timeout.",
                    traceback_text="",
                    timeout_seconds=timeout_seconds,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("ChemLookupTool %s failed", tool_name, exc_info=True)
                import traceback as _tb
                return _build_error_payload(
                    tool_name=tool_name,
                    error_type=type(exc).__name__,
                    details=_format_details(exc),
                    traceback_text=_tb.format_exc(),
                    timeout_seconds=timeout_seconds,
                )

            if isinstance(raw, str):
                raw = tool_instance._truncate_if_needed(raw)
            return raw

        st = StructuredTool.from_function(
            coroutine=_afunc,
            name=self.name,
            description=self._make_description(),
            args_schema=self.args_schema,
        )
        st.metadata = {**(getattr(st, "metadata", None) or {}), **self._build_metadata()}
        return st


# ── Mid-class: ChemStateTool ──────────────────────────────────────────────────


class ChemStateTool(BaseChemTool[T_Input, T_Output]):
    """Execution strategy: direct execution, no timeout, no subprocess.

    Use for pure state-write operations (scratchpad, molecule tree, viewport,
    diagnostics, screening) that are fast, in-process, and cannot crash.
    """

    def _build_langchain_tool(self) -> StructuredTool:
        tool_instance = self
        tool_name = self.name
        is_async_call = asyncio.iscoroutinefunction(self.call)

        async def _afunc(config: RunnableConfig | None = None, **kwargs: Any) -> Any:  # ChemStateTool
            context = dict((config or {}).get("configurable", {}))
            _current_tool_config.set(config)
            args = tool_instance.args_schema(**kwargs)

            err = await tool_instance._gate(args, context)
            if err is not None:
                return err

            try:
                if is_async_call:
                    raw = await tool_instance.call(args)  # type: ignore[arg-type]
                else:
                    raw = tool_instance.call(args)
            except Exception as exc:  # noqa: BLE001
                logger.warning("ChemStateTool %s failed", tool_name, exc_info=True)
                import traceback as _tb
                return _build_error_payload(
                    tool_name=tool_name,
                    error_type=type(exc).__name__,
                    details=_format_details(exc),
                    traceback_text=_tb.format_exc(),
                    timeout_seconds=0.0,
                )

            result = _translate_protocol(raw)
            if isinstance(result, str):
                result = tool_instance._truncate_if_needed(result)
            return result

        st = StructuredTool.from_function(
            coroutine=_afunc,
            name=self.name,
            description=self._make_description(),
            args_schema=self.args_schema,
        )
        st.metadata = {**(getattr(st, "metadata", None) or {}), **self._build_metadata()}
        return st


# ── Mid-class: ChemIOTool ─────────────────────────────────────────────────────


class ChemIOTool(ChemStateTool[T_Input, T_Output]):
    """Execution strategy: direct async execution; path safety enforced in
    validate_input().

    Use for file system tools (read, write, edit).  Path-traversal and
    whitelist checks belong in validate_input() so that the model receives
    a retryable error — NOT a HITL gate — when it supplies an out-of-scope
    path.
    """


# ── Mid-class: ChemShellTool ──────────────────────────────────────────────────


class ChemShellTool(ChemStateTool[T_Input, T_Output]):
    """Execution strategy: direct async execution; dangerous-command check in
    check_permissions().

    Structural difference from ChemIOTool: blocked shell patterns (rm -rf /,
    command substitution, etc.) route through check_permissions() so the user
    sees the HITL gate rather than a silent model-retryable rejection.
    This matches the intent of the shell's three-layer defence: when a command
    is categorically unsafe, it is a *permission* issue, not a *parameter*
    formatting issue.
    """


# ── Mid-class: ChemControlTool ───────────────────────────────────────────────


class ChemControlTool(BaseChemTool[T_Input, T_Output]):
    """Execution strategy: direct execution, no timeout, no isolation.

    Use for HITL and orchestration tools (ask_human, update_task_status,
    run_sub_agent).  These tools manage the agent lifecycle and must never
    be wrapped in subprocess isolation or timeouts that could swallow
    LangGraph interrupt signals.
    """

    def _build_langchain_tool(self) -> StructuredTool:
        tool_instance = self
        tool_name = self.name
        is_async_call = asyncio.iscoroutinefunction(self.call)

        async def _afunc(config: RunnableConfig | None = None, **kwargs: Any) -> Any:  # ChemControlTool
            context = dict((config or {}).get("configurable", {}))
            _current_tool_config.set(config)
            args = tool_instance.args_schema(**kwargs)

            err = await tool_instance._gate(args, context)
            if err is not None:
                return err

            try:
                if is_async_call:
                    return await tool_instance.call(args)  # type: ignore[arg-type]
                return tool_instance.call(args)
            except Exception as exc:  # noqa: BLE001
                # Re-raise: control tools (e.g. run_sub_agent) may deliberately
                # raise LangGraph interrupt signals that must propagate upward.
                raise exc

        st = StructuredTool.from_function(
            coroutine=_afunc,
            name=self.name,
            description=self._make_description(),
            args_schema=self.args_schema,
        )
        st.metadata = {**(getattr(st, "metadata", None) or {}), **self._build_metadata()}
        return st


# ── Factory: build_chem_tool() ────────────────────────────────────────────────


def build_chem_tool(
    *,
    name: str,
    call: Any,
    args_schema: type[BaseModel],
    tier: ChemToolTier | None,
    max_result_size_chars: int,
    mid_class: type[BaseChemTool] = ChemStateTool,  # type: ignore[type-arg]
    read_only: bool = False,
    is_concurrency_safe: bool = False,
    diagnostic_keys: list[str] | None = None,
    timeout: float = 0.0,
) -> StructuredTool:
    """Convenience factory for simple tools that do not need a full class.

    Mirrors Claude Code's ``buildTool()`` — fills in fail-closed defaults so
    callers never need to write a complete class for straightforward tools.

    Parameters
    ----------
    name:
        LangChain tool name string (e.g. ``"tool_ask_human"``).
    call:
        The core callable (sync or async function).  Will be bound as the
        ``call()`` method of a generated subclass.
    args_schema:
        Pydantic model defining tool arguments.
    tier:
        ``"L1"`` / ``"L2"`` / ``None``.
    max_result_size_chars:
        Hard upper bound on result size.
    mid_class:
        Which execution mid-class to use.  Defaults to ``ChemStateTool``
        (direct, no timeout) — the safest default for simple tools.
    read_only:
        Fail-closed default ``False``.
    is_concurrency_safe:
        Fail-closed default ``False``.
    diagnostic_keys:
        Keys auto-patched into ``molecule_tree`` diagnostics.
    timeout:
        Execution timeout in seconds; 0 disables.

    Returns
    -------
    StructuredTool
        Ready for inclusion in ``ALL_CHEM_TOOLS``.
    """
    _diagnostic_keys = list(diagnostic_keys or [])

    # Dynamically create a minimal subclass of the requested mid-class.
    GeneratedTool: type[BaseChemTool] = type(  # type: ignore[assignment]
        f"_GeneratedChemTool_{name}",
        (mid_class,),
        {
            "name": name,
            "args_schema": args_schema,
            "max_result_size_chars": max_result_size_chars,
            "tier": tier,
            "read_only": read_only,
            "is_concurrency_safe": is_concurrency_safe,
            "diagnostic_keys": _diagnostic_keys,
            "timeout": timeout,
            "call": (lambda self, args: call(args))  # bind call fn as method
            if not asyncio.iscoroutinefunction(call)
            else (lambda self, args: call(args)),  # same for async; abc satisfied
        },
    )
    # For async call, override with proper coroutine method so iscoroutinefunction works.
    if asyncio.iscoroutinefunction(call):
        async def _async_call(self: Any, args: Any) -> Any:
            return await call(args)
        GeneratedTool.call = _async_call  # type: ignore[method-assign]
    else:
        def _sync_call(self: Any, args: Any) -> Any:
            return call(args)
        GeneratedTool.call = _sync_call  # type: ignore[method-assign]

    return GeneratedTool().as_langchain_tool()
