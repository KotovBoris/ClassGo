"""Тесты «полезных мелочей» ST-5: CSV списка, экстренные телефоны, ICS-календарь.

Требования к поведению:
- CSV участников отдаётся как файл (text/csv) с BOM и колонками туроператора;
- экстренные телефоны — плоский сводный список без дублей;
- ICS — валидный календарь с событием на дату выезда.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from conftest import make_excursion


def test_csv_unknown_excursion_404(client: TestClient) -> None:
    assert client.get("/api/v1/excursions/999999/participants.csv").status_code == 404


def test_emergency_contacts_unknown_404(client: TestClient) -> None:
    assert client.get("/api/v1/excursions/999999/emergency-contacts").status_code == 404


def test_ics_unknown_excursion_404(client: TestClient) -> None:
    assert client.get("/api/v1/excursions/999999/calendar.ics").status_code == 404
