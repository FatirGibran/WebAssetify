# Deployment & Integration Guide

Panduan setup kredensial Google Drive, environment container, dan deployment ke Render + UptimeRobot.

## 1. Persiapan Google Drive Service Account
1. Buka [Google Cloud Console](https://console.cloud.google.com/).
2. Buat project baru (contoh: `assetforge-prod`).
3. Buka **APIs & Services** > **Library**, cari **Google Drive API**, lalu klik **Enable**.
4. Masuk ke **Credentials** > **Create Credentials** > **Service Account**.
5. Isi nama service account, klik **Done**.
6. Klik pada service account yang baru dibuat, buka tab **Keys** > **Add Key** > **Create new key** (pilih **JSON**).
7. Simpan file sebagai `service_account.json` (jangan di-commit ke Git).
8. Buka Google Drive pribadimu, buat folder baru bernama `AssetForge_Vault`.
9. Klik kanan folder tersebut > **Share**, lalu masukkan email service account tadi dengan role **Editor**.
10. Salin **Folder ID** dari URL browser:
    `https://drive.google.com/drive/folders/{FOLDER_ID_KAMU}`

## 2. Environment Variables (.env)
Konfigurasikan variabel lingkungan berikut di dashboard Render:

```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
GDRIVE_PARENT_FOLDER_ID=your_extracted_folder_id_here
GDRIVE_SERVICE_ACCOUNT_JSON={"type":"service_account", ...} # Format stringified JSON
PORT=8080
MAX_VIDEO_HEIGHT=720
WEBP_QUALITY=80