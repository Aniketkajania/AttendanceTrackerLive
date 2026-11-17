"""Rotating recognition diagnostics written locally, not to the IIS web directory.

Set ENGINE_LOG_DIR to a restricted directory if the default project-local
logs folder is unsuitable. Keep attendance logs access-controlled.
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

_LOG = logging.getLogger("attendance.recognition")


def setup_engine_logging(base_dir):
    if _LOG.handlers:
        return _LOG
    directory = os.getenv("ENGINE_LOG_DIR", os.path.join(base_dir, "logs"))
    os.makedirs(directory, exist_ok=True)
    _LOG.setLevel(logging.INFO)
    _LOG.propagate = False
    formatter = logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    file_handler = RotatingFileHandler(
        os.path.join(directory, "recognition.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    _LOG.addHandler(file_handler)
    _LOG.addHandler(console_handler)
    _LOG.info("[ENGINE] diagnostic_log=%s", os.path.join(directory, "recognition.log"))
    return _LOG


def diag(message):
    if _LOG.handlers:
        _LOG.info("%s", message)
    else:
        # During isolated unit tests and imports before engine startup.
        print(message, flush=True)
