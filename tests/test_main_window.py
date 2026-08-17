import sqlite3

import pytest
from PySide6.QtWidgets import QInputDialog, QMessageBox

from molweigh.core.compound_source import CompoundInfo
from molweigh.db import library_repo, schema, template_repo
from molweigh.db.library_repo import LibraryEntry
from molweigh.ui.main_window import DEFAULT_COLUMN_COUNT, MainWindow
from molweigh.ui.reagent_table import ReagentColumn


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    schema.migrate(connection)
    yield connection
    connection.close()


class TestMainWindowBasics:
    def test_starts_with_only_unselected_template(self, qapp, conn):
        window = MainWindow(conn)
        assert window._template_combo.count() == 1
        assert window._template_combo.itemData(0) is None

    def test_starts_with_default_blank_columns(self, qapp, conn):
        window = MainWindow(conn)
        columns = window._reagent_table.columns()
        assert len(columns) == DEFAULT_COLUMN_COUNT
        assert all(c.name == "" and c.fw is None for c in columns)

    def test_compound_resolved_fills_first_blank_column(self, qapp, conn):
        window = MainWindow(conn)
        info = CompoundInfo(
            name="DMAP", formula="C7H10N2", molecular_weight=122.17,
            density=None, smiles=None, source="pubchem", library_id=5,
        )
        window._on_compound_resolved(info)
        columns = window._reagent_table.columns()
        assert len(columns) == DEFAULT_COLUMN_COUNT
        assert columns[0].name == "DMAP"
        assert columns[0].library_id == 5

    def test_compound_resolved_appends_once_all_blanks_filled(self, qapp, conn):
        window = MainWindow(conn)
        for i in range(DEFAULT_COLUMN_COUNT):
            window._on_compound_resolved(
                CompoundInfo(
                    name=f"R{i}", formula=None, molecular_weight=100.0 + i,
                    density=None, smiles=None, source="pubchem",
                )
            )
        window._on_compound_resolved(
            CompoundInfo(
                name="Overflow", formula=None, molecular_weight=1.0,
                density=None, smiles=None, source="pubchem",
            )
        )
        columns = window._reagent_table.columns()
        assert len(columns) == DEFAULT_COLUMN_COUNT + 1
        assert columns[-1].name == "Overflow"

    def test_column_selected_updates_structure_panel(self, qapp, conn):
        window = MainWindow(conn)
        window._on_compound_resolved(
            CompoundInfo(
                name="Ethanol", formula="C2H6O", molecular_weight=46.069,
                density=None, smiles="CCO", source="pubchem",
            )
        )
        window._on_column_selected(0)
        assert window._structure_panel._name_label.text() == "Ethanol"

    def test_add_reagent_requested_appends_blank_column(self, qapp, conn):
        window = MainWindow(conn)
        window._on_add_reagent_requested()
        columns = window._reagent_table.columns()
        assert len(columns) == DEFAULT_COLUMN_COUNT + 1
        assert columns[-1].name == ""
        assert columns[-1].fw is None

    def test_structure_input_panel_added_to_table_fills_first_blank(self, qapp, conn):
        window = MainWindow(conn)
        window._structure_input_panel._on_smiles_for_add("CCO")
        columns = window._reagent_table.columns()
        assert len(columns) == DEFAULT_COLUMN_COUNT
        assert columns[0].formula == "C2H6O"
        assert columns[0].source == "smiles"

    def test_close_event_shuts_down_structure_input_panel(self, qapp, conn):
        window = MainWindow(conn)
        window._structure_input_panel._on_toggle()
        assert window._structure_input_panel._ketcher is not None
        window.close()  # 例外が出なければOK


class TestSaveColumnToLibrary:
    def test_saves_column_with_fw_and_updates_library_id(self, qapp, conn, monkeypatch):
        window = MainWindow(conn)
        window._reagent_table.replace_column(
            0, ReagentColumn(name="", formula="C6H12O6", fw=180.156, source="formula_parser")
        )
        monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("グルコース", True))

        window._on_save_column_requested(0)

        column = window._reagent_table.columns()[0]
        assert column.library_id is not None
        assert column.name == "グルコース"
        saved = library_repo.get(conn, column.library_id)
        assert saved.name == "グルコース"
        assert saved.molecular_weight == pytest.approx(180.156)

    def test_missing_fw_shows_warning_and_does_not_save(self, qapp, conn, monkeypatch):
        window = MainWindow(conn)
        window._reagent_table.replace_column(0, ReagentColumn(name="NoFw", fw=None))
        warnings = []
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a))

        window._on_save_column_requested(0)

        assert warnings
        assert window._reagent_table.columns()[0].library_id is None

    def test_cancelled_name_dialog_does_not_save(self, qapp, conn, monkeypatch):
        window = MainWindow(conn)
        window._reagent_table.replace_column(0, ReagentColumn(name="X", fw=100.0))
        monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("", False))

        window._on_save_column_requested(0)

        assert window._reagent_table.columns()[0].library_id is None


class TestLibraryDialogIntegration:
    def test_open_library_creates_dialog_once(self, qapp, conn):
        window = MainWindow(conn)
        window._on_open_library()
        first = window._library_dialog
        assert first is not None
        window._on_open_library()
        assert window._library_dialog is first

    def test_library_entry_selected_fills_first_blank_column(self, qapp, conn):
        entry_id = library_repo.create(
            conn, LibraryEntry(id=None, name="DMAP", molecular_weight=122.17, source="pubchem", formula="C7H10N2")
        )
        window = MainWindow(conn)
        entry = library_repo.get(conn, entry_id)
        window._on_library_entry_selected(entry)

        columns = window._reagent_table.columns()
        assert len(columns) == DEFAULT_COLUMN_COUNT
        assert columns[0].name == "DMAP"
        assert columns[0].library_id == entry_id
        assert columns[0].fw == pytest.approx(122.17)


class TestSaveTemplate:
    def test_saves_only_columns_with_library_id(self, qapp, conn, monkeypatch):
        base_id = library_repo.create(
            conn, LibraryEntry(id=None, name="Base", molecular_weight=458.27, source="pubchem")
        )
        window = MainWindow(conn)
        window._reagent_table.add_column(
            ReagentColumn(name="Base", fw=458.27, weight_value=200, library_id=base_id)
        )
        window._reagent_table.add_column(
            ReagentColumn(name="Unsaved", fw=100.0, target_eq=2.0, library_id=None)
        )

        monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("My template", True))
        infos = []
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: infos.append(a))

        window._on_save_template()

        templates = template_repo.list_all(conn)
        assert len(templates) == 1
        assert templates[0].name == "My template"
        assert len(templates[0].payload["reagents"]) == 1
        assert templates[0].payload["reagents"][0]["library_id"] == base_id
        assert infos, "未保存試薬がある旨の通知が出るはず"

    def test_all_unsaved_columns_warns_and_does_not_save(self, qapp, conn, monkeypatch):
        window = MainWindow(conn)
        window._reagent_table.add_column(ReagentColumn(name="Unsaved", fw=100.0, library_id=None))

        monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("T", True))
        warnings = []
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a))

        window._on_save_template()

        assert template_repo.list_all(conn) == []
        assert warnings

    def test_cancelled_dialog_does_not_save(self, qapp, conn, monkeypatch):
        window = MainWindow(conn)
        window._reagent_table.add_column(ReagentColumn(name="X", fw=1.0, library_id=1))
        monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("", False))

        window._on_save_template()

        assert template_repo.list_all(conn) == []


class TestLoadTemplate:
    def test_loads_columns_from_library_refs(self, qapp, conn):
        base_id = library_repo.create(
            conn, LibraryEntry(id=None, name="Base", molecular_weight=458.27, source="pubchem")
        )
        dmap_id = library_repo.create(
            conn, LibraryEntry(id=None, name="DMAP", molecular_weight=122.17, source="pubchem")
        )
        template_id = template_repo.create(
            conn,
            "アミド化",
            {
                "reagents": [
                    {"name": "Base", "library_id": base_id, "role": "base", "eq": 1.0},
                    {"name": "DMAP", "library_id": dmap_id, "role": "additive", "eq": 6.0},
                ]
            },
        )

        window = MainWindow(conn)
        index = window._template_combo.findData(template_id)
        window._template_combo.setCurrentIndex(index)

        window._on_load_template()

        columns = window._reagent_table.columns()
        assert [c.name for c in columns] == ["Base", "DMAP"]
        assert columns[1].target_eq == pytest.approx(6.0)
        assert columns[0].library_id == base_id

    def test_no_selection_shows_info(self, qapp, conn, monkeypatch):
        window = MainWindow(conn)
        columns_before = window._reagent_table.columns()
        infos = []
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: infos.append(a))
        window._on_load_template()
        assert infos
        assert window._reagent_table.columns() == columns_before

    def test_missing_library_entry_is_skipped_with_notice(self, qapp, conn, monkeypatch):
        template_id = template_repo.create(
            conn,
            "壊れたテンプレート",
            {"reagents": [{"name": "Ghost", "library_id": 9999, "role": "base", "eq": 1.0}]},
        )
        window = MainWindow(conn)
        index = window._template_combo.findData(template_id)
        window._template_combo.setCurrentIndex(index)

        infos = []
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: infos.append(a))

        window._on_load_template()

        assert window._reagent_table.columns() == []
        assert infos
