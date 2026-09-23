import pytest

from swiss_api.__main__ import configured_port


def test_configured_port_defaults_to_cloud_run_port(monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    assert configured_port() == 8080


@pytest.mark.parametrize("value", ["not-a-number", "0", "65536"])
def test_configured_port_rejects_invalid_values(monkeypatch, value):
    monkeypatch.setenv("PORT", value)
    with pytest.raises(SystemExit):
        configured_port()
