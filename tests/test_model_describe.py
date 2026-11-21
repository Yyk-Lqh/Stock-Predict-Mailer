import tempfile
import unittest
from pathlib import Path

from stock_predict_mailer.core import Config, connect
from stock_predict_mailer.model_registry import describe_models, schema


def register(cfg, version, *, owner="owner", scope="platform", status="draft"):
    with connect(cfg) as con:
        schema(con)
        con.execute("INSERT INTO registry_models VALUES (?,?,?,?,?,?,?,?,?)",
                    (version, owner, owner, scope, "trained", status, None, "0" * 64, None))


class DescribeTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.cfg = Config(Path(self.folder.name))

    def tearDown(self):
        self.folder.cleanup()

    def test_a_workspace_without_models_lists_nothing(self):
        self.assertEqual(describe_models(self.cfg), [])

    def test_a_model_without_a_manifest_degrades_instead_of_failing(self):
        register(self.cfg, "a" * 64)
        described = describe_models(self.cfg)
        self.assertEqual(len(described), 1)
        self.assertEqual(described[0]["status"], "broken")
        self.assertIsNone(described[0]["algorithm"])
        self.assertEqual(described[0]["version"], "a" * 64)

    def test_the_newest_version_comes_first(self):
        register(self.cfg, "a" * 64)
        register(self.cfg, "b" * 64)
        self.assertEqual([entry["version"] for entry in describe_models(self.cfg)], ["b" * 64, "a" * 64])

    def test_the_limit_is_respected(self):
        for index in range(3):
            register(self.cfg, str(index) * 64)
        self.assertEqual(len(describe_models(self.cfg, limit=2)), 2)


if __name__ == "__main__":
    unittest.main()
