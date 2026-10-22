# Web Frontend (three.js + three-vrm)

Antarmuka 3D visual avatar Silvia berbasis browser menggunakan Three.js (0.180.0), `@pixiv/three-vrm` (3.5.5), dan `@pixiv/three-vrm-animation` (3.5.5) yang dimuat via CDN ES Module Import Map.

---

## Arsitektur Modul

```text
web/
├── index.html          # Markup antarmuka utama, subtitle, status pill, dan panel uji
├── main.js             # Entry point aplikasi & render loop tersinkronisasi
├── style.css           # Styling visual premium, HUD monitor performa, & panel debug
├── README.md           # Dokumentasi arsitektur frontend
└── js/
    ├── animation.js    # AnimationBlender: sistem bobot ternormalisasi (total = 1.0)
    ├── avatar.js       # Loader VRM & VRMA, normalisasi himpunan track tulang, filter ekspresi
    ├── expressions.js  # Manajemen emosi terpusat, auto-blink, lerp morph target, isolasi lip-sync
    ├── audio.js        # Web Audio API, AnalyserNode, deteksi RMS volume untuk lip-sync
    ├── scene.js        # Setup Scene Three.js, Camera, OrbitControls, & Lighting
    ├── ui.js           # Subtitle dua baris, status koneksi, monitor CPU/GPU/RAM, panel debug
    └── websocket.js    # Koneksi WebSocket server, antrean pemutaran baris kalimat & audio
```

---

## Fitur Utama Sistem Animasi & Ekspresi

### 1. Lapisan Dasar Idle Berkelanjutan (`AnimationBlender`)
- File `Idle.vrma` diputar secara terus-menerus (`LoopRepeat`) sejak model selesai dimuat.
- Tidak pernah terjadi kondisi avatar berdiri kaku seperti patung atau kembali ke T-pose saat transisi.
- Jika file `Idle.vrma` tidak ditemukan, sistem otomatis beralih ke animasi idle prosedural berbasis matematika pernapasan (rotasi dinamis tulang `spine` dan `head`).

### 2. Transisi Animasi Mulus Tanpa T-Pose (*Crossfade*)
- **Normalisasi Bobot ($\sum w_i = 1.0$):** Semua action animasi selalu berstatus `enabled = true` dan diatur secara presisi melalui `setEffectiveWeight`. Jumlah seluruh bobot animasi di setiap frame selalu bernilai 1.0.
- **Normalisasi Himpunan Tulang (`normalizeTrackSets`):** Menyamakan himpunan track tulang di semua clip VRMA. Tulang yang tidak ada di clip one-shot diberi track konstan dari clip referensi idle, mencegah lonjakan pose tulang (*bone snap*) ke bind-pose saat crossfade.
- **Penyaringan Track Ekspresi:** Track ekspresi di dalam file VRMA disaring saat pemuatan agar tidak berbenturan dengan kontrol ekspresi kode.
- **Inisialisasi Bebas T-Pose:** Model VRM di-load dalam status tersembunyi (`visible = false`), dievaluasi frame ke-0 oleh mixer, baru dimunculkan ke layar.

### 3. Manajemen Emosi & Ekspresi Wajah Mandiri
- **Himpunan Managed Expressions:** Terdaftar dinamis dari konfigurasi `/api/config` dan preset standar model.
- **Pembersihan Emosi Lama:** Saat emosi berganti, semua target ekspresi di-nol-kan terlebih dahulu sebelum nilai emosi baru diterapkan.
- **Pencegahan Emosi Menempel:** Pada setiap frame, nilai morph target di-lerp menuju target dengan laju turun lebih cepat (`EXPR_FALL_SPEED = 14.0/s`) dibandingkan laju naik (`EXPR_RISE_SPEED = 10.0/s`), dan nilai 0.0 selalu diset eksplisit ke `expressionManager`.
- **Timer WebSocket Terproteksi:** Timer kembali ke emosi netral selalu dibatalkan saat baris kalimat baru masuk, mencegah emosi kalimat berikutnya ter-reset di tengah jalan.
- **Isolasi Lip-sync & Blink:** Kedipan otomatis (`blink`) dan gerak mulut suara (`aa`) berjalan independen dari emosi wajah.

### 4. Urutan Render Loop Presisi (Zero-Frame Delay)
Render loop diatur dengan urutan sekuensial yang ketat:
```text
1. updateAvatarAnimation(dt)   -> Evaluasi bobot AnimationBlender & mixer.update()
2. updateBlink(dt)             -> Kalkulasi kedipan mata acak
3. updateLipSync(dt)           -> Analisis RMS audio buffer
4. updateExpressions(vrm, dt)  -> Set morph target via expressionManager.setValue()
5. updateAvatarVRM(dt)         -> Evaluasi vrm.update() (menerapkan ekspresi & physics spring bone)
6. controls.update() & render  -> OrbitControls dan render Three.js ke canvas
```

---

## Panel Uji Debug (Shortcut: `D`)

Tekan huruf **`D`** pada keyboard atau klik tombol **`D`** di kanan bawah layar untuk membuka panel uji:
- **Daftar Tombol Animasi:** Uji pemicuan setiap animasi one-shot yang tersedia.
- **Daftar Tombol Emosi:** Uji ekspresi emosi (*happy*, *sad*, *angry*, *shy*, *surprised*, *sleepy*, *neutral*).
- **Slider Mulut (aa):** Uji manual pembukaan morph target mulut.
- **🔁 Tombol "Uji Beruntun":** Menjalankan stres tes otomatis pergantian emosi cepat dan animasi berurutan untuk memverifikasi kehalusan crossfade.
- **🐢 Tombol "Slow-mo 0.1×":** Menurunkan kecepatan waktu animasi ke 10% untuk inspeksi visual detail setiap perpindahan tulang dan memastikan ketiadaan glitch T-pose.
- **HUD Bobot Real-Time:** Menampilkan grafik ASCII live dari bobot effective semua action animasi dan persentase aktif blendshape ekspresi.
