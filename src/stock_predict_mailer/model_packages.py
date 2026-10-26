"""Signed model distribution without raw training data or executable serialization."""
from __future__ import annotations

import io
import json
import os
import zipfile
from datetime import date
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .contracts import contract_id, validate_contract
from .core import Config, atomic_write, connect, digest, now, write_json
from .model_registry import get_model, identifier, model_folder, schema
from .native_models import ALGORITHMS, native_predict

MAX_PACKAGE_BYTES = 55 * 1024 * 1024


def key_paths(cfg: Config) -> tuple[Path, Path]:
    root = cfg.workspace / "secrets" / "model-signing"
    return root / "publisher.key", root / "publisher.pub"


def generate_key(cfg: Config) -> dict:
    private_path, public_path = key_paths(cfg)
    private_path.parent.mkdir(parents=True, exist_ok=True)
    if private_path.exists() or public_path.exists():
        raise ValueError("publisher key already exists; refusing to overwrite trust identity")
    key = Ed25519PrivateKey.generate()
    # OS owner protection is still required on Windows; never emit private bytes.
    fd = os.open(private_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(key.private_bytes_raw())
        stream.flush()
        os.fsync(stream.fileno())
    public = key.public_key().public_bytes_raw()
    atomic_write(public_path, public)
    return {"private_key_path": str(private_path), "public_key_path": str(public_path), "public_key_sha256": digest(public)}


def export_package(cfg: Config, model_version: str, output: Path, signing_key: Path | None = None) -> dict:
    manifest, payload, row = get_model(cfg, model_version)
    if row["status"] != "published" or row["scope"] != "platform" or row["origin"] != "trained" or row["created_by"] != cfg.principal:
        raise ValueError("only own locally published platform models may be exported by this publisher")
    if row["channel"] != "demo" or manifest["synthetic"] is not True:
        raise ValueError("only synthetic demo release packages are supported")
    key_path = signing_key or key_paths(cfg)[0]
    private = Ed25519PrivateKey.from_private_bytes(key_path.read_bytes())
    publication = manifest["publication"]
    original_manifest = {key: value for key, value in manifest.items() if key != "publication"}
    card = ("# Synthetic demo model\n\nNot a stable market model or investment evidence.\n\n"
            + json.dumps(publication["model_card"], ensure_ascii=False, indent=2)).encode("utf-8")
    files = {manifest["artifact"]: payload, "model-card.md": card}
    envelope = {"schema_version": 1, "model": original_manifest, "publication": publication,
                "publisher_key_sha256": digest(private.public_key().public_bytes_raw()),
                "files": {name: digest(value) for name, value in files.items()}}
    release = json.dumps(envelope, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    signature = private.sign(release)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("release.json", release)
        archive.writestr("signature.ed25519", signature)
        for name, value in files.items():
            archive.writestr(name, value)
    package = buffer.getvalue()
    if len(package) > MAX_PACKAGE_BYTES:
        raise ValueError("release package too large")
    # Avoid replacing a different previous export at the chosen location.
    if output.exists():
        raise ValueError("output package already exists; choose a new path")
    atomic_write(output, package)
    return {"model_version": model_version, "channel": "demo", "path": str(output.resolve()),
            "package_sha256": digest(package), "publisher_key_sha256": envelope["publisher_key_sha256"]}


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate release JSON key")
        result[key] = value
    return result


def read_verified_package(path: Path, trusted_public_key: Path) -> tuple[dict, bytes]:
    if not 0 < path.stat().st_size <= MAX_PACKAGE_BYTES:
        raise ValueError("invalid release package size")
    public_bytes = trusted_public_key.read_bytes()
    public = Ed25519PublicKey.from_public_bytes(public_bytes)
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(entries) != 4 or len(set(names)) != 4 or sum(entry.file_size for entry in entries) > MAX_PACKAGE_BYTES:
            raise ValueError("invalid model archive members or uncompressed size")
        allowed = {"release.json", "signature.ed25519", "model.json", "model.txt", "model-card.md"}
        if set(names) - allowed or "release.json" not in names or "signature.ed25519" not in names or "model-card.md" not in names:
            raise ValueError("archive contains unexpected paths")
        if archive.getinfo("release.json").file_size > 2 * 1024 * 1024 or archive.getinfo("signature.ed25519").file_size != 64:
            raise ValueError("invalid manifest or signature size")
        release = archive.read("release.json")
        try:
            public.verify(archive.read("signature.ed25519"), release)
        except InvalidSignature as exc:
            raise ValueError("release signature does not match the independently trusted publisher key") from exc
        envelope = json.loads(release, object_pairs_hook=no_duplicates)
        if set(envelope) != {"schema_version", "model", "publication", "publisher_key_sha256", "files"} or envelope["schema_version"] != 1:
            raise ValueError("unsupported release schema")
        if envelope["publisher_key_sha256"] != digest(public_bytes):
            raise ValueError("publisher key fingerprint mismatch")
        model = envelope["model"]
        identifier(model["version"])
        identifier(model["training_snapshot"])
        contract = validate_contract(model["contract"])
        algorithm = model["algorithm"]
        artifact = "model.txt" if algorithm == "lightgbm" else "model.json"
        if algorithm not in ALGORITHMS or model["artifact"] != artifact or model["contract_id"] != contract_id(contract):
            raise ValueError("model artifact or contract mismatch")
        if model["scope"] != "platform" or model["synthetic"] is not True or contract["market"] != "synthetic":
            raise ValueError("this importer accepts synthetic platform demos only")
        publication = envelope["publication"]
        evaluation = publication["evaluation"]
        if publication["channel"] != "demo" or evaluation["model_version"] != model["version"] or evaluation["contract_id"] != model["contract_id"]:
            raise ValueError("publication identity mismatch")
        if date.fromisoformat(evaluation["feature_start"]) <= date.fromisoformat(model["train_label_end"]) or evaluation["metrics"]["days"] < 30:
            raise ValueError("release lacks required forward evaluation")
        expected = {artifact, "model-card.md"}
        if set(envelope["files"]) != expected or set(names) != expected | {"release.json", "signature.ed25519"}:
            raise ValueError("release file list mismatch")
        for name in expected:
            if digest(archive.read(name)) != envelope["files"][name]:
                raise ValueError("release file checksum mismatch")
        payload = archive.read(artifact)
        if digest(payload) != model["artifact_sha256"]:
            raise ValueError("native model checksum mismatch")
        native_predict(algorithm, payload, [{"x": [0.0] * 5}])  # load-only format smoke test
    return envelope, payload


def install_package(cfg: Config, path: Path, trusted_public_key: Path) -> dict:
    envelope, payload = read_verified_package(path, trusted_public_key)
    # A valid signature only proves which key signed; revocation decides whether
    # that key may still install anything.
    from .keys import require_active

    require_active(cfg, envelope["publisher_key_sha256"])
    manifest = envelope["model"]
    model_version = manifest["version"]
    folder = model_folder(cfg, model_version)
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    publication_bytes = json.dumps(envelope["publication"], ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    with connect(cfg) as con:
        schema(con)
        con.execute("BEGIN IMMEDIATE")
        existing = con.execute("SELECT * FROM registry_models WHERE version=?", (model_version,)).fetchone()
        if existing is not None:
            if existing["manifest_sha256"] != digest(manifest_bytes) or existing["publication_sha256"] != digest(publication_bytes) or existing["status"] != "published":
                raise ValueError("version already exists with different contents; refusing replacement")
            for name, expected in (("manifest.json", manifest_bytes), ("publication.json", publication_bytes), (manifest["artifact"], payload)):
                if digest((folder / name).read_bytes()) != digest(expected):
                    raise ValueError("existing installed version is damaged; refusing silent repair")
            return {"model_version": model_version, "status": "already_installed", "selection_changed": False}
        atomic_write(folder / manifest["artifact"], payload)
        atomic_write(folder / "manifest.json", manifest_bytes)
        atomic_write(folder / "publication.json", publication_bytes)
        write_json(folder / "installation.json", {"installed_at": now(), "publisher_key_sha256": envelope["publisher_key_sha256"], "package_sha256": digest(path.read_bytes())})
        con.execute("INSERT INTO registry_models VALUES (?, 'platform', ?, 'platform', 'imported', 'published', 'demo', ?, ?)",
                    (model_version, cfg.principal, digest(manifest_bytes), digest(publication_bytes)))
    return {"model_version": model_version, "channel": "demo", "status": "installed", "selection_changed": False}
