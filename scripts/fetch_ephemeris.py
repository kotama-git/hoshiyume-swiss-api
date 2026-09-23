"""Fetch the minimal official Swiss Ephemeris dataset with pinned hashes."""

from __future__ import annotations

import argparse
import hashlib
import os
import tempfile
import urllib.request
from pathlib import Path


UPSTREAM_COMMIT = "9083a12d59e98034fb2337061481ac8800c16e64"
BASE_URL = (
    "https://raw.githubusercontent.com/aloistr/swisseph/"
    f"{UPSTREAM_COMMIT}/ephe"
)
FILES = {
    "sepl_18.se1": "ca1393ceab3a44fbc895887cf789c68819ae6a1cbc9b22225872dbe4ccd99a66",
    "semo_18.se1": "1ca07bd67c24374d77226180c20a4f9996cba013697894810518e7eb582ca4f7",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for name, expected_hash in FILES.items():
        final_path = destination / name
        if final_path.is_file() and sha256(final_path) == expected_hash:
            continue
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{name}.", dir=destination)
        os.close(descriptor)
        temporary_path = Path(temporary_name)
        try:
            request = urllib.request.Request(
                f"{BASE_URL}/{name}",
                headers={"User-Agent": "hoshiyume-swiss-api-build/1"},
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                if response.status != 200:
                    raise RuntimeError(f"unexpected download status for {name}: {response.status}")
                with temporary_path.open("wb") as target:
                    while chunk := response.read(1024 * 1024):
                        target.write(chunk)
            actual_hash = sha256(temporary_path)
            if actual_hash != expected_hash:
                raise RuntimeError(
                    f"checksum mismatch for {name}: expected {expected_hash}, got {actual_hash}"
                )
            temporary_path.replace(final_path)
        finally:
            temporary_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    fetch(args.destination.resolve())


if __name__ == "__main__":
    main()
