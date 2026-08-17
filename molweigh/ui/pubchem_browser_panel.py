"""ブラウザを別途起動せずにPubChemを調べられる、常設の埋め込み検索パネル。"""

from __future__ import annotations

from urllib.parse import quote

from PySide6.QtCore import QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from . import theme

PUBCHEM_HOME_URL = "https://pubchem.ncbi.nlm.nih.gov/"
PUBCHEM_SEARCH_URL = "https://pubchem.ncbi.nlm.nih.gov/#query={query}"


class PubChemBrowserPanel(QFrame):
    """PubChemの埋め込みブラウザパネル。常時表示され、検索するとその場で読み込む。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(theme.card_frame_style("PubChemBrowserPanel"))

        title_label = QLabel("オンラインで試薬情報を調べる")
        title_label.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {theme.TEXT_PRIMARY};")

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("PubChemで検索…")
        self._search_input.returnPressed.connect(self._on_search)

        search_button = QPushButton("検索")
        search_button.setStyleSheet(theme.accent_button_style())
        search_button.clicked.connect(self._on_search)

        search_row = QHBoxLayout()
        search_row.addWidget(self._search_input)
        search_row.addWidget(search_button)

        self._view = QWebEngineView(self)
        self._view.setMinimumHeight(200)
        self._view.setUrl(QUrl(PUBCHEM_HOME_URL))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.addWidget(title_label)
        outer.addLayout(search_row)
        outer.addWidget(self._view, 1)

    def _on_search(self) -> None:
        query = self._search_input.text().strip()
        if not query:
            return
        self._navigate_to_search(query)

    def _navigate_to_search(self, query: str) -> None:
        self._view.setUrl(QUrl(PUBCHEM_SEARCH_URL.format(query=quote(query))))
