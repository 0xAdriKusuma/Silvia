# Silvia - Personal AI Assistant (Tahap Awal)

**Silvia** adalah personal AI assistant yang masih berada di **tahap awal pengembangan**. Silvia mengobrol lewat suara dengan avatar 3D yang berekspresi, bergerak, dan menggerakkan mulut mengikuti suaranya. Selain itu, Silvia bisa menjalankan aksi sederhana di komputer (membuka aplikasi dan website, memutar musik, mengelola file di folder sandbox) lewat modul agent yang berpengaman.

```text
Mic -> Silero VAD -> faster-whisper (STT) -> [Agent]* -> LLM Streaming -> TTS (SBV2 / Edge-TTS) -> Speaker / Web Audio
                                                |                                  |
                                       (aksi sistem & file)            tag emosi + animasi -> avatar VRM 3D
```
*\*Agent hanya aktif bila ucapan mengandung kata kunci aksi (mode `keyword`) atau diatur selalu aktif.*

> **Status:** prototipe tahap awal. Fitur dan struktur kode masih dapat berubah.

---

## Fitur

- **Percakapan suara**: Anda berbicara bahasa Indonesia, Silvia membalas dengan suara bahasa Jepang dan terjemahan Indonesia sebagai subtitle. Balasan LLM dikirim ke TTS kalimat demi kalimat agar jeda menjawab singkat.
- **Suara ekspresif**: Style-Bert-VITS2 lokal (model `jvnv-F2-jp`) yang menyesuaikan nada dengan emosi. Edge-TTS menjadi cadangan otomatis bila SBV2 gagal atau tidak tersedia.
- **Avatar 3D (VRM)** di browser: ekspresi wajah, animasi gerakan (VRMA) dengan transisi mulus, idle yang terus berputar, kedipan otomatis, dan lip-sync dari audio.
- **Agent (tool calling)**: buka aplikasi dan URL, putar musik (YouTube / YouTube Music, kontrol Spotify), serta buat, baca, daftar, dan hapus file di `agent/workspace/`.
- **Keamanan agent**: operasi file terkunci di sandbox, aksi berisiko wajib dikonfirmasi, dan setiap aksi dicatat di audit log.
- **STT akurat**: faster-whisper model `turbo` di GPU. Jika GPU tidak tersedia, otomatis ke CPU (int8) dengan model yang sama.
- **Dua mode**: Web (avatar 3D) dan Konsol (suara di terminal).

---

## Struktur Direktori

```text
silvia/
├── main.py              # Titik masuk (mode konsol & web)
├── .env                 # API key & pengaturan (jangan di-commit)
├── env.example          # Template .env
├── requirements.txt     # Dependensi (requirements-dev.txt untuk pengujian)
├── app/                 # Pipeline suara & server
│   ├── config.py        # Pengaturan (VAD, STT, LLM, TTS, emosi, animasi)
│   ├── mic.py           # Mikrofon + deteksi suara (Silero VAD)
│   ├── stt.py           # Transkripsi (faster-whisper)
│   ├── llm.py           # Klien LLM streaming (OpenAI-compatible)
│   ├── tts.py           # Orkestrator TTS, fallback Edge-TTS, normalisasi teks
│   ├── tts_sbv2.py      # Engine Style-Bert-VITS2 lokal + unduh model otomatis
│   ├── pipeline.py      # Alur paralel: LLM -> TTS -> output (+ integrasi agent)
│   ├── sinks.py         # Output audio (konsol & WebSocket)
│   ├── server.py        # Server FastAPI + WebSocket (mode web)
│   └── cuda_setup.py    # Deteksi DLL CUDA di Windows
├── agent/               # Modul agent
│   ├── config.py        # Allowlist aplikasi/ekstensi, kata kunci pemicu, batas
│   ├── core.py          # Loop agent (tool calling, konfirmasi)
│   ├── safety.py        # Guardrail (path aman, validasi URL)
│   ├── registry.py      # Registri alat (@tool)
│   ├── pending.py       # Aksi yang menunggu konfirmasi
│   ├── audit.py         # Audit log (JSON Lines)
│   ├── cli.py           # Uji agent lewat teks
│   ├── tools/           # apps, files, spotify, youtube
│   ├── workspace/       # Sandbox file pengguna
│   ├── logs/            # audit.jsonl
│   └── tests/           # Unit test
├── web/                 # Antarmuka avatar (three.js + three-vrm)
│   ├── index.html, main.js, style.css
│   └── js/              # animation, avatar, expressions, audio, scene, ui, websocket
├── prompts/persona.txt  # Kepribadian karakter
├── models/              # Cache model lokal (SBV2)
└── assets/              # Model VRM, animasi VRMA
```

---

## Instalasi

**Prasyarat:** Python 3.10+, mikrofon, dan headset (disarankan agar suara Silvia tidak terdengar kembali oleh mikrofon). Butuh internet untuk LLM via API. GPU NVIDIA bersifat opsional tetapi membuat STT dan SBV2 jauh lebih cepat.

```bash
python -m venv .venv
.\.venv\Scripts\activate        # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
```

**Untuk GPU (CUDA):**

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu121
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12   # jika muncul error cublas/cudnn
```
Jika GPU tidak tersedia atau gagal dimuat, STT otomatis beralih ke CPU (int8).

---

## Konfigurasi `.env`

```bash
Copy-Item env.example .env      # PowerShell  (Linux/macOS: cp env.example .env)
```

```ini
# --- LLM (persona & agent) ---
LLM_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxx
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL=openai/gpt-oss-120b      # alternatif lebih cepat: openai/gpt-oss-20b
LLM_REASONING_EFFORT=low           # hanya untuk model reasoning (GPT-OSS); kosongkan untuk model lain

# Alternatif: Gemini  -> LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
#                        LLM_MODEL=gemini-2.0-flash
# Alternatif: Ollama  -> LLM_BASE_URL=http://localhost:11434/v1  (LLM_API_KEY=ollama)

# --- Agent ---
AGENT_ENABLED=1                    # 1 = aktif, 0 = nonaktif
AGENT_TRIGGER_MODE=keyword         # "keyword" (hemat token) atau "always"

# --- TTS ---
TTS_BACKEND=auto                   # "auto" (SBV2, cadangan Edge), "sbv2", atau "edge"
SBV2_DEVICE=auto                   # "auto", "cuda", atau "cpu"
SBV2_TIMEOUT_S=4.0                 # batas waktu sintesis per kalimat (detik)

# --- STT ---
WHISPER_MODEL=turbo                # "turbo", "large-v3", "medium", atau "small"
WHISPER_COMPUTE_TYPE=int8_float16

# --- Spotify (opsional) ---
# SPOTIPY_CLIENT_ID=isi_client_id
# SPOTIPY_CLIENT_SECRET=isi_client_secret
# SPOTIPY_REDIRECT_URI=http://127.0.0.1:8888/callback
```
---

## Cara Menjalankan

**Mode Web (rekomendasi, avatar 3D + agent):**

```bash
python main.py --web
```
Buka **http://127.0.0.1:8000**. Browser memblokir audio sebelum ada interaksi, jadi klik halaman sekali bila suara belum terdengar.

**Mode Konsol (suara saja):**

```bash
python main.py
```

**Pengembangan:**

```bash
python -m agent.cli     # uji agent lewat teks, tanpa mic/TTS/avatar
python -m pytest        # jalankan unit test
```

---

## Menggunakan Agent

Minta langsung lewat suara atau kolom chat di web:

| Tujuan | Contoh ucapan |
|---|---|
| Buka aplikasi | "Buka Discord", "Buka Chrome", "Jalankan kalkulator" |
| Buka website | "Buka website https://github.com" |
| Musik YouTube | "Putar lagu Hikaru Nara Goose House", "Putar musik lofi di YouTube Music" |
| Spotify (butuh API Spotify) | "Putar spotify lagu Yoasobi Idol", "Jeda musik spotify", "Lagu berikutnya" |
| File di `agent/workspace/` | "Buat file belanja.txt isinya susu, telur, dan roti", "Bacakan isi file belanja", "Lihat daftar file", "Hapus file belanja" |

Aplikasi yang diizinkan (allowlist): Discord, Microsoft Word, Excel, Task Manager, Google Chrome, Notepad, Calculator, File Explorer, dan Spotify.

**Keamanan:**
- Operasi file hanya di `agent/workspace/`. Path traversal (`..`), path absolut, nama perangkat terlarang Windows, dan ekstensi berbahaya (`.exe`, `.bat`, `.ps1`, `.lnk`, dll.) ditolak.
- **Penghapusan file wajib dikonfirmasi.** Silvia menyebut nama file lengkap dan menunggu jawaban: "ya/iya/oke/silakan" melanjutkan (file dipindah ke Recycle Bin via `send2trash`), "tidak/batal/jangan" membatalkan, jawaban ambigu diminta ulang. Konfirmasi kedaluwarsa setelah 60 detik, dan perintah baru otomatis membatalkan permintaan lama.
- Isi file dan hasil alat diperlakukan sebagai data, bukan instruksi.
- Setiap aksi dicatat di `agent/logs/audit.jsonl`.

---

## Emosi dan Animasi

Silvia membalas satu kalimat per baris dengan dua tag di depannya:

```text
[emosi|animasi] kalimat Jepang|||terjemahan Indonesia
[shy|blush] そ、そんなこと言われたら照れちゃうよ…|||K-kalau dibilang begitu aku jadi malu...
[neutral|none] えっと、今日は何したの？|||Hmm, hari ini kamu ngapain aja?
```

- **Emosi** mengatur ekspresi wajah dan nada suara. **Animasi** adalah gerakan badan dari file `.vrma`; `none` berarti hanya idle.
- Bagian Jepang dibacakan TTS, bagian Indonesia tampil sebagai subtitle.
- Tag yang salah atau tidak dikenal diperlakukan aman (emosi jadi `neutral`, animasi diabaikan).
- `Idle.vrma` berputar terus sebagai lapisan dasar. Animasi lain masuk dan keluar dengan crossfade, jadi avatar tidak kembali ke T-pose di antara gerakan. Jika `Idle.vrma` tidak ditemukan, dipakai idle prosedural.

**Panel uji (mode Web):** tekan **`D`** untuk membuka panel berisi tombol tiap animasi dan emosi, uji beruntun, mode slow-mo 0.1×, dan HUD bobot animasi serta ekspresi.

**Menambah animasi:** letakkan file `.vrma` di `assets/`, lalu tambahkan satu entri di `ANIMATIONS` pada `app/config.py` (daftar emosi dan ekspresi juga ada di file itu).

---

## Catatan

- **Aset:** pastikan model VRM, animasi VRMA, dan suara yang dipakai adalah milik Anda atau berlisensi yang sesuai. Untuk dipublikasikan, gunakan karakter orisinal.
- **Lisensi model suara:** `jvnv-F2-jp` berlisensi CC BY-SA 4.0 (sumber: `litagin/style_bert_vits2_jvnv` di Hugging Face). Baca model card untuk ketentuan atribusi sebelum dipublikasikan.
- **Privasi:** audio mikrofon diproses di komputer Anda. Teks hasil transkripsi dikirim ke penyedia LLM yang Anda pilih, dan teks balasan dikirim ke Edge-TTS hanya saat cadangan itu dipakai.
