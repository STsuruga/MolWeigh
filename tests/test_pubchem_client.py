import requests

import pytest

from molweigh.core import pubchem_client
from molweigh.core.pubchem_client import PubChemError, search_compound


class FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._json_data = json_data if json_data is not None else {}

    def json(self):
        return self._json_data


CID_JSON = {"IdentifierList": {"CID": [2244]}}
PROPERTY_JSON = {
    "PropertyTable": {
        "Properties": [
            {
                "CID": 2244,
                "MolecularFormula": "C9H8O4",
                "MolecularWeight": "180.16",
                "CanonicalSMILES": "CC(=O)OC1=CC=CC=C1C(=O)O",
            }
        ]
    }
}
DENSITY_VIEW_JSON = {
    "Record": {
        "Section": [
            {
                "TOCHeading": "Chemical and Physical Properties",
                "Section": [
                    {
                        "TOCHeading": "Experimental Properties",
                        "Section": [
                            {
                                "TOCHeading": "Density",
                                "Information": [
                                    {
                                        "Value": {
                                            "StringWithMarkup": [
                                                {"String": "1.4 g/cu cm"}
                                            ]
                                        }
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }
}


def _install_fake_get(monkeypatch, responses: dict[str, FakeResponse], default: FakeResponse | None = None):
    def fake_get(url, timeout=None):
        for marker, response in responses.items():
            if marker in url:
                return response
        if default is not None:
            return default
        raise AssertionError(f"unexpected URL requested: {url}")

    monkeypatch.setattr(pubchem_client.requests, "get", fake_get)


class TestSearchCompoundSuccess:
    def test_returns_compound_with_density(self, monkeypatch):
        _install_fake_get(
            monkeypatch,
            {
                "/cids/JSON": FakeResponse(200, CID_JSON),
                "/property/": FakeResponse(200, PROPERTY_JSON),
                "pug_view": FakeResponse(200, DENSITY_VIEW_JSON),
            },
        )
        result = search_compound("aspirin")
        assert result.cid == 2244
        assert result.formula == "C9H8O4"
        assert result.molecular_weight == pytest.approx(180.16)
        assert result.smiles == "CC(=O)OC1=CC=CC=C1C(=O)O"
        assert result.density == pytest.approx(1.4)

    def test_density_missing_is_none_not_error(self, monkeypatch):
        _install_fake_get(
            monkeypatch,
            {
                "/cids/JSON": FakeResponse(200, CID_JSON),
                "/property/": FakeResponse(200, PROPERTY_JSON),
                "pug_view": FakeResponse(404, {}),
            },
        )
        result = search_compound("aspirin")
        assert result.density is None


class TestSearchCompoundNotFound:
    def test_cid_404_returns_none(self, monkeypatch):
        _install_fake_get(monkeypatch, {"/cids/JSON": FakeResponse(404, {})})
        assert search_compound("not-a-real-compound-xyz") is None

    def test_empty_cid_list_returns_none(self, monkeypatch):
        _install_fake_get(
            monkeypatch, {"/cids/JSON": FakeResponse(200, {"IdentifierList": {"CID": []}})}
        )
        assert search_compound("nothing") is None


class TestErrors:
    def test_cid_server_error_raises(self, monkeypatch):
        _install_fake_get(monkeypatch, {"/cids/JSON": FakeResponse(500, {})})
        with pytest.raises(PubChemError):
            search_compound("aspirin")

    def test_property_fetch_failure_raises(self, monkeypatch):
        _install_fake_get(
            monkeypatch,
            {
                "/cids/JSON": FakeResponse(200, CID_JSON),
                "/property/": FakeResponse(500, {}),
            },
        )
        with pytest.raises(PubChemError):
            search_compound("aspirin")

    def test_network_error_raises_pubchem_error(self, monkeypatch):
        def raise_connection_error(url, timeout=None):
            raise requests.ConnectionError("network down")

        monkeypatch.setattr(pubchem_client.requests, "get", raise_connection_error)
        with pytest.raises(PubChemError):
            search_compound("aspirin")


class TestParseDensityValue:
    def test_extracts_nested_value(self):
        assert pubchem_client._parse_density_value(DENSITY_VIEW_JSON) == pytest.approx(1.4)

    def test_no_density_section_returns_none(self):
        assert pubchem_client._parse_density_value({"Record": {"Section": []}}) is None
