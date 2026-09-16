# ⚡ WebAssetify

> **Automated Asset Harvester, Web Optimizer (.webp/.webm), and Cloud Delivery Pipeline.**

WebAssetify adalah bot automasi backend yang membaca dokumen (`.md`, `.txt`, `.pdf`, `.docx`, `.html`, `.csv`, `.json`) serta menerima media chat langsung, mengekstrak tautan media (gambar direct dan video/YouTube), mengonversinya secara otomatis ke format web modern yang ringan (`.webp` & `.webm`), lalu mengunggah hasilnya langsung ke Google Drive dalam struktur folder rapi beserta file manifest dan bundle `.zip`.

---

## ✨ Fitur Utama

* **Multi-Format Ingestion:** Ekstraksi URL otomatis dari Markdown, Plain Text, PDF (termasuk URI link annotations), Word DOCX (paragraf, tabel, hyperlink XML), HTML (tag `img`, `video`, `source`, `a`, inline CSS), CSV, dan JSON.
* **Direct Media Handling:** Menerima pengiriman langsung Foto dan Video via chat Telegram untuk dikonversi instan.
* **Auto Web Optimization:**
  * Gambar diunduh paralel dan dikonversi ke **WebP** via Pillow dengan auto-rotasi EXIF dan pembatasan resolusi maksimum.
  * Video (YouTube/platform lain via `yt-dlp` atau direct link) ditranscode otomatis ke format **WebM** via FFmpeg (libvpx-vp9/libopus) dengan lock transcode hemat memori.
* **Google Drive Delivery & Analytics:** Folder hasil, file manifest data (`manifest.json` & `session_summary.txt`), dan file bundle `.zip` otomatis diunggah ke Google Drive dengan laporan persentase penghematan storage.
* **Continuous Cloud Ready:** Dilengkapi dummy micro HTTP server untuk integrasi keep-alive (Render + UptimeRobot) agar bot tetap menyala 24/7 tanpa sleep.

---

## 📁 Struktur Folder Output di Drive

```text
Google Drive / WebAssetify_Vault /
└── WebAssetify_20260916_124500_123456789/
    ├── manifest.json
    ├── session_summary.txt
    ├── assets_bundle.zip
    ├── images/
    │   ├── 001_hero-banner.webp
    │   └── 002_icon-feature.webp
    └── videos/
        └── 001_demo-showcase.webm
```