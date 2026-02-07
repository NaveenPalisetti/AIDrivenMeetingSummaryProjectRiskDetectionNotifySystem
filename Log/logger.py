import logging
from logging.handlers import RotatingFileHandler
import os


def setup_logging(log_dir: str = None, log_file_name: str = "meeting_mcp.log", level: int = logging.DEBUG, file_level: int = logging.DEBUG):
    """Configure root logger with console + rotating file handler.

    log_dir: if None, created at project root / Log
    level: console/root level
    file_level: level for the file handler (allows DEBUG to be written to file while keeping console quieter)
    """
    if log_dir is None:
        # place Log folder at repo root (two levels up from this file)
        this_dir = os.path.dirname(__file__)
        project_root = os.path.abspath(os.path.join(this_dir, ".."))
        log_dir = os.path.join(project_root, "Log")

    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, log_file_name)

    root = logging.getLogger()
    # Set root level to the lowest of console/file so handlers receive appropriate records
    root.setLevel(min(level, file_level))

    # Avoid adding multiple handlers if setup_logging called multiple times
    has_file = any(isinstance(h, RotatingFileHandler) and getattr(h, 'baseFilename', None) == os.path.abspath(log_path) for h in root.handlers)
    if not has_file:
        # Rotating file handler: 5 MB per file, keep 5 backups
        file_handler = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding='utf-8')
        file_formatter = logging.Formatter("%(asctime)s %(levelname)s:%(name)s: %(message)s")
        file_handler.setFormatter(file_formatter)
        file_handler.setLevel(file_level)
        root.addHandler(file_handler)

    # Ensure console handler exists
    console_exists = any(h for h in root.handlers if isinstance(h, logging.StreamHandler))
    if not console_exists:
        console = logging.StreamHandler()
        console.setLevel(level)
        console.setFormatter(logging.Formatter("%(levelname)s:%(name)s: %(message)s"))
        root.addHandler(console)

    # Set uvicorn loggers to the same level as the configured root level
    logging.getLogger("uvicorn").setLevel(level)
    logging.getLogger("uvicorn.error").setLevel(level)
    logging.getLogger("uvicorn.access").setLevel(level)

    return log_path
