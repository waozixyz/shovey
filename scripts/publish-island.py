#!/usr/bin/env python3
"""Prepare Island's signed compiled package; import it behind its existing gate.

Preparation is local and never copies the signing key. Operator registration
and transport are separate: protected_import calls register only after its
gate is durable, and before the canonical Apps importer exposes any bytes.
"""
import argparse
import importlib.util
from io import BytesIO
import json
import os
from pathlib import Path
import tarfile
import tempfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

APP = "xyz.waozi.shovey-island"
NAME = "shovey-island"
PRODUCT = "shovey.island"
KEY_ID = "shovey-island-2026-11b"
ORIGIN = "https://api.waozi.xyz"
MAX_PACKET = 65 * 1024 * 1024


def load_release(path):
    spec = importlib.util.spec_from_file_location("island_node_release", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def own_pins(path):
    pins = json.loads(path.read_bytes())
    if len(pins) != 1 or set(pins[0]) != {"key_id", "public_key", "app_ids", "node_app_ids"}:
        raise ValueError("Island needs one exact publisher pin")
    pin = pins[0]
    if pin["key_id"] != KEY_ID or pin["app_ids"] != [] or pin["node_app_ids"] != [APP]:
        raise ValueError("publisher pin is outside Island's namespace")
    return pins


def read_packet(path):
    if path.stat().st_size > MAX_PACKET:
        raise ValueError("oversized publication packet")
    entries = {}
    total = 0
    with tarfile.open(path, "r:") as archive:
        for member in archive:
            total += member.size
            if not member.isfile() or member.name in entries or total > MAX_PACKET or \
                    not member.name.startswith(APP + "/") or \
                    len(Path(member.name).parts) != 2 or member.size > 64 * 1024 * 1024:
                raise ValueError("invalid publication packet member")
            entries[member.name] = archive.extractfile(member).read(member.size + 1)
    return entries


def validate_entries(release, entries, pins, scratch):
    """Run the actual canonical importer in an unserved disposable directory."""
    value = json.loads(entries.get(APP + "/latest-v2.json", b"{}"))
    release.validate_release(value, APP, pins)
    if value["key_id"] != KEY_ID or value["dependencies"]:
        raise ValueError("unexpected Island publisher or dependencies")
    artifact = value["artifacts"][0]
    payload = artifact["sha256"] + ".zx"
    encoded = entries[APP + "/latest-v2.json"]
    expected = {APP + "/latest-v2.json", APP + "/" + payload,
                APP + "/" + payload + ".release-v2.json",
                APP + f"/release-{value['sequence']}.json"}
    if set(entries) != expected or any(entries[name] != encoded for name in expected
                                      if name.endswith(".json")):
        raise ValueError("Island packet must contain only its compiled release")
    scratch.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix="island-validate-", dir=scratch) as directory:
        release.import_node_app(entries, Path(directory), pins, APP)
    return value


def protected_import(release, entries, pins, store, scratch, register):
    """Validate, durably gate, register, then import using canonical validation.

    The authenticated operator must serialize this with its deployment lock.
    Any failure leaves a gate in place; it never creates an ungated payload.
    """
    value = validate_entries(release, entries, pins, scratch)
    directory = store / APP
    if directory.is_symlink():
        raise ValueError("Island namespace must not be a symlink")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Persist the namespace before its marker and payload can be published.
    descriptor = os.open(store, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    payload = directory / (value["artifacts"][0]["sha256"] + ".zx")
    if any(path.is_symlink() for path in directory.iterdir()):
        raise ValueError("Island namespace contains a symlink")
    gate = payload.with_name(payload.name + ".product")
    if gate.is_symlink() or (gate.exists() and gate.read_bytes() != (PRODUCT + "\n").encode()):
        raise ValueError("existing Island gate differs")
    if payload.exists() and not gate.exists():
        raise ValueError("existing payload has no gate; operator review required")
    release.atomic_write(gate, (PRODUCT + "\n").encode())
    register(value)
    release.import_node_app(entries, store, pins, APP)
    if gate.read_bytes() != (PRODUCT + "\n").encode():
        raise ValueError("Island gate changed during import")
    return value


def prepare(root, release, output, key_path):
    descriptor = json.loads((root / "packaging/island.json").read_bytes())
    pins = own_pins(root / "packaging/island-publishers.json")
    if key_path.stat().st_mode & 0o077:
        raise ValueError("private publisher key must be owner-only")
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("publisher key must be Ed25519")
    value, data = release.node_app_release(NAME, key, KEY_ID,
        ledger_path=root / "packaging/island-versions.json",
        bundle_directory=root / "build/player/games", publishers=pins)
    artifact = value["artifacts"][0]
    if descriptor["package_id"] != APP or descriptor["name"] != NAME or \
            descriptor["version"] != value["version"] or \
            descriptor["sha256"] != artifact["sha256"] or descriptor["bytes"] != artifact["size"]:
        raise ValueError("compiled Island differs from its reviewed descriptor")
    encoded = (json.dumps(value, separators=(",", ":")) + "\n").encode()
    payload = artifact["sha256"] + ".zx"
    entries = {APP + "/latest-v2.json": encoded, APP + "/" + payload: data,
               APP + "/" + payload + ".release-v2.json": encoded,
               APP + f"/release-{value['sequence']}.json": encoded}
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    validate_entries(release, entries, pins, output)
    packet = output / "island.tar"
    with tarfile.open(packet, "w:") as archive:
        for name, content in entries.items():
            member = tarfile.TarInfo(name)
            member.size = len(content)
            member.mode = 0o600
            archive.addfile(member, BytesIO(content))
    packet.chmod(0o600)
    release.atomic_write(output / "publishers.json", json.dumps(pins).encode() + b"\n")
    receipt = dict(app_id=APP, product=PRODUCT, origin=ORIGIN, key_id=KEY_ID,
                   version=value["version"], sequence=value["sequence"],
                   artifact=artifact, stage="prepared")
    release.atomic_write(output / "prepared.json", json.dumps(receipt, indent=2).encode() + b"\n")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node-release", required=True, type=Path,
                        help="canonical Apps scripts/node_release.py")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=Path("work/island-publication"))
    parser.add_argument("--key", type=Path, default=Path("backup/island-publisher/key.pem"))
    args = parser.parse_args()
    print(json.dumps(prepare(args.root, load_release(args.node_release), args.output, args.key)))


if __name__ == "__main__":
    main()
