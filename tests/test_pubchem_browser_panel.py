from molweigh.ui.pubchem_browser_panel import PUBCHEM_HOME_URL, PubChemBrowserPanel


class TestInitialState:
    def test_view_is_created_immediately_at_home_url(self, qapp):
        panel = PubChemBrowserPanel()
        assert panel._view is not None
        assert panel._view.url().toString() == PUBCHEM_HOME_URL


class TestSearch:
    def test_search_navigates_to_query(self, qapp):
        panel = PubChemBrowserPanel()
        panel._search_input.setText("aspirin")
        panel._on_search()
        assert "aspirin" in panel._view.url().toString()

    def test_empty_search_does_nothing(self, qapp):
        panel = PubChemBrowserPanel()
        panel._search_input.setText("   ")
        panel._on_search()
        assert panel._view.url().toString() == PUBCHEM_HOME_URL
