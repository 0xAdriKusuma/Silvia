# Silvia - Personal AI Assistant

**Silvia** adalah personal AI assistant interaktif berbasis suara dengan avatar 3D yang bisa berekspresi, bergerak, dan menggerakkan mulut mengikuti suaranya. Selain percakapan suara alami, Silvia kini dilengkapi dengan **Modul Agent (Tool Calling)** berpengaman ketat untuk menjalankan aksi nyata di komputer pengguna (membuka aplikasi, mengelola file di workspace, membuka web).

Alur kerja intinya:

```text
Mic -> Silero VAD -> faster-whisper (STT) -> [Agent Tool Calling]* -> LLM Streaming -> Edge-TTS -> Web Audio API / Speaker
                                                   |                                       |
                                         (aksi sistem & file)               tag emosi + animasi -> avatar VRM 3D
```
*\*Agent hanya aktif jika ucapan mengandung kata kunci aksi (mode keyword) atau dikonfigurasi selalu aktif.*

> **Status:** prototipe aktif dengan kemampuan tool calling mandiri dan teruji.

---

## Fitur Saat Ini

- **Percakapan suara dua arah**: Anda berbicara dalam bahasa Indonesia, Silvia membalas dengan suara bahasa Jepang beserta terjemahan Indonesia sebagai subtitle.
- **Kemampuan Agent (Tool Calling)**:
  - **Membuka aplikasi**: Membuka program dari allowlist aman (Notepad, Calculator, Paint, File Explorer, Task Manager, VS Code, Browser, Spotify, Discord, dll.).
  - **Membuka URL**: Membuka link web terverifikasi (`http://` dan `https://`) di browser default.
  - **Operasi file sandboxed**: Membuat file baru, membaca file, mendaftar isi folder, dan menghapus file dengan aman di dalam folder `agent/workspace/`.
- **Keamanan & Guardrails Ketat**:
  - **Sandboxing Workspace**: Operasi file terkunci rapat di `agent/workspace/`. Menolak *path traversal* (`..`), path absolut Windows/Unix, drive letters, UNC, device names terlarang Windows (`CON`, `NUL`, dll.), serta ekstensi file berbahaya (`.exe`, `.bat`, `.ps1`, `.lnk`, dll.).
  - **Konfirmasi Aksi Destruktif**: Operasi berisiko seperti penghapusan file (`delete_file`) **wajib dikonfirmasi** terlebih dahulu oleh pengguna sebelum dieksekusi.
  - **Recycle Bin**: Penghapusan file menggunakan `send2trash` (tidak langsung dihapus permanen dan tanpa fallback berbahaya).
  - **Pencegahan Prompt Injection**: Konten file dan data alat diperlakukan murni sebagai data, bukan instruksi yang bisa dieksekusi oleh model persona.
  - **Audit Logging**: Setiap aksi, argumen, status eksekusi, dan keputusan konfirmasi dicatat dalam format JSON Lines di `agent/logs/audit.jsonl`.
- **Respons streaming per kalimat**: Balasan LLM langsung dikirim ke TTS kalimat demi kalimat agar jeda menjawab singkat.
- **Avatar 3D (VRM)** di browser dengan ekspresi wajah, animasi badan (VRMA), sinkronisasi gerak mulut (*lip-sync*), dan subtitle.
- **Dua mode penggunaan**: Web (avatar 3D interaktif) dan Konsol (suara terminal).
- **Fallback otomatis**: Jika GPU tidak tersedia, STT Whisper otomatis berjalan di CPU (int8).

---

## Struktur Direktori

```text
silvia/
├── main.py              # Titik masuk utama (mode console & web)
├── .env                 # File environment & API Key (jangan di-commit ke Git)
├── env.example          # Template konfigurasi environment
├── requirements.txt     # Daftar dependensi utama
├── requirements-dev.txt # Dependensi pengujian (pytest, pytest-asyncio)
├── pytest.ini           # Konfigurasi pengujian pytest
├── .gitignore           # Aturan pengabaian file Git
├── README.md            # Dokumentasi proyek
├── agent/               # Modul Agent (Tool Calling & Keamanan)
│   ├── __init__.py
│   ├── config.py        # Pengaturan agent (allowlist app/ekstensi, trigger keywords, batas keamanan)
│   ├── core.py          # Loop eksekusi agent (LLM tool-use, konfirmasi, penanganan respons)
│   ├── safety.py        # Guardrails (safe_path, resolve_name, validasi URL, filter trigger)
│   ├── pending.py       # Manajemen pending actions & kadaluarsa konfirmasi
│   ├── registry.py      # Registri alat (@tool decorator, skema OpenAPI, validasi argumen)
│   ├── audit.py         # Pencatat audit log JSONL
│   ├── cli.py           # CLI mandiri untuk uji coba teks modul agent
│   ├── prompts/
│   │   └── agent_rules.txt # Aturan keamanan sistem agent
│   ├── tools/           # Definisi alat
│   │   ├── apps.py      # open_app, open_url
│   │   └── files.py     # create_file, read_file, list_files, delete_file
│   ├── workspace/       # Folder sandbox untuk file pengguna
│   ├── logs/            # Folder log audit (audit.jsonl)
│   └── tests/           # Suite unit test lengkap (test_safety, test_tools, test_confirm, test_core)
├── app/                 # Pipeline Percakapan Suara & Avatar
│   ├── __init__.py
│   ├── config.py        # Pengaturan (VAD, STT, LLM, TTS, emosi, animasi)
│   ├── cuda_setup.py    # Auto-detection path DLL CUDA di Windows
│   ├── llm.py           # Klien LLM streaming OpenAI-compatible
│   ├── mic.py           # Perekaman mic + deteksi suara (Silero VAD)
│   ├── pipeline.py      # Pipeline paralel: LLM -> TTS -> Audio Sink + Integrasi Agent
│   ├── server.py        # Server FastAPI + WebSocket untuk mode Web
│   ├── sinks.py         # Abstraksi audio output (ConsoleSink & WebSink)
│   ├── stt.py           # Transkripsi suara via faster-whisper
│   └── tts.py           # Sintesis suara via Edge-TTS & pemutar audio
├── assets/              # Model avatar 3D (.vrm), animasi (.vrma), dan background
├── prompts/
│   └── persona.txt      # Prompt karakter & kepribadian Silvia
└── web/                 # Antarmuka web (three.js, three-vrm, HTML/CSS/JS)
```

---

## Persiapan dan Instalasi

### 1. Prasyarat
- Python 3.10+ (disarankan memakai virtual environment)
- Mikrofon dan speaker / headset (**disarankan headset** agar suara Silvia tidak masuk lagi ke mikrofon)
- Koneksi internet (untuk LLM via API dan Edge-TTS)
- GPU NVIDIA (opsional, untuk Whisper yang lebih cepat dengan CUDA)

### 2. Buat Virtual Environment & Pasang Dependensi

```bash
# Buat dan aktifkan virtual environment
python -m venv .venv
.\.venv\Scripts\activate   # Windows
# source .venv/bin/activate # Linux / macOS

# Install dependensi utama
pip install -r requirements.txt
```

> **Catatan untuk Akselerasi GPU (CUDA):**
> Jika ingin memakai GPU untuk `Silero VAD` & `faster-whisper`:
> ```bash
> # Pasang PyTorch CUDA (contoh cu121):
> pip install torch --index-url https://download.pytorch.org/whl/cu121
>
> # Pasang library cuBLAS & cuDNN jika diperlukan:
> pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
> ```
> *Jika GPU tidak tersedia atau gagal dimuat, sistem otomatis beralih ke mode CPU (int8).*

---

## Konfigurasi `.env`

Salin file `env.example` ke `.env`:

```bash
cp env.example .env      # Linux/macOS
# atau di Windows PowerShell:
Copy-Item env.example .env
```

Buka `.env` dan sesuaikan konfigurasinya:

```ini
# --- Penyedia LLM Persona & Agent ---
# Opsi 1: Groq (sangat cepat & ada kuota gratis)
LLM_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxx
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL=openai/gpt-oss-120b
# Model alternatif: llama-3.3-70b-versatile atau openai/gpt-oss-20b
LLM_REASONING_EFFORT=low

# Opsi 2: Google Gemini (OpenAI-compatible)
# LLM_API_KEY=AIzaxxxxxxxxxxxxxxxxxx
# LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
# LLM_MODEL=gemini-2.0-flash
# LLM_REASONING_EFFORT=

# Opsi 3: Ollama lokal (tanpa internet untuk LLM)
# LLM_API_KEY=ollama
# LLM_BASE_URL=http://localhost:11434/v1
# LLM_MODEL=qwen2.5:3b
# LLM_REASONING_EFFORT=

# --- Konfigurasi Modul Agent (Tool Calling) ---
AGENT_ENABLED=1             # 1 = aktif (default), 0 = nonaktif
AGENT_TRIGGER_MODE=keyword  # "keyword" (hemat biaya/token) atau "always" (selalu cek tool)
```

> [!NOTE]
> Nama model di penyedia API sering berganti atau dihentikan. Jika muncul error `model_not_found` (404), cek daftar model terbaru di dashboard penyedia lalu ubah `LLM_MODEL`. `LLM_REASONING_EFFORT=low` hanya untuk model *reasoning* seperti GPT-OSS; kosongkan untuk model lain.

> [!IMPORTANT]
> Jangan unggah `.env` ke publik/GitHub karena berisi API Key rahasia Anda. File ini sudah ditambahkan ke [.gitignore](.gitignore).

---

## Cara Menjalankan

### 1. Mode Web (Rekomendasi - Avatar 3D VRM + Agent)
Menjalankan server FastAPI lokal sekaligus antarmuka avatar interaktif di browser:

```bash
python main.py --web
```
Setelah server berjalan, buka browser di:
**[http://127.0.0.1:8000](http://127.0.0.1:8000)**

> *Browser memblokir pemutaran audio sebelum ada interaksi. Klik area halaman sekali jika suara belum terdengar.*

### 2. Mode Konsol (Terminal Suara Only)
Menjalankan percakapan suara interaktif langsung di terminal:

```bash
python main.py
```
*Gunakan headset saat berbicara agar audio speaker tidak masuk kembali ke mikrofon.*

### 3. Uji Manual Modul Agent via Teks (CLI Tester)
Menguji kemampuan agent secara mandiri melalui teks terminal tanpa perlu mic/TTS/avatar:

```bash
python -m agent.cli
```

### 4. Menjalankan Unit Test (Pytest)
Memverifikasi fungsionalitas dan keamanan seluruh modul agent:

```bash
python -m pytest
```

---

## Menggunakan Kemampuan Agent

Anda dapat meminta Silvia menjalankan tugas langsung lewat ucapan suara atau kolom chat web:

### 1. Membuka Aplikasi & Website
- *"Silvia, tolong bukakan notepad"* -> Membuka aplikasi Notepad.
- *"Jalankan kalkulator dong"* -> Membuka Calculator.
- *"Buka spotify"* -> Membuka Spotify.
- *"Buka website https://github.com"* -> Membuka link di browser default.

### 2. Operasi File di Sandbox (`agent/workspace/`)
Semua operasi file dibatasi secara ketat hanya di dalam folder `agent/workspace/`:
- **Membuat file**: *"Silvia, buat file belanja.txt isinya susu, telur, dan roti"*
- **Membaca file**: *"Tolong bacakan isi file belanja"* (Silvia otomatis mendeteksi nama file stem tanpa ekstensi).
- **Melihat isi folder**: *"Lihat daftar file"* atau *"Tampilkan semua file di workspace"*
- **Menghapus file**: *"Hapus file belanja"*

### 3. Alur Konfirmasi Aksi Berisiko (Safety Guardrail)
Saat Anda meminta menghapus file:
1. Silvia tidak akan langsung menghapus file, melainkan meminta konfirmasi:
   > *"Apakah kamu yakin ingin menghapus 'belanja.txt'? Katakan 'ya' untuk lanjut atau 'tidak' untuk batal."*
2. Jawab dengan tegas:
   - **Afirmatif**: *"Ya"*, *"Iya"*, *"Oke"*, *"Silakan"* -> File dipindahkan ke Recycle Bin (`send2trash`).
   - **Negatif**: *"Tidak"*, *"Batal"*, *"Jangan"* -> Aksi dibatalkan.
   - **Ambigu**: *"Mungkin saja"* -> Silvia akan meminta penegasan ulang.
   - **Kadaluarsa**: Jika tidak dijawab dalam 60 detik (default), konfirmasi otomatis dibatalkan.
   - **Instruksi Baru**: Jika Anda langsung memberi perintah baru (mis. *"buka paint"*), permintaan hapus lama otomatis dibatalkan dan perintah baru diproses.

---

## Cara Kerja Emosi dan Animasi

Silvia membalas dalam format satu kalimat per baris dengan dua tag di depannya:

```text
[emosi|animasi] kalimat Jepang|||terjemahan Indonesia
```

Contoh:

```text
[shy|blush] そ、そんなこと言われたら照れちゃうよ…|||K-kalau dibilang begitu aku jadi malu...
[neutral|none] えっと、今日は何したの？|||Hmm, hari ini kamu ngapain aja?
```

- **Emosi** mengatur ekspresi wajah dan nada suara (kecepatan dan tinggi nada TTS).
- **Animasi** adalah gerakan badan dari file `.vrma`. Nilai `none` berarti tidak ada gerakan khusus.
- Bagian Jepang dibacakan TTS, bagian Indonesia hanya tampil sebagai subtitle.
- Tag yang salah atau tidak dikenal diperlakukan aman: emosi menjadi `neutral`, animasi diabaikan.

Daftar emosi dan animasi ada di `app/config.py` (`EMOTION_PROSODY` dan `ANIMATIONS`) dan otomatis dimasukkan ke prompt. Untuk menambah animasi baru: letakkan file `.vrma` di `assets/`, lalu tambahkan satu entri di `ANIMATIONS`.

---

## Pengaturan yang Sering Diubah

| Yang ingin diubah | Lokasi |
|---|---|
| Kepribadian dan gaya bicara karakter | `prompts/persona.txt` |
| Aturan & batasan sistem modul agent | `agent/prompts/agent_rules.txt` |
| Daftar aplikasi yang boleh dibuka | `APP_ALLOWLIST` di `agent/config.py` |
| Ekstensi file yang diizinkan | `ALLOWED_EXTENSIONS` di `agent/config.py` |
| Kata kunci pemicu agent (mode keyword) | `TRIGGER_KEYWORDS` di `agent/config.py` |
| Waktu kadaluarsa konfirmasi hapus | `CONFIRM_EXPIRY_SECONDS` di `agent/config.py` |
| Batas karakter pembacaan file | `TOOL_RESULT_MAX_CHARS` di `agent/config.py` |
| Nama karakter | `CHARACTER_NAME` di `app/config.py` |
| Kecepatan dan nada suara per emosi | `EMOTION_PROSODY` di `app/config.py` |
| Daftar animasi dan kapan dipakai | `ANIMATIONS` di `app/config.py` |
| Bahasa bicara pengguna (STT) | `STT_LANG` di `app/config.py` (`"id"` atau `"ja"`) |
| Ukuran model Whisper | `WHISPER_MODEL` di `app/config.py` |
| Kepekaan deteksi suara | `VAD_THRESHOLD`, `END_SILENCE_MS` di `app/config.py` |
| Suara TTS | `TTS_VOICE` di `app/config.py` |

---

## Rencana Pengembangan

Silvia akan dikembangkan bertahap. Berikut arah yang direncanakan:

- [x] Percakapan suara di konsol
- [x] Avatar 3D di browser dengan ekspresi, animasi, dan lip-sync
- [x] Modul Agent (Tool Calling): membuka aplikasi, membuka URL, dan operasi file sandboxed
- [x] Sistem keamanan agent: sandbox workspace, alur konfirmasi aksi destruktif, dan audit logging
- [ ] Ingatan percakapan jangka panjang (memori kontekstual)
- [ ] Menyela Silvia saat ia sedang berbicara (*voice interruption*)
- [ ] Kemampuan asisten harian tambahan (kalender, integrasi alarm/pengingat waktu)
- [ ] TTS yang lebih ekspresif
- [ ] Opsi deployment sepenuhnya lokal (tanpa API eksternal)

---

## Catatan

- **Aset:** Pastikan model VRM, animasi VRMA, dan suara yang dipakai adalah milik Anda atau berlisensi yang sesuai. Untuk dipublikasikan, gunakan karakter orisinal.
- **Privasi:** Audio mikrofon diproses secara lokal di komputer Anda. Teks hasil transkripsi dikirim ke penyedia LLM yang Anda pilih, dan teks balasan dikirim ke layanan Edge-TTS (membutuhkan internet).

