# Silvia - Personal AI Assistant (Tahap Awal)

**Silvia** adalah personal AI assistant yang masih berada di **tahap awal pengembangan**. Saat ini Silvia berfokus pada satu kemampuan inti: **mengobrol lewat suara** dengan wujud avatar 3D yang bisa berekspresi, bergerak, dan menggerakkan mulut mengikuti suaranya. Fitur asisten yang lebih luas (ingatan jangka panjang, bantuan tugas harian, dan sebagainya) akan ditambahkan bertahap.

Alur kerja intinya:

```text
Mic -> Silero VAD -> faster-whisper (STT) -> LLM Streaming -> Edge-TTS -> Web Audio API / Speaker
                                                  |
                                      tag emosi + animasi -> avatar VRM 3D
```

> **Status:** prototipe aktif. Fitur dan struktur kode masih dapat berubah.

---

## Fitur Saat Ini

- **Percakapan suara dua arah**: Anda berbicara dalam bahasa Indonesia, Silvia membalas dengan suara bahasa Jepang beserta terjemahan Indonesia sebagai subtitle.
- **Respons streaming per kalimat**: balasan LLM langsung dikirim ke TTS kalimat demi kalimat agar jeda menjawab singkat.
- **Avatar 3D (VRM)** di browser dengan:
  - ekspresi wajah sesuai emosi,
  - animasi gerakan badan (VRMA) sesuai konteks percakapan,
  - sinkronisasi gerak mulut dengan audio,
  - transkrip dan subtitle langsung.
- **Dua mode**: Web (avatar 3D) dan Konsol (suara saja).
- **Fallback otomatis**: jika GPU tidak tersedia, Whisper berjalan di CPU (int8).

---

## Struktur Direktori

```text
silvia/
├── main.py              # Titik masuk utama (console & web)
├── .env                 # File environment & API Key (jangan di-commit ke Git)
├── env.example          # Template konfigurasi environment
├── requirements.txt     # Daftar dependensi Python
├── .gitignore           # Aturan pengabaian file Git
├── README.md            # Dokumentasi proyek
├── app/
│   ├── __init__.py
│   ├── config.py        # Pengaturan (VAD, STT, LLM, TTS, emosi, animasi)
│   ├── cuda_setup.py    # Auto-detection path DLL CUDA di Windows
│   ├── llm.py           # Klien LLM streaming OpenAI-compatible
│   ├── mic.py           # Perekaman mic + deteksi suara (Silero VAD)
│   ├── pipeline.py      # Pipeline paralel: LLM -> TTS -> Audio Sink
│   ├── server.py        # Server FastAPI + WebSocket untuk mode Web
│   ├── sinks.py         # Abstraksi audio output (ConsoleSink & WebSocketSink)
│   ├── stt.py           # Transkripsi suara via faster-whisper
│   └── tts.py           # Sintesis suara via Edge-TTS & pemutar audio
├── assets/              # Model avatar 3D (.vrm), animasi (.vrma), dan background
├── prompts/
│   └── persona.txt      # Prompt karakter & instruksi kepribadian Silvia
├── server/              # Modul pelengkap server
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
# Opsi 1: Groq (cepat & ada kuota gratis)
LLM_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxx
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL=openai/gpt-oss-120b
# Alternatif lebih cepat tapi kurang pintar: openai/gpt-oss-20b
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
```

> [!NOTE]
> Nama model di penyedia API sering berganti atau dihentikan. Jika muncul error `model_not_found` (404), cek daftar model terbaru di dashboard penyedia lalu ubah `LLM_MODEL`. `LLM_REASONING_EFFORT=low` hanya untuk model *reasoning* seperti GPT-OSS; kosongkan untuk model lain.

> [!IMPORTANT]
> Jangan unggah `.env` ke publik/GitHub karena berisi API Key rahasia Anda. File ini sudah ditambahkan ke [.gitignore](.gitignore).

---

## Cara Menjalankan

### Mode Web (Rekomendasi - Avatar 3D VRM)
Menjalankan server FastAPI lokal sekaligus antarmuka avatar interaktif:

```bash
python main.py --web
```
Setelah server berjalan, buka browser di:
**[http://127.0.0.1:8000](http://127.0.0.1:8000)**

> Browser memblokir pemutaran audio sebelum ada interaksi. Jika suara tidak keluar, klik halaman sekali lalu coba lagi.

### Mode Konsol (Terminal Only)
Menjalankan percakapan audio langsung di terminal:

```bash
python main.py
```
*Gunakan headset saat berbicara agar audio keluaran speaker tidak masuk kembali ke mikrofon.*

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

Daftar emosi dan animasi, beserta petunjuk kapan masing-masing dipakai, ada di `app/config.py` (`EMOTION_PROSODY` dan `ANIMATIONS`) dan otomatis dimasukkan ke prompt. Untuk menambah animasi baru: letakkan file `.vrma` di `assets/`, lalu tambahkan satu entri di `ANIMATIONS`.

---

## Pengaturan yang Sering Diubah

| Yang ingin diubah | Lokasi |
|---|---|
| Kepribadian dan gaya bicara karakter | `prompts/persona.txt` |
| Nama karakter | `CHARACTER_NAME` di `app/config.py` |
| Kecepatan dan nada suara per emosi | `EMOTION_PROSODY` di `app/config.py` |
| Daftar animasi dan kapan dipakai | `ANIMATIONS` di `app/config.py` |
| Bahasa bicara pengguna (STT) | `STT_LANG` di `app/config.py` (`"id"` atau `"ja"`) |
| Ukuran model Whisper | `WHISPER_MODEL` di `app/config.py` |
| Kepekaan deteksi suara | `VAD_THRESHOLD`, `END_SILENCE_MS` di `app/config.py` |
| Suara TTS | `TTS_VOICE` di `app/config.py` |

---

## Pemecahan Masalah

| Gejala | Penyebab dan solusi |
|---|---|
| `model_not_found` / error 404 dari LLM | Model sudah dihentikan atau salah nama. Ubah `LLM_MODEL` di `.env`, lalu jalankan ulang. |
| `Library cublas64_12.dll is not found` | Pasang `nvidia-cublas-cu12 nvidia-cudnn-cu12`. Sementara itu Whisper otomatis memakai CPU. |
| Ada teks aneh padahal tidak berbicara | Halusinasi Whisper dari noise. Naikkan `VAD_THRESHOLD` (mis. 0.6) dan `MIN_SPEECH_MS` (mis. 600). |
| Ucapan sering terpotong | Naikkan `END_SILENCE_MS`. |
| Silvia menjawab suaranya sendiri | Pakai headset. |
| Port 8000 sudah dipakai | Tutup program lain yang memakai port itu, atau ubah port server. |
| Perubahan `.env` tidak berpengaruh | Jalankan ulang program; `.env` hanya dibaca saat start. |

---

## Rencana Pengembangan

Silvia akan dikembangkan bertahap. Berikut arah yang direncanakan (belum final):

- [x] Percakapan suara di konsol
- [x] Avatar 3D di browser dengan ekspresi, animasi, dan lip-sync
- [ ] Ingatan percakapan jangka panjang
- [ ] Menyela Silvia saat ia sedang berbicara
- [ ] Kemampuan asisten harian (catatan, pengingat, dan sejenisnya)
- [ ] TTS yang lebih natural dan ekspresif
- [ ] Opsi sepenuhnya lokal (tanpa API eksternal)

---

## Catatan

- **Aset:** pastikan model VRM, animasi VRMA, dan suara yang dipakai adalah milik Anda atau berlisensi yang sesuai. Untuk dipublikasikan, gunakan karakter orisinal.
- **Privasi:** audio mikrofon diproses di komputer Anda. Teks hasil transkripsi dikirim ke penyedia LLM yang Anda pilih, dan teks balasan dikirim ke layanan Edge-TTS (butuh internet).
