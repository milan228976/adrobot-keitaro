import json
from collections.abc import Iterator
from contextlib import asynccontextmanager
from hashlib import sha256
from pathlib import Path
from threading import Lock
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import httpx
from pydantic import BaseModel, Field, PositiveInt, StringConstraints, field_validator
import pycountry
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from .settings import Settings
from .storage import StreamDraft
from .tracker import IncompleteCampaign, Tracker, TrackerError, create_campaign, list_offer_allocations
from .weights import InvalidShares, distribute


STATIC = Path(__file__).with_name("static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    key = settings.keitaro_api_key.get_secret_value().strip()
    if not key:
        raise RuntimeError("Set KEITARO_API_KEY in your environment or .env")

    engine = create_engine(settings.database_url)
    try:
        with httpx.Client(
            base_url=str(settings.keitaro_url).rstrip("/") + "/admin_api/v1/",
            headers={"Api-Key": key, "Accept": "application/json"},
            timeout=httpx.Timeout(15, connect=5),
            follow_redirects=False,
        ) as client:
            app.state.tracker = Tracker(client)
            app.state.engine = engine
            app.state.edit_lock = Lock()
            yield
    finally:
        engine.dispose()


app = FastAPI(title="Adrobot · Keitaro", lifespan=lifespan)


@app.exception_handler(TrackerError)
async def tracker_error(request: Request, error: TrackerError):
    if isinstance(error, IncompleteCampaign):
        message = f"Создание компании #{error.campaign_id} прервалось. Проверьте её в Keitaro."
        status = 502
    elif error.status == 404:
        message, status = "Объект не найден в Keitaro.", 404
    else:
        suffix = f"HTTP {error.status}" if error.status else "сбой соединения или ответа"
        message, status = f"Запрос к Keitaro завершился ошибкой ({suffix}).", 502
    return JSONResponse({"detail": message}, status_code=status)


@app.exception_handler(InvalidShares)
async def shares_error(request: Request, error: InvalidShares):
    return JSONResponse({"detail": str(error)}, status_code=422)


def get_tracker(request: Request) -> Tracker:
    return request.app.state.tracker


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session:
        yield session


Keitaro = Annotated[Tracker, Depends(get_tracker)]
Database = Annotated[Session, Depends(get_session)]


class CampaignInput(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=140)]
    country: str
    domain_id: PositiveInt
    group_id: PositiveInt
    traffic_source_id: PositiveInt
    offer_id: PositiveInt

    @field_validator("country")
    @classmethod
    def country_code(cls, value: str) -> str:
        code = value.strip().upper()
        if len(code) != 2 or pycountry.countries.get(alpha_2=code) is None:
            raise ValueError("Введите двухбуквенный код страны ISO 3166-1, например AU.")
        return code


class DraftOffer(BaseModel):
    offer_id: PositiveInt
    pinned_share: int | None = Field(None, ge=0, le=100)


class DraftVersion(BaseModel):
    revision: int = Field(ge=0)
    baseline: str = Field(pattern=r"^[0-9a-f]{64}$")


class DraftInput(DraftVersion):
    offers: list[DraftOffer]

    @field_validator("offers")
    @classmethod
    def unique_offers(cls, offers: list[DraftOffer]) -> list[DraftOffer]:
        if len({offer.offer_id for offer in offers}) != len(offers):
            raise ValueError("Один оффер может присутствовать в потоке только один раз.")
        return offers


def public_campaign(row: dict) -> dict:
    return {key: row.get(key) for key in ("id", "name", "state", "alias", "domain_id")}


def public_catalog(rows: list[dict]) -> list[dict]:
    return [
        {"id": row["id"], "name": row["name"]}
        for row in rows
        if row.get("state", "active") == "active"
    ]


@app.get("/api/catalog")
def catalog(tracker: Keitaro):
    return {
        "domains": public_catalog(tracker.get("domains")),
        "groups": public_catalog(tracker.get("groups", type="campaigns")),
        "sources": public_catalog(tracker.get("traffic_sources")),
        "offers": public_catalog(tracker.get("offers")),
    }


@app.get("/api/campaigns")
def campaigns(
    tracker: Keitaro,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
):
    return [public_campaign(row) for row in tracker.get("campaigns", offset=offset, limit=limit)]


@app.post("/api/campaigns", status_code=201)
def new_campaign(data: CampaignInput, tracker: Keitaro):
    offer = tracker.get(f"offers/{data.offer_id}")
    if offer.get("state", "active") != "active":
        raise HTTPException(422, "Исходный оффер должен быть активным.")
    settings = data.model_dump(exclude={"country", "offer_id"})
    settings["alias"] = f"adrobot-{uuid4().hex[:12]}"
    campaign = create_campaign(tracker, settings, data.country, data.offer_id)
    return public_campaign(campaign)


@app.get("/api/campaigns/{campaign_id}")
def campaign_details(campaign_id: PositiveInt, tracker: Keitaro):
    campaign = public_campaign(tracker.get(f"campaigns/{campaign_id}"))
    streams = tracker.get(f"campaigns/{campaign_id}/streams")
    campaign["streams"] = [
        {
            "id": stream["id"],
            "name": stream["name"],
            "state": stream["state"],
            "position": stream["position"],
            "editable": stream.get("schema") == "landings",
            "offer_count": len(stream.get("offers") or []),
        }
        for stream in sorted(streams, key=lambda item: item["position"])
    ]
    return campaign


def load_stream(tracker: Tracker, stream_id: int) -> tuple[dict, list[dict]]:
    stream = tracker.get(f"streams/{stream_id}")
    if stream.get("schema") != "landings":
        raise HTTPException(422, "Офферы можно редактировать только в потоке со схемой «Офферы и лендинги».")
    return stream, list_offer_allocations(stream)


def fingerprint(offers: list[dict]) -> str:
    ordered = sorted(offers, key=lambda offer: offer["offer_id"])
    return sha256(json.dumps(ordered, sort_keys=True).encode()).hexdigest()


def draft_view(stream: dict, live: list[dict], draft: StreamDraft | None) -> dict:
    pending = draft is not None and draft.pending is not None
    rows = draft.pending if pending else live
    pins = (draft.pending_pins if pending else draft.pins) if draft else {}
    live_fingerprint = fingerprint(live)
    baseline = fingerprint(draft.baseline) if pending else live_fingerprint
    return {
        "id": stream["id"],
        "name": stream["name"],
        "campaign_id": stream["campaign_id"],
        "revision": draft.revision if draft else 0,
        "baseline": baseline,
        "changed_upstream": pending and live_fingerprint not in (baseline, fingerprint(rows)),
        "pending": pending,
        "offers": [
            {**row, "pinned": row["state"] == "active" and pins.get(str(row["offer_id"])) == row["share"]}
            for row in rows
        ],
    }


def verify_revision(draft: StreamDraft | None, data: DraftVersion):
    if data.revision != (draft.revision if draft else 0):
        raise HTTPException(409, "Черновик уже изменился. Сначала обновите поток.")


@app.get("/api/streams/{stream_id}/draft")
def view_draft(stream_id: PositiveInt, db: Database, tracker: Keitaro):
    stream, live = load_stream(tracker, stream_id)
    return draft_view(stream, live, db.get(StreamDraft, stream_id))


@app.put("/api/streams/{stream_id}/draft")
def save_draft(stream_id: PositiveInt, data: DraftInput, request: Request, db: Database, tracker: Keitaro):
    with request.app.state.edit_lock:
        stream, live = load_stream(tracker, stream_id)
        draft = db.get(StreamDraft, stream_id)
        verify_revision(draft, data)
        if fingerprint(live) != data.baseline:
            raise HTTPException(409, "Офферы в Keitaro изменились. Обновите поток перед редактированием.")
        old_states = {offer["offer_id"]: offer for offer in live}
        if draft is not None:
            old_states.update({offer["offer_id"]: offer for offer in draft.pending or []})
        for offer in data.offers:
            if offer.offer_id not in old_states:
                candidate = tracker.get(f"offers/{offer.offer_id}")
                if candidate.get("state", "active") != "active":
                    raise HTTPException(422, f"Оффер #{offer.offer_id} выключен.")

        pins = {
            offer.offer_id: offer.pinned_share
            for offer in data.offers
            if old_states.get(offer.offer_id, {}).get("state", "active") == "active"
        }
        shares = distribute(pins)
        pending = [
            {"offer_id": offer.offer_id, "share": shares[offer.offer_id], "state": "active"}
            if offer.offer_id in shares else old_states[offer.offer_id]
            for offer in data.offers
        ]
        if draft is None:
            draft = StreamDraft(stream_id=stream_id, revision=0, pins={})
            db.add(draft)
        draft.baseline = live
        draft.pending = pending
        draft.pending_pins = {str(key): value for key, value in pins.items() if value is not None}
        draft.revision += 1
        db.commit()
        return draft_view(stream, live, draft)


@app.post("/api/streams/{stream_id}/apply")
def apply_draft(stream_id: PositiveInt, data: DraftVersion, request: Request, db: Database, tracker: Keitaro):
    with request.app.state.edit_lock:
        stream, live = load_stream(tracker, stream_id)
        draft = db.get(StreamDraft, stream_id)
        verify_revision(draft, data)
        if draft is None or draft.pending is None:
            raise HTTPException(409, "У потока нет черновика.")

        wanted = fingerprint(draft.pending)
        if fingerprint(live) != wanted:
            if fingerprint(live) != fingerprint(draft.baseline):
                raise HTTPException(409, "Офферы в Keitaro изменились после начала редактирования.")
            tracker.request("PUT", f"streams/{stream_id}", body={"offers": draft.pending})
            stream, live = load_stream(tracker, stream_id)
            if fingerprint(live) != wanted:
                raise HTTPException(502, "Keitaro вернул другой список офферов. Черновик сохранён.")

        draft.baseline = live
        draft.pins = draft.pending_pins
        draft.pending = None
        draft.pending_pins = {}
        draft.revision += 1
        db.commit()
        return draft_view(stream, live, draft)


@app.post("/api/streams/{stream_id}/discard")
def discard_draft(stream_id: PositiveInt, data: DraftVersion, request: Request, db: Database, tracker: Keitaro):
    with request.app.state.edit_lock:
        stream, live = load_stream(tracker, stream_id)
        draft = db.get(StreamDraft, stream_id)
        verify_revision(draft, data)
        if draft is not None:
            draft.baseline = live
            draft.pending = None
            draft.pending_pins = {}
            draft.revision += 1
            db.commit()
        return draft_view(stream, live, draft)


@app.get("/api/streams/{stream_id}/stats")
def offer_stats(stream_id: PositiveInt, tracker: Keitaro):
    stream, _ = load_stream(tracker, stream_id)
    report = tracker.request("POST", "report/build", body={
        "range": {"interval": "7_days", "timezone": "Europe/Moscow"},
        "dimensions": ["offer_id"],
        "measures": ["clicks", "conversions"],
        "filters": [
            {"name": "campaign_id", "operator": "EQUALS", "expression": stream["campaign_id"]},
            {"name": "stream_id", "operator": "EQUALS", "expression": stream_id},
        ],
    })
    return {
        str(row["offer_id"]): {"clicks": row["clicks"], "conversions": row["conversions"]}
        for row in report["rows"]
        if row.get("offer_id") not in (None, "", 0)
    }


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(STATIC / "index.html")


@app.get("/styles.css", include_in_schema=False)
def stylesheet():
    return FileResponse(STATIC / "styles.css", media_type="text/css")


@app.get("/app.js", include_in_schema=False)
def javascript():
    return FileResponse(STATIC / "app.js", media_type="text/javascript")


app.mount("/assets", StaticFiles(directory=STATIC), name="assets")
