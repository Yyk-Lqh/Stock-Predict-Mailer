"""One project, one name: the assertions that keep the spelling from drifting."""
from __future__ import annotations

import os
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from stock_predict_mailer import __version__, naming

ROOT = Path(__file__).resolve().parents[1]


class NamingTest(unittest.TestCase):
    def test_the_three_forms_follow_their_own_rule(self):
        # Prose is hyphenated title case; index names are lowercase-hyphen; imports are snake_case.
        self.assertEqual(naming.PROJECT_NAME, "Stock-Predict-Mailer")
        self.assertEqual(naming.DISTRIBUTION_NAME, "stock-predict-mailer")
        self.assertEqual(naming.PACKAGE_NAME, "stock_predict_mailer")
        self.assertEqual(naming.COMMAND, naming.DISTRIBUTION_NAME)
        self.assertEqual(naming.PROJECT_NAME.lower(), naming.DISTRIBUTION_NAME)
        self.assertEqual(naming.DISTRIBUTION_NAME.replace("-", "_"), naming.PACKAGE_NAME)

    def test_pyproject_matches_the_naming_module(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        self.assertEqual(project["name"], naming.DISTRIBUTION_NAME)
        self.assertEqual(project["scripts"], {naming.COMMAND: f"{naming.PACKAGE_NAME}.cli:main"})
        # Version lives in the package, not in two places that can disagree.
        self.assertNotIn("version", project)
        self.assertIn("version", project["dynamic"])

    def test_version_is_declared_once(self):
        self.assertEqual(naming.version(), __version__)
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")
        self.assertIn(naming.version(), naming.banner())
        self.assertIn(naming.PROJECT_NAME, naming.banner())

    def test_env_prefers_the_canonical_prefix_and_still_reads_the_legacy_one(self):
        with mock.patch.dict(os.environ, {naming.env_key("MASTER_KEY"): "canonical"}, clear=True):
            self.assertEqual(naming.env("MASTER_KEY"), "canonical")
        with mock.patch.dict(os.environ, {f"{naming.LEGACY_ENV_PREFIX}_MASTER_KEY": "legacy"}, clear=True):
            self.assertEqual(naming.env("MASTER_KEY"), "legacy")
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(naming.env("MASTER_KEY"), "")
            self.assertEqual(naming.env("MASTER_KEY", "fallback"), "fallback")

    def test_env_key_is_the_documented_shape(self):
        self.assertEqual(naming.env_key("MASTER_KEY"), "STOCK_PREDICT_MAILER_MASTER_KEY")
        self.assertTrue(naming.env_key("X").startswith(naming.ENV_PREFIX + "_"))

    def test_user_facing_pages_show_the_proper_name(self):
        console = (ROOT / "src/stock_predict_mailer/control/web/index.html").read_text(encoding="utf-8")
        upload = (ROOT / "src/stock_predict_mailer/web/index.html").read_text(encoding="utf-8")
        for page in (console, upload):
            self.assertIn(f"<title>{naming.PROJECT_NAME}", page)
        self.assertIn(f'<span class="wordmark-name">{naming.PROJECT_NAME}</span>', console)
        self.assertIn(f'<span class="brand">{naming.PROJECT_NAME}</span>', upload)

    def test_readme_opens_with_the_proper_name(self):
        first = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()[0]
        self.assertEqual(first, f"# {naming.PROJECT_NAME}")

    def test_a2a_card_names_the_project(self):
        from stock_predict_mailer.control.a2a import card

        self.assertEqual(card("http://127.0.0.1:8767")["name"], f"{naming.PROJECT_NAME} · main")


if __name__ == "__main__":
    unittest.main()
