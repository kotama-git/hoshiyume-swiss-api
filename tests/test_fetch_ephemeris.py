from pathlib import Path

import pytest

from scripts.fetch_ephemeris import FILES, sha256


def test_pinned_dataset_contains_planets_and_moon():
    assert set(FILES) == {"sepl_18.se1", "semo_18.se1"}
    assert all(len(value) == 64 for value in FILES.values())


def test_sha256_reads_file_in_binary_chunks(tmp_path: Path):
    sample = tmp_path / "sample.se1"
    sample.write_bytes(b"known-data")
    assert sha256(sample) == "c231b45bfeefc1514d63661657ac361cb0e667b075592a1b23fa6dc8c7bbd284"


def test_fetch_refuses_checksum_mismatch(tmp_path: Path, monkeypatch):
    import scripts.fetch_ephemeris as module

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, _size):
            if getattr(self, "done", False):
                return b""
            self.done = True
            return b"tampered"

    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr(module, "FILES", {"sepl_18.se1": "0" * 64})
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        module.fetch(tmp_path)
    assert not (tmp_path / "sepl_18.se1").exists()
