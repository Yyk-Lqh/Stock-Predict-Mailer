import copy
import csv
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from stock_predict_mailer.contracts import read_contract
from stock_predict_mailer.core import Config
from stock_predict_mailer.data import FIELDS, demo_csv, import_csv, load_snapshot
from stock_predict_mailer.model_packages import export_package, generate_key, install_package, key_paths
from stock_predict_mailer.model_registry import evaluate_model, get_model, list_models, model_folder, predict_snapshot, publish_demo, select_model, train_platform


class ModelPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.publisher = Config(self.root / "publisher", principal="publisher")
        self.client = Config(self.root / "client", principal="alice")
        self.contract = read_contract(Path("config/task-demo.json"))
        self.snapshot = import_csv(self.publisher, demo_csv(self.root / "bars.csv", 200, 6), synthetic=True)["snapshot_id"]
        _, self.rows = load_snapshot(self.publisher, self.snapshot)
        dates = sorted({r["date"] for r in self.rows})
        self.cutoff = dates[-1] + "T20:00:00+08:00"
        model = train_platform(self.publisher, self.snapshot, self.contract, dates[110] + "T20:00:00+08:00", confirm_platform_data=True)
        self.model_version = model["version"]
        evaluation = evaluate_model(self.publisher, self.model_version, self.snapshot, self.cutoff)
        self.evaluation_id = evaluation["evaluation_id"]
        publish_demo(self.publisher, self.model_version, self.evaluation_id)
        generate_key(self.publisher)
        self.private_key, self.public_key = key_paths(self.publisher)
        self.package = self.root / "demo.zip"
        export_package(self.publisher, self.model_version, self.package)

    def rewrite(self, transform):
        with zipfile.ZipFile(self.package) as source:
            values = {name: source.read(name) for name in source.namelist()}
        transform(values)
        output = self.root / "changed.zip"
        with zipfile.ZipFile(output, "w") as archive:
            for name, content in values.items():
                archive.writestr(name, content)
        return output

    def test_fresh_workspace_predicts_without_platform_training_data_or_fit(self):
        installed = install_package(self.client, self.package, self.public_key)
        self.assertFalse(installed["selection_changed"])
        _, _, state = get_model(self.client, self.model_version)
        self.assertEqual(state["origin"], "imported")
        dates = sorted({r["date"] for r in self.rows})
        tail = [r for r in self.rows if r["date"] >= dates[-35]]
        text = io.StringIO()
        writer = csv.DictWriter(text, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(tail)
        recent = self.root / "recent.csv"
        recent.write_text(text.getvalue(), encoding="utf-8")
        snapshot = import_csv(self.client, recent, synthetic=True)["snapshot_id"]
        self.assertNotEqual(snapshot, self.snapshot)
        self.assertFalse((self.client.workspace / "snapshots" / self.snapshot).exists())
        select_model(self.client, self.model_version, allow_demo=True)
        with patch("sklearn.linear_model.Ridge.fit", side_effect=AssertionError("client must not train")), patch("stock_predict_mailer.native_models.fit_native", side_effect=AssertionError("client must not train")):
            result = predict_snapshot(self.client, snapshot, self.cutoff, allow_demo=True)
        self.assertFalse(result["training_performed"])
        self.assertEqual(len(result["predictions"]), 5)
        with zipfile.ZipFile(self.package) as archive:
            self.assertEqual(set(archive.namelist()), {"release.json", "signature.ed25519", "model.json", "model-card.md"})
            self.assertNotIn(self.private_key.read_bytes(), self.package.read_bytes())

    def test_wrong_trust_key_and_signed_manifest_tamper(self):
        wrong = self.root / "wrong.pub"
        wrong.write_bytes(Ed25519PrivateKey.generate().public_key().public_bytes_raw())
        with self.assertRaises(ValueError):
            install_package(self.client, self.package, wrong)
        changed = self.rewrite(lambda values: values.update({"release.json": b" " + values["release.json"]}))
        with self.assertRaises(ValueError):
            install_package(self.client, changed, self.public_key)
        self.assertEqual(list_models(self.client), [])

    def test_payload_checksum_and_illegal_path_rejected(self):
        changed = self.rewrite(lambda values: values.update({"model.json": values["model.json"] + b" "}))
        with self.assertRaises(ValueError):
            install_package(self.client, changed, self.public_key)
        changed = self.rewrite(lambda values: values.update({"../outside": b"bad"}))
        with self.assertRaises(ValueError):
            install_package(self.client, changed, self.public_key)
        self.assertFalse((self.root / "outside").exists())

    def test_installer_does_not_change_selection_or_silently_replace_damage(self):
        install_package(self.client, self.package, self.public_key)
        select_model(self.client, self.model_version, allow_demo=True)
        again = install_package(self.client, self.package, self.public_key)
        self.assertEqual(again["status"], "already_installed")
        self.assertFalse(again["selection_changed"])
        with self.assertRaises(ValueError):
            publish_demo(self.client, self.model_version, self.evaluation_id)
        artifact = model_folder(self.client, self.model_version) / "model.json"
        artifact.write_bytes(b"damaged")
        with self.assertRaises(ValueError):
            install_package(self.client, self.package, self.public_key)
        self.assertEqual(artifact.read_bytes(), b"damaged")

    def test_signed_but_semantically_invalid_evaluation_is_rejected(self):
        def invalid(values):
            envelope = json.loads(values["release.json"])
            envelope["publication"]["evaluation"]["feature_start"] = envelope["model"]["train_label_end"]
            values["release.json"] = json.dumps(envelope).encode()
            values["signature.ed25519"] = Ed25519PrivateKey.from_private_bytes(self.private_key.read_bytes()).sign(values["release.json"])
        changed = self.rewrite(invalid)
        with self.assertRaises(ValueError):
            install_package(self.client, changed, self.public_key)

    def test_keys_and_export_are_not_overwritten(self):
        before = self.private_key.read_bytes()
        with self.assertRaises(ValueError):
            generate_key(self.publisher)
        self.assertEqual(before, self.private_key.read_bytes())
        original = self.package.read_bytes()
        with self.assertRaises(ValueError):
            export_package(self.publisher, self.model_version, self.package)
        self.assertEqual(original, self.package.read_bytes())

    def test_lightgbm_native_package_installs(self):
        try:
            import lightgbm
        except ImportError:
            self.skipTest("install optional trees dependency")
        dates = sorted({r["date"] for r in self.rows})
        model = train_platform(self.publisher, self.snapshot, self.contract, dates[110] + "T20:00:00+08:00", "lightgbm", confirm_platform_data=True)
        evaluation = evaluate_model(self.publisher, model["version"], self.snapshot, self.cutoff)
        publish_demo(self.publisher, model["version"], evaluation["evaluation_id"])
        package = self.root / "lightgbm.zip"
        export_package(self.publisher, model["version"], package)
        installed = install_package(self.client, package, self.public_key)
        self.assertEqual(installed["model_version"], model["version"])
        loaded, _, _ = get_model(self.client, model["version"])
        self.assertEqual(loaded["artifact"], "model.txt")


if __name__ == "__main__":
    unittest.main()
