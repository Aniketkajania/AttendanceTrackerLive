"""Isolated test for local rotating recognition diagnostics (no camera or SQL)."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diagnostic_logging import setup_engine_logging, diag, _LOG


class EngineDiagnosticLogTests(unittest.TestCase):
    def tearDown(self):
        for handler in _LOG.handlers[:]:
            _LOG.removeHandler(handler)
            handler.close()

    def test_diagnostics_are_written_to_configured_path(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, {"ENGINE_LOG_DIR": temp}):
                setup_engine_logging(temp)
                diag("[MATCH_REJECT] camera=TEST reason=quality_too_small")
                for handler in _LOG.handlers:
                    handler.flush()
                log = Path(temp, "recognition.log").read_text(encoding="utf-8")
                self.assertIn("[MATCH_REJECT] camera=TEST", log)
                self.assertIn("diagnostic_log=", log)

    def test_maximum_file_size_and_backup_limit_are_configured(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, {"ENGINE_LOG_DIR": temp}):
                setup_engine_logging(temp)
                handler = next(h for h in _LOG.handlers if hasattr(h, "maxBytes"))
                self.assertEqual(handler.maxBytes, 5 * 1024 * 1024)
                self.assertEqual(handler.backupCount, 3)


if __name__ == "__main__":
    unittest.main()
