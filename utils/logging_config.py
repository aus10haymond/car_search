import logging
import logging.handlers
from pathlib import Path


def setup_logging(log_file: str, console_debug: bool = False) -> None:
    """
    Configure root logger:
      - Console: INFO level by default (DEBUG if console_debug=True)
      - File: DEBUG level, rotated at 5 MB, 3 backups kept (tracker.log)
    """
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Avoid duplicate handlers if called more than once
    if root.handlers:
        return

    fmt_console = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )
    fmt_file = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG if console_debug else logging.INFO)
    console_handler.setFormatter(fmt_console)

    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt_file)

    root.addHandler(console_handler)
    root.addHandler(file_handler)


def start_run_log(log_dir: str, run_id: str, timestamp: str) -> logging.FileHandler:
    """
    Add a dedicated per-run log file handler to the root logger.
    File is named:  logs/run_YYYYMMDD_HHMMSS_<short_id>.log
    Returns the handler so the caller can remove it when the run ends.
    """
    logs_dir = Path(log_dir) / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    short_id  = run_id.split("-")[0]
    log_path  = logs_dir / f"run_{timestamp}_{short_id}.log"

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler = logging.FileHandler(str(log_path), encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(fmt)

    logging.getLogger().addHandler(handler)
    return handler


def end_run_log(handler: logging.FileHandler) -> None:
    """Flush, close, and remove the per-run log handler."""
    handler.flush()
    handler.close()
    logging.getLogger().removeHandler(handler)
