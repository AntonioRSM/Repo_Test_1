"""Test dell'installazione del server MCP f5-tts nel mcp.json di LM Studio."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "app"))
import lmstudio_mcp_config as cfg  # noqa: E402


def test_install_conserva_altri_server(tmp_path):
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"mcpServers": {"altro": {"command": "x"}}}))
    cfg.install(str(path), cfg.server_entry(str(tmp_path / "ab")))
    data = json.loads(path.read_text())
    assert data["mcpServers"]["altro"] == {"command": "x"}
    f5 = data["mcpServers"]["f5-tts"]
    assert f5["command"] == sys.executable and f5["args"][0].endswith("mcp_server.py")
    assert f5["env"]["AUDIOBOOK_DIR"] == str(tmp_path / "ab")
    assert (tmp_path / "mcp.json.bak").exists()


def test_install_file_nuovo_o_vuoto(tmp_path):
    path = tmp_path / "mcp.json"
    cfg.install(str(path), cfg.server_entry())
    assert "env" not in json.loads(path.read_text())["mcpServers"]["f5-tts"]
    path.write_text("")
    cfg.install(str(path), cfg.server_entry())
    assert "f5-tts" in json.loads(path.read_text())["mcpServers"]


def test_install_errori(tmp_path):
    bad = tmp_path / "mcp.json"
    bad.write_text("{ non json")
    with pytest.raises(SystemExit):
        cfg.install(str(bad), cfg.server_entry())
    assert bad.read_text() == "{ non json"  # file dell'utente non toccato
    with pytest.raises(SystemExit):
        cfg.install(str(tmp_path / "manca" / "mcp.json"), cfg.server_entry())
