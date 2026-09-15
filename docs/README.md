# ⚡ AssetForge

> **Automated Asset Harvester, Web Optimizer (.webp/.webm), and Cloud Delivery Pipeline.**

AssetForge adalah bot automasi backend yang membaca dokumen (`.md`, `.txt`, `.pdf`, `.docx`), mengekstrak tautan media (gambar direct dan video/YouTube), mengonversinya secara otomatis ke format web modern yang ringan (`.webp` & `.webm`), lalu mengunggah hasilnya langsung ke Google Drive dalam struktur folder rapi beserta bundle file `.zip`.

---

## ✨ Fitur Utama

* **Multi-Format Ingestion:** Ekstraksi URL otomatis dari file Markdown, Plain Text, PDF (termasuk URI link annotations), dan Word DOCX.
* **Auto Web Optimization:**
  * Gambar diunduh paralel dan dikonversi ke **WebP** via Pillow.
  * Video (YouTube/platform lain via `yt-dlp`) ditranscode otomatis ke format **WebM** via FFmpeg.
* **Google Drive Delivery:** Folder hasil dan file bundle `.zip` otomatis dibuatkan di Google Drive tanpa membebani storage lokal/container.
* **Continuous Cloud Ready:** Dilengkapi dummy micro HTTP server untuk integrasi keep-alive (Render + UptimeRobot) agar bot tetap menyala 24/7 tanpa sleep.

---

## 📁 Struktur Folder Output di Drive

```text
Google Drive / AssetForge_Vault /
└── AssetForge_20260915_081530/
    ├── bundle_assets.zip
    ├── images/
    │   ├── hero-banner.webp
    │   └── icon-feature.webp
    └── videos/
        └── demo-showcase.webm