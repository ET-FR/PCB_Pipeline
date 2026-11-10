import pytest


@pytest.fixture(autouse=True)
def isolated_knowledge_base(tmp_path_factory, monkeypatch):
    """Tests never read or write the user's real knowledge base or config."""
    home = tmp_path_factory.mktemp("kb")
    monkeypatch.setenv("PCB_PIPELINE_DATA", str(home / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "config"))
    return home / "data"
