import sys

from molweigh.db import paths


class TestGetAppDataDir:
    def test_windows(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setenv("APPDATA", str(tmp_path))
        result = paths.get_app_data_dir()
        assert result == tmp_path / "MolWeigh"
        assert result.is_dir()

    def test_macos(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(paths.Path, "home", lambda: tmp_path)
        result = paths.get_app_data_dir()
        assert result == tmp_path / "Library" / "Application Support" / "MolWeigh"
        assert result.is_dir()

    def test_linux_fallback(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(paths.Path, "home", lambda: tmp_path)
        result = paths.get_app_data_dir()
        assert result == tmp_path / ".local" / "share" / "MolWeigh"
        assert result.is_dir()


class TestGetDbPath:
    def test_db_path_under_app_data_dir(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setenv("APPDATA", str(tmp_path))
        assert paths.get_db_path() == tmp_path / "MolWeigh" / "molweigh.db"
