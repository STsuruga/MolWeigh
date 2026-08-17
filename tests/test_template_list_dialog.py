import sqlite3

import pytest
from PySide6.QtWidgets import QDialog, QMessageBox

from molweigh.db import library_repo, schema, template_repo
from molweigh.db.library_repo import LibraryEntry
from molweigh.ui.template_list_dialog import TemplateEditDialog, TemplateListDialog


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    schema.migrate(connection)
    yield connection
    connection.close()


def _seed_library(conn, name="Base", **overrides):
    defaults = dict(id=None, name=name, molecular_weight=100.0, source="pubchem")
    defaults.update(overrides)
    return library_repo.create(conn, LibraryEntry(**defaults))


def _seed_template(conn, name, base_id, extra=None):
    reagents = [{"name": "Base", "library_id": base_id, "role": "base", "eq": 1.0}]
    if extra:
        reagents.extend(extra)
    return template_repo.create(conn, name, {"reagents": reagents})


class TestTemplateListDialog:
    def test_refresh_lists_templates(self, qapp, conn):
        base_id = _seed_library(conn)
        _seed_template(conn, "テンプレA", base_id)
        _seed_template(conn, "テンプレB", base_id)
        dialog = TemplateListDialog(conn)
        assert dialog._list.count() == 2

    def test_load_emits_selected_template(self, qapp, conn):
        base_id = _seed_library(conn)
        template_id = _seed_template(conn, "テンプレA", base_id)
        dialog = TemplateListDialog(conn)
        dialog._list.setCurrentRow(0)

        received = []
        dialog.template_loaded.connect(received.append)
        dialog._on_load()

        assert len(received) == 1
        assert received[0].id == template_id

    def test_load_without_selection_does_nothing(self, qapp, conn):
        dialog = TemplateListDialog(conn)
        received = []
        dialog.template_loaded.connect(received.append)
        dialog._on_load()
        assert received == []

    def test_delete_removes_template(self, qapp, conn, monkeypatch):
        base_id = _seed_library(conn)
        template_id = _seed_template(conn, "テンプレA", base_id)
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)

        dialog = TemplateListDialog(conn)
        dialog._list.setCurrentRow(0)
        dialog._on_delete()

        assert template_repo.get(conn, template_id) is None
        assert dialog._list.count() == 0

    def test_declined_delete_keeps_template(self, qapp, conn, monkeypatch):
        base_id = _seed_library(conn)
        template_id = _seed_template(conn, "テンプレA", base_id)
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)

        dialog = TemplateListDialog(conn)
        dialog._list.setCurrentRow(0)
        dialog._on_delete()

        assert template_repo.get(conn, template_id) is not None


class TestTemplateEditDialog:
    def test_initializes_rows_from_payload(self, qapp, conn):
        base_id = _seed_library(conn, name="Base")
        dmap_id = _seed_library(conn, name="DMAP")
        template_id = _seed_template(
            conn, "テンプレA", base_id,
            extra=[{"name": "DMAP", "library_id": dmap_id, "role": "additive", "eq": 6.0}],
        )
        tmpl = template_repo.get(conn, template_id)
        dialog = TemplateEditDialog(conn, tmpl)

        assert len(dialog._row_widgets) == 2
        assert dialog._row_widgets[0]._name_label.text() == "Base"
        assert dialog._row_widgets[1]._name_label.text() == "DMAP"
        assert dialog._row_widgets[1]._eq_spin.value() == pytest.approx(6.0)

    def test_base_row_eq_and_role_are_locked(self, qapp, conn):
        base_id = _seed_library(conn, name="Base")
        template_id = _seed_template(conn, "テンプレA", base_id)
        tmpl = template_repo.get(conn, template_id)
        dialog = TemplateEditDialog(conn, tmpl)

        assert dialog._row_widgets[0]._role_combo.isEnabled() is False
        assert dialog._row_widgets[0]._eq_spin.isEnabled() is False

    def test_save_persists_renamed_template_and_eq_change(self, qapp, conn):
        base_id = _seed_library(conn, name="Base")
        dmap_id = _seed_library(conn, name="DMAP")
        template_id = _seed_template(
            conn, "テンプレA", base_id,
            extra=[{"name": "DMAP", "library_id": dmap_id, "role": "additive", "eq": 6.0}],
        )
        tmpl = template_repo.get(conn, template_id)
        dialog = TemplateEditDialog(conn, tmpl)

        dialog._name_input.setText("改名後")
        dialog._row_widgets[1]._eq_spin.setValue(3.5)
        dialog._on_save()

        saved = template_repo.get(conn, template_id)
        assert saved.name == "改名後"
        assert saved.payload["reagents"][1]["eq"] == pytest.approx(3.5)

    def test_remove_row_excludes_it_from_saved_payload(self, qapp, conn):
        base_id = _seed_library(conn, name="Base")
        dmap_id = _seed_library(conn, name="DMAP")
        template_id = _seed_template(
            conn, "テンプレA", base_id,
            extra=[{"name": "DMAP", "library_id": dmap_id, "role": "additive", "eq": 6.0}],
        )
        tmpl = template_repo.get(conn, template_id)
        dialog = TemplateEditDialog(conn, tmpl)

        second_row = dialog._row_widgets[1]
        dialog._on_remove_row(second_row)
        assert len(dialog._row_widgets) == 1

        dialog._on_save()
        saved = template_repo.get(conn, template_id)
        assert len(saved.payload["reagents"]) == 1

    def test_add_reagent_from_library_appends_row(self, qapp, conn):
        base_id = _seed_library(conn, name="Base")
        _seed_library(conn, name="Extra")
        template_id = _seed_template(conn, "テンプレA", base_id)
        tmpl = template_repo.get(conn, template_id)
        dialog = TemplateEditDialog(conn, tmpl)

        initial_count = len(dialog._row_widgets)
        dialog._on_add_reagent()
        assert len(dialog._row_widgets) == initial_count + 1

    def test_empty_name_shows_warning_and_does_not_save(self, qapp, conn, monkeypatch):
        base_id = _seed_library(conn)
        template_id = _seed_template(conn, "テンプレA", base_id)
        tmpl = template_repo.get(conn, template_id)
        dialog = TemplateEditDialog(conn, tmpl)

        warnings = []
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a))
        dialog._name_input.setText("")
        dialog._on_save()

        assert warnings
        assert template_repo.get(conn, template_id).name == "テンプレA"


class TestListDialogEditIntegration:
    def test_edit_then_accept_refreshes_list_with_new_name(self, qapp, conn, monkeypatch):
        base_id = _seed_library(conn)
        _seed_template(conn, "元の名前", base_id)
        list_dialog = TemplateListDialog(conn)
        list_dialog._list.setCurrentRow(0)

        def fake_exec(self_dialog):
            self_dialog._name_input.setText("新しい名前")
            self_dialog._on_save()
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(TemplateEditDialog, "exec", fake_exec)
        list_dialog._on_edit()

        assert list_dialog._list.item(0).text() == "新しい名前"
