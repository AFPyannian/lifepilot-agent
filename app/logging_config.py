import logging
from logging.handlers import RotatingFileHandler

from app.config import Settings


LOGGER_NAMESPACE = "lifepilot"


def configure_logging(
    settings: Settings,
) -> None:
    """Configure console and rotating file logging."""
    settings.log_file_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    application_logger = logging.getLogger(
        LOGGER_NAMESPACE
    )

    application_logger.setLevel(
        settings.log_level
    )

    application_logger.propagate = False

    for handler in list(
        application_logger.handlers
    ):
        application_logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(
        fmt=(
            "%(asctime)s | "
            "%(levelname)s | "
            "%(name)s | "
            "%(message)s"
        ),
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(settings.log_level)
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        filename=settings.log_file_path,
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(settings.log_level)
    file_handler.setFormatter(formatter)

    application_logger.addHandler(
        console_handler
    )
    application_logger.addHandler(
        file_handler
    )


def shutdown_logging() -> None:
    """Flush and close LifePilot log handlers."""
    application_logger = logging.getLogger(
        LOGGER_NAMESPACE
    )

    for handler in list(
        application_logger.handlers
    ):
        handler.flush()
        application_logger.removeHandler(handler)
        handler.close()