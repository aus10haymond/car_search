import base64
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scraper.urls import build_search_url


def test_url_contains_cvnaid():
    url = build_search_url("Toyota", "RAV4", 2021, 2025)
    assert "cvnaid=" in url, "URL must contain the cvnaid parameter"


def test_base64_decodes_correctly():
    url = build_search_url("Toyota", "RAV4", 2021, 2025)
    encoded = url.split("cvnaid=")[1].split("&")[0]
    decoded = json.loads(base64.b64decode(encoded).decode())
    filters = decoded["filters"]
    assert filters["makes"][0]["name"] == "Toyota"
    assert filters["makes"][0]["parentModels"][0]["name"] == "RAV4"
    assert filters["year"]["min"] == 2021
    assert filters["year"]["max"] == 2025


def test_different_make_model():
    url = build_search_url("Honda", "CR-V", 2022, 2024)
    encoded = url.split("cvnaid=")[1].split("&")[0]
    decoded = json.loads(base64.b64decode(encoded).decode())
    filters = decoded["filters"]
    assert filters["makes"][0]["name"] == "Honda"
    assert filters["makes"][0]["parentModels"][0]["name"] == "CR-V"
    assert filters["year"]["min"] == 2022
    assert filters["year"]["max"] == 2024


def test_fuel_type_filter():
    url = build_search_url("Toyota", "RAV4", 2021, 2025, fuel_type="Hybrid")
    encoded = url.split("cvnaid=")[1].split("&")[0]
    decoded = json.loads(base64.b64decode(encoded).decode())
    assert decoded["filters"]["fuelTypes"] == ["Hybrid"]


def test_no_fuel_type_filter():
    url = build_search_url("Toyota", "RAV4", 2021, 2025, fuel_type=None)
    encoded = url.split("cvnaid=")[1].split("&")[0]
    decoded = json.loads(base64.b64decode(encoded).decode())
    assert "fuelTypes" not in decoded["filters"]


def test_page_1_not_in_cvnaid():
    url = build_search_url("Toyota", "RAV4", 2021, 2025, page=1)
    encoded = url.split("cvnaid=")[1]
    decoded = json.loads(base64.b64decode(encoded).decode())
    assert "page" not in decoded, "page key should be absent for page=1"


def test_page_2_encoded_in_cvnaid():
    url = build_search_url("Toyota", "RAV4", 2021, 2025, page=2)
    assert "&page=" not in url, "page must not appear as a query param"
    encoded = url.split("cvnaid=")[1]
    decoded = json.loads(base64.b64decode(encoded).decode())
    assert decoded["page"] == 2, "page=2 must be encoded inside cvnaid JSON"


def test_page_5_encoded_in_cvnaid():
    url = build_search_url("Kia", "Sportage", 2021, 2025, page=5)
    assert "&page=" not in url, "page must not appear as a query param"
    encoded = url.split("cvnaid=")[1]
    decoded = json.loads(base64.b64decode(encoded).decode())
    assert decoded["page"] == 5, "page=5 must be encoded inside cvnaid JSON"


def test_url_base():
    url = build_search_url("Subaru", "Forester", 2021, 2025)
    assert url.startswith("https://www.carvana.com/cars/filters?cvnaid=")
