import sqlite3

import pytest

from molweigh.db import schema, template_repo
from molweigh.ui.template_list_panel import TemplateListPanel


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    schema.migrate(connection)
    yield connection
    connection.close()


class TestTemplateListPanel:
    def test_starts_empty_shows_hint(self, qapp, conn):
        panel = TemplateListPanel(conn)
        assert panel._list.isHidden()
        assert not panel._empty_hint.isHidden()

    def test_refresh_populates_list(self, qapp, conn):
        template_repo.create(conn, "アミド化", {"reagents": [{"name": "A"}, {"name": "B"}]})
        panel = TemplateListPanel(conn)
        assert panel._list.count() == 1
        assert "アミド化" in panel._list.item(0).text()
        assert "2件" in panel._list.item(0).text()
        assert not panel._list.isHidden()
        assert panel._empty_hint.isHidden()

    def test_double_click_emits_template_selected(self, qapp, conn):
        template_repo.create(conn, "アミド化", {"reagents": []})
        panel = TemplateListPanel(conn)
        received = []
        panel.template_selected.connect(received.append)

        panel._on_item_double_clicked(panel._list.item(0))

        assert len(received) == 1
        assert received[0].name == "アミド化"

    def test_refresh_reflects_newly_created_template(self, qapp, conn):
        panel = TemplateListPanel(conn)
        assert panel._list.count() == 0

        template_repo.create(conn, "新規", {"reagents": []})
        panel.refresh()

        assert panel._list.count() == 1
