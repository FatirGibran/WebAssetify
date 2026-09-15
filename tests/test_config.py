"""Tests for config module."""

from config import Config


def test_config_defaults():
    cfg = Config()
    assert cfg.port == 8080
    assert cfg.max_video_height == 720
    assert cfg.webp_quality == 80


def test_config_validation_missing_secrets():
    cfg = Config(telegram_bot_token="", gdrive_parent_folder_id="", gdrive_service_account_json="")
    errors = cfg.validate(check_secrets=True)
    assert len(errors) == 3
    assert any("TELEGRAM_BOT_TOKEN" in e for e in errors)
    assert any("GDRIVE_PARENT_FOLDER_ID" in e for e in errors)
    assert any("GDRIVE_SERVICE_ACCOUNT_JSON" in e for e in errors)


def test_config_validation_invalid_bounds():
    cfg = Config(port=-1, max_video_height=0, webp_quality=150)
    errors = cfg.validate(check_secrets=False)
    assert len(errors) == 3
    assert any("PORT" in e for e in errors)
    assert any("MAX_VIDEO_HEIGHT" in e for e in errors)
    assert any("WEBP_QUALITY" in e for e in errors)


def test_config_safe_dict_masks_secrets():
    cfg = Config(
        telegram_bot_token="1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
        gdrive_parent_folder_id="1a2B3c4D5e6F7g8H9i0J",
        gdrive_service_account_json='{"type":"service_account"}',
    )
    safe = cfg.to_safe_dict()
    assert safe["telegram_bot_token"].startswith("1234...")
    assert safe["telegram_bot_token"].endswith("wxyz")
    assert safe["gdrive_service_account_json"] == "<configured>"
