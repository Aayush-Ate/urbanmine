"""The shapes of JSON going in and out.

FastAPI checks requests against these before our code runs. Wrong types get
a 422 response, not a crash.
"""
from typing import Optional

from pydantic import BaseModel


class ListingConfirm(BaseModel):
    material: str
    quantity: float
    unit: Optional[str] = None
    condition: str = "Good"
    price_per_unit: Optional[float] = None
    # no default point: a listing with no location is honest,
    # a listing pinned to Bengaluru centre when nobody said so is not
    lat: Optional[float] = None
    lng: Optional[float] = None
    address: str = ""
    contractor: str = ""
    title: Optional[str] = None
    description: str = ""
    confidence: Optional[float] = None
    image_url: Optional[str] = None
    # small copy for the feed; image_url is only fetched when someone opens it
    thumb_url: Optional[str] = None
    bbox: Optional[list[float]] = None
    # measured size in millimetres (weight in kg, count in pieces) plus a label
    dimensions: Optional[dict] = None
    dimensions_label: Optional[str] = None


class ListingPatch(BaseModel):
    quantity: Optional[float] = None
    condition: Optional[str] = None
    price_per_unit: Optional[float] = None
    status: Optional[str] = None


class MatchRequest(BaseModel):
    material: str
    quantity: float = 100
    # required: ranking around a city the buyer never named is worse than an error
    lat: float
    lng: float
    condition: Optional[str] = None
    max_distance_km: float = 50


class BuyerRequest(BaseModel):
    listing_id: str
    buyer_name: str
    buyer_type: str = "Architect"
    quantity: Optional[float] = None
    message: str = ""


class RequestPatch(BaseModel):
    status: str  # accepted | declined | pending
