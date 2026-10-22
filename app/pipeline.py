"""
pipeline.py - Satu giliran: LLM streaming -> TTS -> Sink

respond() menerima sink (ConsoleSink atau WebSink) sebagai parameter,
sehingga perilaku output dapat diganti tanpa mengubah logika pipeline.
"""
import asyncio
import time
from openai import AsyncOpenAI
from app.config import (
    LLM_MODEL,
    LLM_REASONING_EFFORT,
    MAX_HISTORY_MESSAGES,
)
from app.llm import load_system_prompt
from app.tts import parse_line, synth, synth_clip, AudioClip
from app.sinks import BaseSink, ConsoleSink

# Import agent (opsional — dinonaktifkan jika modul tidak tersedia)
try:
    import agent as _agent
    _AGENT_AVAILABLE = True
except ImportError:
    _AGENT_AVAILABLE = False


async def respond(
    client: AsyncOpenAI,
    history: list,
    user_text: str,
    sink: BaseSink = None,
    on_line=None,
):
    """LLM streaming -> per baris ke TTS -> emit ke sink, semua berjalan paralel.
    
    Args:
        client    : AsyncOpenAI client
        history   : daftar pesan (dimodifikasi in-place)
        user_text : ucapan/teks pengguna
        sink      : output sink (default: ConsoleSink)
        on_line   : callback opsional on_line(emotion, anim, jp, idn) -- untuk kompatibilitas lama
    """
    t0 = time.perf_counter()
    if sink is None:
        sink = ConsoleSink()
        if hasattr(sink, "reset_timer"):
            sink.reset_timer()

    # ---- Panggil agent sebelum LLM persona ----
    extra_system_msg: str | None = None
    agent_result = None
    if _AGENT_AVAILABLE:
        try:
            # Callback status: kirim "thinking" ke sink saat agent bekerja
            async def _agent_status(state: str):
                await sink.set_status("thinking")

            # Ambil konfigurasi LLM dari config
            llm_kwargs = {}
            if LLM_REASONING_EFFORT:
                llm_kwargs["extra_body"] = {"reasoning_effort": LLM_REASONING_EFFORT}

            agent_result = await _agent.handle_turn(
                user_text=user_text,
                history=history,  # belum ditambah user_text
                client=client,
                model=LLM_MODEL,
                llm_kwargs=llm_kwargs or None,
                on_status=_agent_status,
            )

            if agent_result.handled:
                # Susun pesan fakta untuk persona
                extra_system_msg = (
                    "HASIL AKSI (fakta, jangan diubah/dikarang): "
                    + agent_result.message
                    + "\nSampaikan ke pengguna dengan gaya karakter."
                    " Jika ada nama file, sebut PERSIS seperti tertulis."
                    " Jika ini permintaan konfirmasi, tanyakan konfirmasi dengan jelas "
                    "dalam terjemahan Indonesia di bagian |||."
                )
        except Exception as _e:
            print(f"[AGENT] Error: {_e}")
            # Jangan hentikan pipeline jika agent error

    # ---- Susun pesan untuk LLM persona ----
    system_prompt = load_system_prompt()
    history.append({"role": "user", "content": user_text})

    # Pesan sistem: persona + konteks + (opsional) fakta aksi
    system_content = system_prompt
    if extra_system_msg:
        system_content = system_prompt + "\n\n[KONTEKS AKSI]\n" + extra_system_msg

    messages = [{"role": "system", "content": system_content}] + history[-MAX_HISTORY_MESSAGES:]

    line_q: asyncio.Queue = asyncio.Queue()
    audio_q: asyncio.Queue = asyncio.Queue()
    reply_lines: list[str] = []

    async def llm_producer():
        """Mengonsumsi streaming LLM dan memasukkan baris ke line_q."""
        buf = ""
        try:
            kwargs = dict(
                model=LLM_MODEL,
                messages=messages,
                stream=True,
                temperature=0.8,
                max_tokens=500,
            )
            if LLM_REASONING_EFFORT:
                kwargs["extra_body"] = {"reasoning_effort": LLM_REASONING_EFFORT}
            stream = await client.chat.completions.create(**kwargs)
            first_token = True
            async for ev in stream:
                if not ev.choices:
                    continue
                delta = ev.choices[0].delta.content or ""
                if not delta:
                    continue
                if first_token:
                    print(f"[LLM] token pertama: {time.perf_counter() - t0:.2f} dtk")
                    first_token = False
                buf += delta
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    if line.strip():
                        reply_lines.append(line.strip())
                        await line_q.put(line.strip())
            if buf.strip():
                reply_lines.append(buf.strip())
                await line_q.put(buf.strip())
        finally:
            await line_q.put(None)

    async def tts_worker():
        """Ambil baris dari line_q, sintesis audio (AudioClip), kirim ke audio_q."""
        try:
            while True:
                line = await line_q.get()
                if line is None:
                    break
                emotion, animation, jp, idn = parse_line(line)
                if not jp:
                    continue
                clip = await synth_clip(jp, emotion)
                await audio_q.put((emotion, animation, jp, idn, clip))
        finally:
            await audio_q.put(None)

    async def player():
        """Emit setiap baris ke sink secara berurutan."""
        first = True
        while True:
            item = await audio_q.get()
            if item is None:
                break
            emotion, animation, jp, idn, clip = item
            if first:
                print(f"[TOTAL] suara pertama keluar setelah {time.perf_counter() - t0:.2f} dtk")
                first = False
            # Callback kompatibilitas lama (opsional)
            if on_line:
                on_line(emotion, animation, jp, idn)
            # Kirim ke sink (console: cetak+putar; web: broadcast JSON)
            await sink.emit_line(emotion, animation, jp, idn, clip)

    await sink.set_status("thinking")
    await asyncio.gather(llm_producer(), tts_worker(), player())
    await sink.end_turn()

    history.append({"role": "assistant", "content": "\n".join(reply_lines)})
