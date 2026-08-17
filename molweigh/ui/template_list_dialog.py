"""テンプレート一覧ウィンドウ。一覧表示・呼び出し・削除・(試薬構成込みの)編集を行う。

メインウィンドウの「テンプレートを呼び出し」「テンプレート一覧」の両方から
この同じウィンドウを開く(呼び出しと管理を1つの窓に統合している)。
"""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..db import library_repo, template_repo
from ..db.template_repo import Template
from . import theme


class TemplateListDialog(QDialog):
    """テンプレートの一覧・呼び出し・編集・削除を行う非モーダルウィンドウ。"""

    template_loaded = Signal(object)  # Template

    def __init__(self, conn: sqlite3.Connection, parent: QWidget | None = None):
        super().__init__(parent)
        self._conn = conn
        self.setWindowTitle("テンプレート一覧")
        self.resize(420, 480)

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(lambda _item: self._on_load())

        load_button = QPushButton("呼び出し")
        load_button.setStyleSheet(theme.accent_button_style())
        load_button.clicked.connect(self._on_load)
        edit_button = QPushButton("編集")
        edit_button.clicked.connect(self._on_edit)
        delete_button = QPushButton("削除")
        delete_button.setStyleSheet(theme.danger_ghost_button_style())
        delete_button.clicked.connect(self._on_delete)
        close_button = QPushButton("閉じる")
        close_button.clicked.connect(self.close)

        button_row = QHBoxLayout()
        button_row.addWidget(load_button)
        button_row.addWidget(edit_button)
        button_row.addWidget(delete_button)
        button_row.addStretch()
        button_row.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self._list, 1)
        layout.addLayout(button_row)

        self.refresh()

    def refresh(self) -> None:
        self._list.clear()
        for tmpl in template_repo.list_all(self._conn):
            item = QListWidgetItem(tmpl.name)
            item.setData(Qt.ItemDataRole.UserRole, tmpl)
            self._list.addItem(item)

    def _selected_template(self) -> Template | None:
        item = self._list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _on_load(self) -> None:
        tmpl = self._selected_template()
        if tmpl is None:
            return
        self.template_loaded.emit(tmpl)

    def _on_edit(self) -> None:
        tmpl = self._selected_template()
        if tmpl is None:
            return
        dialog = TemplateEditDialog(self._conn, tmpl, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _on_delete(self) -> None:
        tmpl = self._selected_template()
        if tmpl is None:
            return
        confirm = QMessageBox.question(
            self, "テンプレートを削除", f"「{tmpl.name}」を削除しますか?"
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        template_repo.delete(self._conn, tmpl.id)
        self.refresh()


class TemplateEditDialog(QDialog):
    """テンプレート名と、含まれる試薬構成(eq値・削除)を編集する。"""

    def __init__(self, conn: sqlite3.Connection, template: Template, parent: QWidget | None = None):
        super().__init__(parent)
        self._conn = conn
        self._template = template
        self.setWindowTitle("テンプレートを編集")
        self.resize(420, 480)

        self._name_input = QLineEdit(template.name)

        self._rows_layout = QVBoxLayout()
        self._rows_layout.setSpacing(6)
        self._row_widgets: list[_ReagentRow] = []
        for reagent in template.payload.get("reagents", []):
            self._add_row(reagent)

        add_button = QPushButton("+ ライブラリから追加")
        add_button.clicked.connect(self._on_add_reagent)

        save_button = QPushButton("保存")
        save_button.setStyleSheet(theme.accent_button_style())
        save_button.clicked.connect(self._on_save)
        cancel_button = QPushButton("キャンセル")
        cancel_button.clicked.connect(self.reject)

        button_row = QHBoxLayout()
        button_row.addStretch()
        button_row.addWidget(save_button)
        button_row.addWidget(cancel_button)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("テンプレート名"))
        layout.addWidget(self._name_input)
        layout.addWidget(QLabel("試薬構成"))
        layout.addLayout(self._rows_layout)
        layout.addWidget(add_button)
        layout.addStretch()
        layout.addLayout(button_row)

    def _add_row(self, reagent: dict) -> None:
        row = _ReagentRow(self._conn, reagent, is_base=(len(self._row_widgets) == 0))
        row.remove_requested.connect(self._on_remove_row)
        self._row_widgets.append(row)
        self._rows_layout.addWidget(row)

    def _on_remove_row(self, row: "_ReagentRow") -> None:
        self._row_widgets.remove(row)
        self._rows_layout.removeWidget(row)
        row.setParent(None)
        row.deleteLater()

    def _on_add_reagent(self) -> None:
        entries = library_repo.list_all(self._conn, order_by_use_count=True)
        if not entries:
            QMessageBox.information(self, "ライブラリから追加", "ライブラリに試薬が登録されていません。")
            return
        entry = entries[0]
        self._add_row({"name": entry.name, "library_id": entry.id, "role": "additive", "eq": 1.0})

    def _on_save(self) -> None:
        name = self._name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "テンプレートを編集", "テンプレート名を入力してください。")
            return
        reagents = [row.to_payload() for row in self._row_widgets]
        self._template.name = name
        self._template.payload = {"reagents": reagents}
        template_repo.update(self._conn, self._template)
        self.accept()


class _ReagentRow(QWidget):
    """テンプレート編集ダイアログ内の1試薬分の行(名前・役割・eq・削除)。"""

    remove_requested = Signal(object)

    def __init__(self, conn: sqlite3.Connection, reagent: dict, is_base: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self._library_id = reagent.get("library_id")

        entry = library_repo.get(conn, self._library_id) if self._library_id is not None else None
        display_name = entry.name if entry is not None else reagent.get("name", "(不明な試薬)")

        self._name_label = QLabel(display_name)
        self._name_label.setMinimumWidth(120)

        self._role_combo = QComboBox()
        self._role_combo.addItems(["base", "additive"])
        self._role_combo.setCurrentText("base" if is_base else reagent.get("role", "additive"))
        self._role_combo.setEnabled(not is_base)

        self._eq_spin = QDoubleSpinBox()
        self._eq_spin.setRange(0.01, 1000.0)
        self._eq_spin.setDecimals(2)
        self._eq_spin.setValue(float(reagent.get("eq", 1.0)))
        self._eq_spin.setEnabled(not is_base)

        remove_button = QPushButton("×")
        remove_button.setFixedWidth(24)
        remove_button.setStyleSheet(theme.danger_ghost_button_style())
        remove_button.clicked.connect(lambda: self.remove_requested.emit(self))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._name_label, 1)
        layout.addWidget(self._role_combo)
        layout.addWidget(self._eq_spin)
        layout.addWidget(remove_button)

    def to_payload(self) -> dict:
        return {
            "name": self._name_label.text(),
            "library_id": self._library_id,
            "role": self._role_combo.currentText(),
            "eq": 1.0 if self._role_combo.currentText() == "base" else self._eq_spin.value(),
        }
