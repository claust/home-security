from __future__ import annotations

from fastapi.testclient import TestClient


def test_wifi_overview_reports_counts(app) -> None:  # noqa: ANN001 - fixture
    with TestClient(app) as client:
        response = client.get("/wifi/stats/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["total_observations"] > 0
    assert body["distinct_addresses"] > 0
    # The synthetic archive makes every other MAC randomized.
    assert 0 < body["randomized_addresses"] <= body["distinct_addresses"]
    assert body["scanner_count"] == 3
    assert body["first_observed_utc"] is not None


def test_wifi_observations_are_paginated(app) -> None:  # noqa: ANN001 - fixture
    with TestClient(app) as client:
        first = client.get("/wifi/observations", params={"limit": 5}).json()
        assert len(first["items"]) == 5
        assert first["next_cursor"]

        second = client.get(
            "/wifi/observations",
            params={"limit": 5, "cursor": first["next_cursor"]},
        ).json()

    assert len(second["items"]) == 5
    first_keys = {
        (i["observed_at_utc"], i["scanner_id"], i["address"]) for i in first["items"]
    }
    second_keys = {
        (i["observed_at_utc"], i["scanner_id"], i["address"]) for i in second["items"]
    }
    assert first_keys.isdisjoint(second_keys)


def test_wifi_observation_shape(app) -> None:  # noqa: ANN001 - fixture
    with TestClient(app) as client:
        item = client.get("/wifi/observations", params={"limit": 1}).json()["items"][0]
    assert set(item) == {
        "observed_at_utc",
        "scanner_id",
        "address",
        "frame_type",
        "ssid",
        "rssi",
        "channel",
        "is_randomized_mac",
        "information_elements",
    }
    assert item["frame_type"] in {"probe_req", "beacon", "probe_resp", "data"}
    assert 1 <= item["channel"] <= 13
    assert "tag_order" in item["information_elements"]


def test_wifi_observations_filter_by_frame_type(app) -> None:  # noqa: ANN001 - fixture
    with TestClient(app) as client:
        body = client.get(
            "/wifi/observations", params={"frame_type": "beacon", "limit": 20}
        ).json()
    assert body["items"]
    assert all(item["frame_type"] == "beacon" for item in body["items"])


def test_wifi_addresses_filter_randomized(app) -> None:  # noqa: ANN001 - fixture
    with TestClient(app) as client:
        randomized = client.get(
            "/wifi/addresses", params={"randomized": "true", "limit": 25}
        ).json()
        stable = client.get(
            "/wifi/addresses", params={"randomized": "false", "limit": 25}
        ).json()
    assert randomized["items"]
    assert all(item["is_randomized_mac"] for item in randomized["items"])
    assert stable["items"]
    assert all(not item["is_randomized_mac"] for item in stable["items"])


def test_wifi_address_detail_and_timeline(app) -> None:  # noqa: ANN001 - fixture
    with TestClient(app) as client:
        listing = client.get("/wifi/addresses", params={"limit": 1}).json()
        address = listing["items"][0]["address"]

        detail = client.get(f"/wifi/addresses/{address}")
        assert detail.status_code == 200
        summary = detail.json()
        assert summary["address"] == address
        assert summary["observations"] >= 1
        assert summary["channels"] == sorted(summary["channels"])
        assert summary["frame_types"]

        timeline = client.get(f"/wifi/addresses/{address}/observations").json()
    assert timeline["items"]
    assert all(item["address"] == address for item in timeline["items"])


def test_wifi_unknown_address_is_404(app) -> None:  # noqa: ANN001 - fixture
    with TestClient(app) as client:
        response = client.get("/wifi/addresses/zz:zz:zz:zz:zz:zz")
    assert response.status_code == 404
