"""
Quick smoke test — sends a real chemistry query and prints all events + elapsed time.
Usage:  python smoke_test.py
"""
import asyncio
import json
import time
import sys

import websockets


WS_URL = "ws://localhost:3030/api/chat/ws"
QUERY = "调研一下阿奇霉素：SMILES结构、Lipinski五规则分析、Murcko骨架"

# ANSI colours
GREY   = "\033[90m"
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


async def run():
    start = time.perf_counter()
    print(f"\n{BOLD}{'─'*60}{RESET}")
    print(f"{BOLD}Query:{RESET} {QUERY}")
    print(f"{BOLD}{'─'*60}{RESET}\n")

    async with websockets.connect(WS_URL) as ws:
        # 1. Handshake: send session.start first (server waits for this)
        await ws.send(json.dumps({"type": "session.start"}))

        # 2. Receive session.started
        raw = await ws.recv()
        evt = json.loads(raw)
        session_id = evt.get("session_id", "")
        print(f"{GREY}[{elapsed(start):.1f}s] {evt['type']}  session_id={session_id}{RESET}")

        # 3. Drain static greeting (run.started → assistant.message → run.finished)
        async for raw in ws:
            greeting_evt = json.loads(raw)
            gt = greeting_evt.get("type", "")
            if gt == "assistant.message":
                msg = greeting_evt.get("message", "")
                print(f"{GREY}[{elapsed(start):.1f}s] 👋 {msg}{RESET}")
            elif gt == "run.finished":
                print(f"{GREY}[{elapsed(start):.1f}s] greeting done{RESET}")
                break
            else:
                print(f"{GREY}[{elapsed(start):.1f}s] greeting: {gt}{RESET}")

        # 4. Enable auto_approve so we don't need manual plan.approve
        await ws.send(json.dumps({
            "type": "settings.update",
            "settings": {"auto_approve": True},
        }))
        # drain settings.updated ack
        raw = await ws.recv()
        print(f"{GREY}[{elapsed(start):.1f}s] {json.loads(raw).get('type')}: auto_approve=True{RESET}")

        # 5. Send the chemistry query
        await ws.send(json.dumps({
            "type": "user.message",
            "content": QUERY,
            "session_id": session_id,
        }))
        print(f"{CYAN}[sent]{RESET} {QUERY}\n")

        # 3. Stream events until run.finished or run.failed
        # NOTE: to_wire() spreads payload flat into the top-level dict.
        # So evt["tool"]["name"], evt["plan"], evt["summary"] etc. are at root.
        _stream_buf = ""
        async for raw in ws:
            evt = json.loads(raw)
            t = evt.get("type", "?")
            ts = elapsed(start)

            if t == "assistant.delta":
                # streaming token — accumulate + print inline
                token = evt.get("content", "")
                _stream_buf += token
                print(token, end="", flush=True)

            elif t == "plan.proposed":
                if _stream_buf:
                    print()
                    _stream_buf = ""
                plan = evt.get("plan", "")
                print(f"\n{YELLOW}[{ts:.1f}s] 📋 plan.proposed:{RESET}")
                for line in plan.splitlines():
                    print(f"  {line}")

            elif t == "plan.status":
                status = evt.get("status", "")
                print(f"\n{YELLOW}[{ts:.1f}s] plan.status → {status}{RESET}")

            elif t == "todo.progress":
                if _stream_buf:
                    print()
                    _stream_buf = ""
                todo = evt.get("todo", "").strip()
                # show first 3 lines of todo
                lines = todo.splitlines()[:4]
                print(f"\n{CYAN}[{ts:.1f}s] 📝 todo:{RESET}")
                for line in lines:
                    print(f"  {line}")

            elif t == "tool.call":
                if _stream_buf:
                    print()
                    _stream_buf = ""
                name = evt.get("tool", {}).get("name", "?")
                args = json.dumps(evt.get("arguments", {}), ensure_ascii=False)[:120]
                print(f"\n{CYAN}[{ts:.1f}s] 🔧 {name}({args}){RESET}")

            elif t == "tool.result":
                name = evt.get("tool", {}).get("name", "?")
                status = evt.get("status", "")
                summary = evt.get("summary", "")[:120]
                colour = GREEN if status == "success" else RED
                print(f"{colour}[{ts:.1f}s]  ↳ {name} → {status}  {summary}{RESET}")

            elif t == "assistant.message":
                if _stream_buf:
                    print()
                    _stream_buf = ""
                msg = evt.get("message", "")[:200]
                sender = evt.get("sender", "")
                print(f"\n{GREY}[{ts:.1f}s] 💬 {sender}: {msg}{RESET}")

            elif t == "thinking.delta":
                print(f"\033[90m{evt.get('content','')}\033[0m", end="", flush=True)

            elif t == "run.finished":
                if _stream_buf:
                    print()
                    _stream_buf = ""
                summary = evt.get("summary", "")
                print(f"\n\n{GREEN}{BOLD}{'─'*60}{RESET}")
                print(f"{GREEN}{BOLD}✅ run.finished  [{ts:.1f}s total]{RESET}")
                print(f"{GREEN}{BOLD}{'─'*60}{RESET}")
                if summary:
                    print(summary[:800])
                break

            elif t == "run.failed":
                if _stream_buf:
                    print()
                    _stream_buf = ""
                print(f"\n{RED}{BOLD}[{ts:.1f}s] ❌ run.failed: {evt}{RESET}")
                break

            elif t in ("ping", "turn.status", "run.started", "review.status"):
                # suppress noisy routine events
                pass

            else:
                print(f"\n{GREY}[{ts:.1f}s] {t}{RESET}", end="")

    total = elapsed(start)
    print(f"\n\n{BOLD}Total wall time: {total:.1f}s{RESET}\n")


def elapsed(start: float) -> float:
    return time.perf_counter() - start


if __name__ == "__main__":
    asyncio.run(run())
