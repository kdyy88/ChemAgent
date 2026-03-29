"""
SSE smoke test for POST /api/chat/stream

Run from the repo root:
    cd backend
    uv run python tests/test_sse_stream.py [--url URL] [--smiles SMILES] [message]

Examples
─────────
    # Default: Aspirin descriptors
    uv run python tests/test_sse_stream.py

    # Custom message
    uv run python tests/test_sse_stream.py "画出布洛芬的结构图"

    # Provide an explicit SMILES (triggers Shadow Lab path)
    uv run python tests/test_sse_stream.py --smiles "CC(=O)Oc1ccccc1C(=O)O" "计算阿司匹林的 Lipinski 性质"

    # Test Shadow Lab with a deliberately broken SMILES
    uv run python tests/test_sse_stream.py --smiles "C1CC1C1CCCC1CCCC" "分析这个分子"

Output legend
─────────────
    run_started  → [START]      green header
    node_start   → [NODE >>]    cyan node name
    token        → inline text  white (typewriter append)
    tool_start   → [TOOL ▶]    yellow
    tool_end     → [TOOL ✓]    green
    artifact     → [ARTIFACT]  magenta summary
    shadow_error → [SHADOW ⚠]  red warning
    node_end     → [NODE <<]   dim
    done         → [DONE]      green footer with timing
    error        → [ERROR]     red
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid

import requests

# ── ANSI colours (safe on most terminals) ─────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RED    = "\033[31m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
MAGENTA= "\033[35m"
WHITE  = "\033[37m"


def colour(text: str, *codes: str) -> str:
    return "".join(codes) + text + RESET


# ── Event printers ─────────────────────────────────────────────────────────────

_current_node: str = ""
_token_buf: str = ""       # accumulate tokens for this node


def _flush_tokens() -> None:
    global _token_buf
    if _token_buf:
        print()  # newline after typewriter output
        _token_buf = ""


def handle_event(ev: dict) -> None:
    global _current_node, _token_buf
    t = ev.get("type", "")

    if t == "run_started":
        print(colour(
            f"\n{'═'*60}\n[START] turn_id={ev.get('turn_id', '?')}\n"
            f"  message: {ev.get('message', '')}\n{'═'*60}",
            BOLD, GREEN,
        ))

    elif t == "node_start":
        _flush_tokens()
        node = ev.get("node", "?")
        _current_node = node
        print(colour(f"\n[NODE >>] {node}", CYAN, BOLD))

    elif t == "token":
        tok = ev.get("content", "")
        # Responses API may yield a list of content blocks; flatten to str
        if isinstance(tok, list):
            tok = "".join(
                b.get("text", "") if isinstance(b, dict) else str(b) for b in tok
            )
        _token_buf += str(tok)
        print(colour(tok, WHITE), end="", flush=True)

    elif t == "tool_start":
        _flush_tokens()
        tool = ev.get("tool", "?")
        inp  = ev.get("input", {})
        # Show first SMILES / query arg if present for readability
        arg_preview = next(iter(inp.values()), "") if inp else ""
        if isinstance(arg_preview, str) and len(arg_preview) > 60:
            arg_preview = arg_preview[:60] + "…"
        print(colour(f"  [TOOL ▶] {tool}({arg_preview})", YELLOW))

    elif t == "tool_end":
        tool   = ev.get("tool", "?")
        output = ev.get("output", {})
        valid  = output.get("is_valid", "?") if isinstance(output, dict) else "?"
        # Summarise output without dumping bulk base64 data
        keys   = list(output.keys()) if isinstance(output, dict) else []
        safe_keys = [k for k in keys if "image" not in k and "structure" not in k]
        print(colour(f"  [TOOL ✓] {tool}  is_valid={valid}  fields={safe_keys}", GREEN))

    elif t == "artifact":
        _flush_tokens()
        kind   = ev.get("kind", "?")
        title  = ev.get("title", "")
        smiles = ev.get("smiles", "")
        if kind == "molecule_image":
            data   = ev.get("data", "")
            size_kb = round(len(data) * 3 / 4 / 1024, 1)  # base64 → bytes estimate
            print(colour(
                f"  [ARTIFACT] molecule_image  smiles={smiles}  "
                f"png≈{size_kb} KB  title='{title}'",
                MAGENTA, BOLD,
            ))
        elif kind == "descriptors":
            data = ev.get("data", {})
            desc = data.get("descriptors", {})
            summary = (
                f"MW={desc.get('molecular_weight', '?')}  "
                f"LogP={desc.get('log_p', '?')}  "
                f"QED={desc.get('qed', '?')}  "
                f"SA={desc.get('sa_score', '?')}"
            )
            print(colour(
                f"  [ARTIFACT] descriptors  {summary}  title='{title}'",
                MAGENTA, BOLD,
            ))
        else:
            print(colour(f"  [ARTIFACT] {kind}  title='{title}'", MAGENTA))

    elif t == "shadow_error":
        _flush_tokens()
        print(colour(
            f"\n  [SHADOW ⚠] SMILES validation FAILED\n"
            f"    smiles : {ev.get('smiles', '?')}\n"
            f"    error  : {ev.get('error', '?')}",
            RED, BOLD,
        ))

    elif t == "node_end":
        node = ev.get("node", "?")
        _flush_tokens()
        print(colour(f"[NODE <<] {node}", DIM))

    elif t == "done":
        _flush_tokens()
        print(colour(f"\n{'═'*60}\n[DONE] turn_id={ev.get('turn_id', '?')}\n{'═'*60}", BOLD, GREEN))

    elif t == "error":
        _flush_tokens()
        print(colour(
            f"\n[ERROR] {ev.get('error', '?')}\n{ev.get('traceback', '')}",
            RED, BOLD,
        ))

    else:
        # Unknown event — print raw for debugging
        print(colour(f"[?] {t}: {json.dumps(ev, ensure_ascii=False)[:120]}", DIM))


# ── SSE reader ────────────────────────────────────────────────────────────────

def stream_chat(
    url: str,
    message: str,
    active_smiles: str | None = None,
) -> None:
    payload = {
        "message": message,
        "session_id": uuid.uuid4().hex,
        "turn_id": uuid.uuid4().hex,
        "active_smiles": active_smiles,
    }

    print(colour(f"POST {url}", DIM))

    t0 = time.perf_counter()
    event_count = 0

    with requests.post(url, json=payload, stream=True, timeout=180) as resp:
        resp.raise_for_status()

        data_buf = ""
        for raw_line in resp.iter_lines(decode_unicode=True):
            if raw_line.startswith("data:"):
                data_buf = raw_line[len("data:"):].strip()
            elif raw_line == "" and data_buf:
                try:
                    ev = json.loads(data_buf)
                    handle_event(ev)
                    event_count += 1
                    if ev.get("type") in ("done", "error"):
                        break
                except json.JSONDecodeError as exc:
                    print(colour(f"[WARN] JSON parse error: {exc}  raw={data_buf[:80]}", YELLOW))
                finally:
                    data_buf = ""

    elapsed = time.perf_counter() - t0
    print(colour(
        f"\nTotal SSE events: {event_count}  |  Wall time: {elapsed:.2f}s",
        DIM,
    ))


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="ChemAgent SSE smoke test")
    parser.add_argument("message", nargs="?",
                        default="计算阿司匹林的 Lipinski 性质，SMILES 为 CC(=O)Oc1ccccc1C(=O)O",
                        help="User message to send")
    parser.add_argument("--url", default="http://localhost:8000/api/chat/stream",
                        help="SSE endpoint URL")
    parser.add_argument("--smiles", default=None,
                        help="Active SMILES for the canvas (pre-populates active_smiles in state)")
    args = parser.parse_args()

    try:
        stream_chat(args.url, args.message, active_smiles=args.smiles)
    except requests.exceptions.ConnectionError:
        print(colour(
            f"[ERROR] Could not connect to {args.url}\n"
            "Make sure the backend is running: uv run uvicorn app.main:app --reload",
            RED, BOLD,
        ))
        sys.exit(1)
    except KeyboardInterrupt:
        print(colour("\n[INTERRUPTED]", YELLOW))


if __name__ == "__main__":
    main()
