"""Development startup must preserve both new credentials and the original vault."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from stock_predict_mailer.control.store import Store


class DevelopmentStoreTests(unittest.TestCase):
    def test_missing_master_key_reopens_isolated_encrypted_development_store(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = Store(root, Fernet.generate_key())
            old = original.put("models", {"name": "Original", "api_key": "original-secret"})
            with patch("stock_predict_mailer.control.store.env", return_value=None):
                development = Store(root)
                self.assertEqual(development.list("models"), [])
                model = development.put("models", {"name": "Development", "api_key": "development-secret"})
                reopened = Store(root)
                self.assertEqual(reopened.secret("models", model["id"])["api_key"], "development-secret")
                self.assertNotIn(b"development-secret", reopened.db_path.read_bytes())
            self.assertEqual(original.secret("models", old["id"])["api_key"], "original-secret")
