"""engine_sse — Stateless SSE event-parsing helpers.

Pure functions and constants extracted from engine.py so that the session
lifecycle logic stays separate from the LangGraph→SSE event translation layer.

Importing this module has no side-effects and requires no network or I/O.
"""

from __future__ import annotations

import json
from typing import Any

# ── Module-level constants ─────────────────────────────────────────────────────

# Keys stripped from tool_end SSE events — emitted separately as artifact events.
_BULKY_TOOL_OUTPUT_KEYS = frozenset({
    "image",
    "structure_image",
    "highlighted_image",
    "molecule_image",
    "scaffold_image",
    "sdf_content",
    "pdbqt_content",
})

# Keys whose values are collapsed into the Redis artifact store (data-plane).
_ARTIFACT_COLLAPSE_KEYS = frozenset({
    "pdbqt_content",
    "sdf_content",
    "large_descriptor_matrix",
})

_SILENT_TOOL_NAMES = frozenset({"tool_update_task_status"})

# LangGraph node names whose LLM token stream is forwarded to the client.
_STREAMING_NODES = {"chem_agent"}

# Sub-graph node name prefix — tokens from sub-agent nodes are also streamed.
_SUB_AGENT_NODE_PREFIX = "sub_agent"

# LangGraph node names for which we emit node_start / node_end lifecycle events.
_LIFECYCLE_NODES = {"task_router", "planner_node", "chem_agent", "tools_executor"}

_NODE_REASONING_MESSAGES: dict[tuple[str, str], str] = {
    ("task_router", "on_chain_start"): "正在快速判断这次请求是否需要显式任务规划...",
    ("task_router", "on_chain_end"): "复杂度判断完成。",
    ("planner_node", "on_chain_start"): "检测到复杂任务，正在生成可执行任务清单...",
    ("planner_node", "on_chain_end"): "任务清单已生成，准备进入执行阶段。",
    ("chem_agent", "on_chain_start"): "进入智能体大脑，正在评估当前信息并规划下一步行动...",
    ("chem_agent", "on_chain_end"): "智能体本轮思考完毕。",
    ("tools_executor", "on_chain_start"): "准备转入工具执行流水线...",
    ("tools_executor", "on_chain_end"): "工具调用链执行完毕，正在将实验数据交回给智能体大脑。",
}

_TOOL_LABELS: dict[str, str] = {
    "validate_smiles": "校验 SMILES",
    "strip_salts": "去除盐和溶剂",
    "pubchem_lookup": "PubChem 检索",
    "compute_descriptors": "计算分子描述符",
    "compute_mol_properties": "计算分子性质",
    "substructure_match": "子结构匹配",
    "murcko_scaffold": "提取 Murcko Scaffold",
    "render_smiles": "渲染二维结构图",
    "build_3d_conformer": "生成三维构象",
    "prepare_pdbqt": "准备 PDBQT 文件",
    "convert_format": "格式转换",
    "ask_human": "请求用户澄清",
    "web_search": "联网搜索",
    "update_task_status": "更新任务状态",
}

# Chemical error keywords that trigger error withholding + automatic retry.
_WITHHELD_ERROR_KEYWORDS = (
    "valence",
    "invalid smiles",
    "kekulize",
    "sanitize",
)


# ── Internal retry signal ──────────────────────────────────────────────────────


class _ChemRetrySignal(Exception):
    """Raised by the outer loop to trigger an automatic self-correction retry."""

    def __init__(self, error_msg: str, new_messages: list) -> None:
        self.error_msg = error_msg
        self.new_messages = new_messages


# ── Pure helper functions ──────────────────────────────────────────────────────


def _preview(value: object, max_len: int = 1200) -> str:
    """Best-effort compact preview for debug logs."""
    try:
        if isinstance(value, (dict, list)):
            text = json.dumps(value, ensure_ascii=False)
        else:
            text = str(value)
    except Exception:
        text = repr(value)
    if len(text) > max_len:
        return text[:max_len] + "...<truncated>"
    return text


def _extract_stream_text(raw: object, chunk: object) -> tuple[str, str]:
    """Extract ``(token_text, reasoning_text)`` from LLM stream chunks.

    Supports OpenAI/Responses, Anthropic, and provider-compatibility shapes.
    """
    token_parts: list[str] = []
    reasoning_parts: list[str] = []

    def _append_text(target: list[str], value: object) -> None:
        if isinstance(value, str) and value:
            target.append(value)

    if isinstance(raw, str):
        token_parts.append(raw)
    elif isinstance(raw, dict):
        block_type = str(raw.get("type", "")).lower()
        if block_type in {"reasoning", "thinking"}:
            summary = raw.get("summary")
            if isinstance(summary, list):
                for item in summary:
                    if isinstance(item, dict):
                        _append_text(reasoning_parts, item.get("text"))
                    else:
                        _append_text(reasoning_parts, item)
            else:
                _append_text(reasoning_parts, summary)
            _append_text(reasoning_parts, raw.get("text"))
            _append_text(reasoning_parts, raw.get("thinking"))
        elif block_type in {"text", "output_text"}:
            _append_text(token_parts, raw.get("text"))
        elif block_type == "message":
            msg_content = raw.get("content", [])
            if isinstance(msg_content, list):
                for c in msg_content:
                    if isinstance(c, dict):
                        _append_text(token_parts, c.get("text"))
                    else:
                        _append_text(token_parts, c)
            else:
                _append_text(token_parts, msg_content)
        else:
            _append_text(token_parts, raw.get("text"))
            _append_text(reasoning_parts, raw.get("reasoning"))
    elif isinstance(raw, list):
        for block in raw:
            if isinstance(block, dict):
                block_type = str(block.get("type", "")).lower()
                if block_type == "reasoning":
                    summary = block.get("summary", [])
                    if isinstance(summary, list):
                        for s in summary:
                            if isinstance(s, dict):
                                _append_text(reasoning_parts, s.get("text"))
                            else:
                                _append_text(reasoning_parts, s)
                    elif isinstance(summary, str):
                        _append_text(reasoning_parts, summary)
                    _append_text(reasoning_parts, block.get("text"))
                elif block_type == "message":
                    msg_content = block.get("content", [])
                    if isinstance(msg_content, list):
                        for c in msg_content:
                            if isinstance(c, dict):
                                _append_text(token_parts, c.get("text"))
                            else:
                                _append_text(token_parts, c)
                    elif isinstance(msg_content, str):
                        _append_text(token_parts, msg_content)
                elif block_type in {"text", "output_text"}:
                    _append_text(token_parts, block.get("text"))
                elif block_type == "thinking":
                    _append_text(reasoning_parts, block.get("thinking"))
                    _append_text(reasoning_parts, block.get("text"))
            else:
                _append_text(token_parts, block)

    additional_kwargs = getattr(chunk, "additional_kwargs", {}) or {}
    if isinstance(additional_kwargs, dict):
        _append_text(reasoning_parts, additional_kwargs.get("reasoning_content"))
        _append_text(reasoning_parts, additional_kwargs.get("thinking"))
        _append_text(reasoning_parts, additional_kwargs.get("reasoning"))

    return "".join(token_parts), "".join(reasoning_parts)


def _parse_tool_output(tool_output: Any) -> dict | str:
    if isinstance(tool_output, str):
        try:
            return json.loads(tool_output)
        except Exception:
            return tool_output
    return tool_output


def _sanitize_tool_output(tool_name: str, output: dict | str) -> dict | str:
    """Strip bulky artifact payloads so tool_end events stay compact.

    Rich media is emitted separately via custom ``artifact`` SSE events.
    """
    if not isinstance(output, dict):
        return output

    sanitized = dict(output)
    removed = [key for key in _BULKY_TOOL_OUTPUT_KEYS if key in sanitized]
    for key in removed:
        sanitized.pop(key, None)

    if tool_name == "tool_convert_format" and isinstance(sanitized.get("output"), str):
        output_text = sanitized["output"]
        if len(output_text) > 500:
            sanitized["output"] = (
                f"已生成 {sanitized.get('output_format', '').upper()} 内容，"
                "完整结果通过 artifact 事件发送"
            )
            removed.append("output")

    if removed:
        sanitized["artifact_payloads_removed"] = sorted(set(removed))

    return sanitized
