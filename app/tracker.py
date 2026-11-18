from typing import Any

import httpx


class TrackerError(RuntimeError):
    def __init__(self, status: int | None = None):
        self.status = status
        super().__init__("Keitaro is unavailable" if status is None else f"Keitaro HTTP {status}")


class Tracker:
    def __init__(self, client: httpx.Client):
        self.client = client

    def request(
        self, method: str, path: str, *, params: dict | None = None, body: dict | None = None
    ) -> Any:
        try:
            response = self.client.request(method, path, params=params, json=body)
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise TrackerError(error.response.status_code) from None
        except httpx.RequestError:
            raise TrackerError() from None
        try:
            return response.json() if response.content else None
        except ValueError:
            raise TrackerError() from None

    def get(self, path: str, **params: str | int) -> Any:
        return self.request("GET", path, params=params)


def list_offer_allocations(stream: dict) -> list[dict]:
    return [
        {
            "offer_id": int(offer["offer_id"]),
            "share": int(offer["share"]),
            "state": offer.get("state") or "active",
        }
        for offer in stream.get("offers") or []
    ]


def create_campaign(tracker: Tracker, settings: dict, country: str, offer_id: int) -> dict:
    campaign = tracker.request("POST", "campaigns", body={
        **settings, "type": "position", "state": "disabled",
    })
    campaign_id = campaign["id"]
    try:
        tracker.request("POST", "streams", body={
            "campaign_id": campaign_id,
            "name": f"{country} → Google",
            "type": "regular",
            "position": 1,
            "schema": "redirect",
            "action_type": "http",
            "action_payload": "https://www.google.com/",
            "filters": [{"name": "country", "mode": "accept", "payload": [country]}],
        })
        tracker.request("POST", "streams", body={
            "campaign_id": campaign_id,
            "name": "Офферы",
            "type": "default",
            "position": 2,
            "schema": "landings",
            "action_type": "http",
            "offers": [{"offer_id": offer_id, "share": 100, "state": "active"}],
        })
        return tracker.request("PUT", f"campaigns/{campaign_id}", body={"state": "active"})
    except TrackerError as error:
        raise IncompleteCampaign(campaign_id, error.status) from None


class IncompleteCampaign(TrackerError):
    def __init__(self, campaign_id: int, status: int | None):
        self.campaign_id = campaign_id
        super().__init__(status)
