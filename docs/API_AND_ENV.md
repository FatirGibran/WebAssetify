# ⚙️ Environment Variables & API Specs

## 1. Environment Variables (.env)

| Variabel | Deskripsi | Contoh Nilai |
| :--- | :--- | :--- |
| `TELEGRAM_BOT_TOKEN` | Token bot dari @BotFather | `123456:ABC-DEF...` |
| `GDRIVE_PARENT_FOLDER_ID` | ID folder target di Google Drive | `1A2b3C4d5E...` |
| `GDRIVE_SERVICE_ACCOUNT_JSON` | Konten service_account.json stringified | `{"type": "service_account", ...}` |
| `PORT` | Port untuk dummy health server (UptimeRobot) | `8080` |
| `MAX_VIDEO_HEIGHT` | Batas resolusi unduh yt-dlp | `720` |
| `WEBP_QUALITY` | Kualitas kompresi Pillow | `80` |

## 2. Health Endpoint
* **GET `/` atau `/health`**
  * Response: `200 OK`
  * Body: `{"status": "alive", "service": "WebAssetify"}`