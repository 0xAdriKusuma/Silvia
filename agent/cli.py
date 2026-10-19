"""
agent/cli.py - Antarmuka teks untuk uji manual agent

Jalankan: python -m agent.cli
Membuat klien LLM sendiri dari .env via python-dotenv.
Tidak membutuhkan komponen suara/TTS/pipeline.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Tambahkan root proyek ke sys.path agar import agent/* berfungsi
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Muat .env sebelum import lain
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from openai import AsyncOpenAI

from agent import handle_turn, AgentResult
from agent.config import (
    AGENT_ENABLED,
    WORKSPACE_DIR,
)


def _print_result(result: AgentResult) -> None:
    """Tampilkan AgentResult ke konsol dengan format yang mudah dibaca."""
    print()
    if not result.handled:
        print("  [agent] Tidak ditangani agent (percakapan biasa).")
        return

    if result.needs_confirmation:
        print(f"  [KONFIRMASI DIPERLUKAN] {result.message}")
    else:
        print(f"  [HASIL] {result.message}")

    if result.actions:
        print("  [Aksi yang dijalankan]:")
        for act in result.actions:
            status_icon = "✓" if act.get("status") == "ok" else "✗"
            print(f"    {status_icon} {act['name']}({act.get('args', {})})")
            if "result" in act and act["result"]:
                preview = str(act["result"])[:200]
                print(f"       -> {preview}")


async def _on_status(state: str) -> None:
    """Tampilkan status working ke konsol."""
    print(f"  [agent] {state}...")


async def main():
    """Loop percakapan teks untuk pengujian agent."""
    api_key = os.getenv("LLM_API_KEY", "")
    base_url = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    model = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
    reasoning_effort = os.getenv("LLM_REASONING_EFFORT", "")

    if not api_key:
        print("[ERROR] LLM_API_KEY belum diisi di .env")
        sys.exit(1)

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    llm_kwargs = {}
    if reasoning_effort:
        llm_kwargs["extra_body"] = {"reasoning_effort": reasoning_effort}

    if not AGENT_ENABLED:
        print("[PERINGATAN] AGENT_ENABLED=0 di .env — agent dinonaktifkan.")

    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print(" Agent CLI Silvia — Uji Manual")
    print(f" Workspace: {WORKSPACE_DIR}")
    print(f" Model: {model}")
    print(" Ketik 'keluar' atau Ctrl+C untuk berhenti.")
    print("=" * 60)
    print()

    history: list = []

    while True:
        try:
            user_input = input("Kamu: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSampai jumpa!")
            break

        if not user_input:
            continue

        if user_input.lower() in ("keluar", "exit", "quit"):
            print("Sampai jumpa!")
            break

        result = await handle_turn(
            user_text=user_input,
            history=history,
            client=client,
            model=model,
            llm_kwargs=llm_kwargs or None,
            on_status=_on_status,
        )

        _print_result(result)

        # Tambahkan ke riwayat (jika handled, catat sebagai asisten)
        history.append({"role": "user", "content": user_input})
        if result.handled and result.message:
            history.append({"role": "assistant", "content": result.message})

        print()


if __name__ == "__main__":
    asyncio.run(main())
