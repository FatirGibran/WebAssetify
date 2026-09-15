# 🤝 Contributing Guidelines

## Development Rules
1. **Async Discipline:** Jangan gunakan library sinkron blocking (`requests`, `time.sleep`) di thread utama. Gunakan `aiohttp` dan `asyncio.sleep`.
2. **Subprocess Isolation:** Jalankan eksekusi CLI FFmpeg dan yt-dlp di dalam `asyncio.to_thread`.
3. **Cleanup Guarantee:** Selalu letakkan fungsi penghapusan file scratch di dalam blok `finally:` untuk mencegah disk container penuh.