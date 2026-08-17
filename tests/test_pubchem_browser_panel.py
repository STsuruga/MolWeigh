from molweigh.ui.pubchem_browser_panel import PUBCHEM_HOME_URL, PubChemBrowserPanel


class TestInitialState:
    def test_starts_collapsed_without_view(self, qapp):
        panel = PubChemBrowserPanel()
        assert panel._expanded is False
        assert panel._view is None
        assert panel._body.isHidden()


class TestToggle:
    def test_expanding_creates_view_at_home_url(self, qapp):
        panel = PubChemBrowserPanel()
        panel._on_toggle()
        assert panel._expanded is True
        assert panel._view is not None
        assert panel._view.url().toString() == PUBCHEM_HOME_URL
        assert not panel._body.isHidden()

    def test_collapsing_keeps_view_instance(self, qapp):
        panel = PubChemBrowserPanel()
        panel._on_toggle()
        view = panel._view
        panel._on_toggle()
        assert panel._expanded is False
        assert panel._body.isHidden()
        assert panel._view is view

    def test_reexpanding_does_not_recreate_view(self, qapp):
        panel = PubChemBrowserPanel()
        panel._on_toggle()
        first = panel._view
        panel._on_toggle()
        panel._on_toggle()
        assert panel._view is first


class TestSearch:
    def test_search_while_collapsed_expands_and_navigates(self, qapp):
        panel = PubChemBrowserPanel()
        panel._search_input.setText("aspirin")
        panel._on_search()

        assert panel._expanded is True
        assert panel._view is not None
        assert "aspirin" in panel._view.url().toString()

    def test_search_while_expanded_navigates_directly(self, qapp):
        panel = PubChemBrowserPanel()
        panel._on_toggle()
        panel._search_input.setText("ethanol")
        panel._on_search()
        assert "ethanol" in panel._view.url().toString()

    def test_empty_search_does_nothing(self, qapp):
        panel = PubChemBrowserPanel()
        panel._search_input.setText("   ")
        panel._on_search()
        assert panel._expanded is False
        assert panel._view is None
