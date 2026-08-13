from types import SimpleNamespace

from raganything.parser import MineruParser
from raganything.services import user_settings


def test_mineru_uses_executable_from_active_virtual_environment(monkeypatch, tmp_path):
    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    mineru = scripts / "mineru.exe"
    mineru.write_text("", encoding="utf-8")
    monkeypatch.setattr("raganything.parser.pdf_parser.sys.executable", str(scripts / "python.exe"))

    assert MineruParser._mineru_command() == str(mineru)


def test_mineru_probe_uses_executable_from_active_virtual_environment(monkeypatch, tmp_path):
    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    mineru = scripts / "mineru.exe"
    mineru.write_text("", encoding="utf-8")
    monkeypatch.setattr("raganything.parser.pdf_parser.sys.executable", str(scripts / "python.exe"))
    calls = []

    def run(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(stdout="mineru, version test")

    monkeypatch.setattr("raganything.parser.pdf_parser.subprocess.run", run)

    assert MineruParser().check_installation() is True
    assert calls == [[str(mineru), "--version"]]


def test_parser_catalog_exposes_safe_installation_reason(monkeypatch):
    user_settings._parser_availability_cache.clear()
    parser = SimpleNamespace(installation_error=lambda: "missing optional runtime")
    monkeypatch.setattr("raganything.parser.get_parser", lambda _parser_id: parser)

    available, reason = user_settings._probe_parser_available("marker")

    assert available is False
    assert reason == "missing optional runtime"


def test_parser_catalog_caches_and_returns_reason_only_when_unavailable(monkeypatch):
    user_settings._parser_availability_cache.clear()
    calls = []
    parser = SimpleNamespace(installation_error=lambda: "missing optional runtime")

    def get_parser(_parser_id):
        calls.append(_parser_id)
        return parser

    monkeypatch.setattr("raganything.parser.SUPPORTED_PARSERS", ("marker",))
    monkeypatch.setattr("raganything.parser.get_parser", get_parser)

    first = user_settings._parser_catalog()
    second = user_settings._parser_catalog()

    assert first == second
    assert first[0]["reason"] == "missing optional runtime"
    assert calls == ["marker"]
