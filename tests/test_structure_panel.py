import pytest

from molweigh.core.compound_source import CompoundInfo
from molweigh.ui.structure_panel import StructurePanel


class TestStructurePanel:
    def test_initial_state_is_cleared(self, qapp):
        panel = StructurePanel()
        assert panel._name_label.text() == ""
        assert panel._image_label.text() == "未選択"

    def test_show_compound_with_smiles_renders_structure(self, qapp):
        panel = StructurePanel()
        info = CompoundInfo(
            name="Ethanol", formula="C2H6O", molecular_weight=46.069,
            density=None, smiles="CCO", source="pubchem",
        )
        panel.show_compound(info)
        assert panel._name_label.text() == "Ethanol"
        assert panel._formula_label.text() == "C2H6O"
        assert panel._source_label.text() == "出典: PubChem"
        assert not panel._image_label.pixmap().isNull()
        assert panel._image_label.text() == ""

    def test_show_compound_without_smiles_shows_placeholder(self, qapp):
        panel = StructurePanel()
        info = CompoundInfo(
            name="Glucose", formula="C6H12O6", molecular_weight=180.156,
            density=None, smiles=None, source="formula_parser",
        )
        panel.show_compound(info)
        assert panel._image_label.text() == "構造式なし"
        assert panel._source_label.text() == "出典: 化学式入力"

    def test_show_compound_with_invalid_smiles_falls_back(self, qapp):
        panel = StructurePanel()
        info = CompoundInfo(
            name="Broken", formula=None, molecular_weight=1.0,
            density=None, smiles="not-a-smiles(((", source="smiles",
        )
        panel.show_compound(info)
        assert panel._image_label.text() == "構造式なし"

    def test_clear_resets_labels(self, qapp):
        panel = StructurePanel()
        info = CompoundInfo(
            name="Ethanol", formula="C2H6O", molecular_weight=46.069,
            density=None, smiles="CCO", source="pubchem",
        )
        panel.show_compound(info)
        panel.clear()
        assert panel._name_label.text() == ""
        assert panel._image_label.text() == "未選択"
