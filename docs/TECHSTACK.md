# Tech Stack Specification: AssetForge

Dokumen ini mendefinisikan arsitektur teknologi, library, dan runtime environment yang digunakan pada sistem otomasi AssetForge.

## 1. Core Architecture & Runtime
* **Runtime:** Python 3.11 (Slim Debian base)
* **Containerization:** Docker (Multi-stage build / Minimal slim image)
* **Execution Paradigm:** Asynchronous Event Loop (`asyncio`) dengan worker thread offloading untuk proses CLI-bound.

## 2. Dependencies & Libraries

### Network, Webhook & Server Keep-Alive
* **`aiohttp` (v3.9+):** 
  * Menjalankan micro HTTP web server di port internal (`$PORT` / `8080`) untuk endpoint health check keep-alive (UptimeRobot).
  * Asynchronous HTTP client untuk streaming download direct image assets.
* **`python-telegram-bot` (v20+):** Asynchronous Telegram Bot framework untuk menerima payload dokumen dan mengirimkan link folder Google Drive.

### Document & Payload Parsers
* **`pypdf` (v4+):** Ekstraksi teks dan resolusi URI Hyperlink annotations dari file `.pdf`.
* **`python-docx` (v1.1+):** Ekstraksi teks paragraf, elemen tabel, dan relasi XML hyperlink (`w:hyperlink`) dari file `.docx`.
* **Regex Engine (`re`):** Ekstraksi direct URL dan format markdown link (`[text](url)`, `![alt](url)`).

### Media Processing & Transcoding
* **`Pillow` (PIL Fork v10+):** Decoder multi-format gambar dan konversi/kompresi lossy/lossless ke format standar modern web (`.webp`).
* **`yt-dlp` (Latest):** Engine ekstraksi video multi-platform (YouTube, TikTok, X, CDN publik).
* **System CLI: `ffmpeg`:** Transcoding video engine ke format `.webm` (VP9 video codec, Opus audio codec) dengan pembatasan thread untuk efisiensi memori container.

### Cloud Integration & Storage
* **`google-api-python-client` & `google-auth`:** Otentikasi Service Account ke Google Drive API v3 untuk pembuatan folder terstruktur, batch upload aset, dan permission sharing.

## 3. Hosting & Deployment Environment
* **Platform:** Render.com (Web Service Docker Environment)
* **Keep-Alive Mechanism:** UptimeRobot HTTP ping via `/health` endpoint tiap 5 menit.
* **Storage Target:** Google Drive (5 TB capacity via Service Account delegated folder).