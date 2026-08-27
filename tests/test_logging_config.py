"""验证日志系统配置和关闭行为。"""

import logging

from app.config import Settings
from app.logging_config import (
    configure_logging,
    shutdown_logging,
)


def test_log_message_is_written_to_file(
    tmp_path,
):
    log_file = tmp_path / "lifepilot.log"

    settings = Settings(
        _env_file=None,
        deepseek_api_key="test-secret-key",
        log_level="INFO",
        log_file_path=log_file,
    )

    configure_logging(settings)

    try:
        logger = logging.getLogger("lifepilot.test")

        logger.info("Configuration test completed.")

        for handler in logging.getLogger("lifepilot").handlers:
            handler.flush()

        content = log_file.read_text(encoding="utf-8")

        assert "Configuration test completed." in content

        assert "test-secret-key" not in content
    finally:
        shutdown_logging()
