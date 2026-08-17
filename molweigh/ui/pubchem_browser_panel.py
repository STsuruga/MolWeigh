"""ブラウザを別途起動せずにPubChemを調べられる、開閉式の埋め込み検索パネル。

構造入力パネルと同様、初期状態は折りたたみ。展開して初めて埋め込み
ブラウザ(QWebEngineView)を読み込む(常時起動はしない)。
"""

from __future__ import annotations

from urllib.parse import quote

from PySide6.QtCore import QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget

from . import theme

PUBCHEM_HOME_URL = "https://pubchem.ncbi.nlm.nih.gov/"
PUBCHEM_SEARCH_URL = "https://pubchem.ncbi.nlm.nih.gov/#query={query}"


class PubChemBrowserPanel(QFrame):
    """開閉式のPubChem埋め込みブラウザパネル。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(theme.card_frame_style("PubChemBrowserPanel"))
        self._view: QWebEngineView | None = None
        self._expanded = False
        self._pending_query: str | None = None

        self._toggle_button = QPushButton("▶ オンラインで試薬情報を調べる")
        self._toggle_button.clicked.connect(self._on_toggle)

        self._body = QWidget()
        self._body.hide()
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(0, 8, 0, 0)
        body_layout.setSpacing(8)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("PubChemで検索…")
        self._search_input.returnPressed.connect(self._on_search)

        search_button = QPushButton("検索")
        search_button.setStyleSheet(theme.accent_button_style())
        search_button.clicked.connect(self._on_search)

        search_row = QHBoxLayout()
        search_row.addWidget(self._search_input)
        search_row.addWidget(search_button)

        self._view_container = QVBoxLayout()
        self._view_container.setContentsMargins(0, 0, 0, 0)

        body_layout.addLayout(search_row)
        body_layout.addLayout(self._view_container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.addWidget(self._toggle_button)
        outer.addWidget(self._body)

    def _on_toggle(self) -> None:
        self._expanded = not self._expanded
        if self._expanded:
            self._body.show()
            self._toggle_button.setText("▼ オンラインで試薬情報を調べる")
            if self._view is None:
                self._create_view()
        else:
            self._body.hide()
            self._toggle_button.setText("▶ オンラインで試薬情報を調べる")

    def _create_view(self) -> None:
        self._view = QWebEngineView(self)
        self._view.setMinimumHeight(420)
        self._view_container.addWidget(self._view)
        if self._pending_query:
            self._navigate_to_search(self._pending_query)
            self._pending_query = None
        else:
            self._view.setUrl(QUrl(PUBCHEM_HOME_URL))

    def _on_search(self) -> None:
        query = self._search_input.text().strip()
        if not query:
            return
        if self._view is None:
            self._pending_query = query
            if not self._expanded:
                self._on_toggle()
            return
        self._navigate_to_search(query)

    def _navigate_to_search(self, query: str) -> None:
        self._view.setUrl(QUrl(PUBCHEM_SEARCH_URL.format(query=quote(query))))
