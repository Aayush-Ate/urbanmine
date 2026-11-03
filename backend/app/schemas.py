"""The shapes of JSON going in and out.

FastAPI checks requests against these before our code runs. Wrong types get a
422 response, not a crash.

Anything that later becomes a file path, a price, or a map coordinate is bounded
here, so a route can trust what it receives. The URL rule matters most: the app
used to accept any string in image_url, and DELETE took the last path segment of
that string and passed it to a file unlink.
"""
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

CONDITIONS = Literal["Excellent", "Good", "Fair", "Poor"]
LISTING_STATUS = Literal["active", "sold", "draft"]
REQUEST_STATUS = Literal["pending", "accepted", "declined"]

# Only files this server wrote look like this: an upload id and .jpg. Anything
# else in image_url is dropped rather than stored.
UPLOAD_URL = re.compile(r"^/uploads/[A-Za-z0-9]{1,40}\.jpg$")

MAX_QUANTITY = 10_000_000
MAX_PRICE = 10_000_000


def _upload_url(value):
    if value in (None, ""):
        return None
    if isinstance(value, str) and UPLOAD_URL.match(value):
        return value
    return None


class ListingConfirm(BaseModel):
    material: str = Field(min_length=1, max_length=40)
    # a zero or negative lot is not a lot, and a negative price is a refund
    quantity: float = Field(gt=0, le=MAX_QUANTITY)
    unit: Optional[str] = Field(default=None, max_length=20)
    condition: CONDITIONS = "Good"
    price_per_unit: Optional[float] = Field(default=None, ge=0, le=MAX_PRICE)
    # no default point: a listing with no location is honest,
    # a listing pinned to Bengaluru centre when nobody said so is not
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lng: Optional[float] = Field(default=None, ge=-180, le=180)
    address: str = Field(default="", max_length=300)
    contractor: str = Field(default="", max_length=120)
    title: Optional[str] = Field(default=None, max_length=200)
    description: str = Field(default="", max_length=2000)
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    image_url: Optional[str] = None
    # small copy for the feed; image_url is only fetched when someone opens it
    thumb_url: Optional[str] = None
    bbox: Optional[list[float]] = None
    # measured size in millimetres (weight in kg, count in pieces) plus a label
    dimensions: Optional[dict] = None
    dimensions_label: Optional[str] = Field(default=None, max_length=120)

    @field_validator("image_url", "thumb_url")
    @classmethod
    def only_our_uploads(cls, v):
        return _upload_url(v)

    @field_validator("bbox")
    @classmethod
    def box_is_normalized(cls, v):
        # the browser crops the listing photo with these four numbers, so a
        # malformed box has to become "no box" instead of a wrong crop
        if v is None:
            return None
        if len(v) != 4:
            return None
        try:
            x1, y1, x2, y2 = (float(x) for x in v)
        except (TypeError, ValueError):
            return None
        if not all(0.0 <= x <= 1.0 for x in (x1, y1, x2, y2)):
            return None
        if x2 <= x1 or y2 <= y1:
            return None
        return [round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)]


class ListingPatch(BaseModel):
    quantity: Optional[float] = Field(default=None, gt=0, le=MAX_QUANTITY)
    condition: Optional[CONDITIONS] = None
    price_per_unit: Optional[float] = Field(default=None, ge=0, le=MAX_PRICE)
    status: Optional[LISTING_STATUS] = None


class MatchRequest(BaseModel):
    material: str = Field(min_length=1, max_length=40)
    quantity: float = Field(default=100, gt=0, le=MAX_QUANTITY)
    # required: ranking around a city the buyer never named is worse than an error
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    condition: Optional[CONDITIONS] = None
    max_distance_km: float = Field(default=50, gt=0, le=20_000)


class BuyerRequest(BaseModel):
    listing_id: str = Field(min_length=1, max_length=40)
    buyer_name: str = Field(min_length=1, max_length=80)
    buyer_type: str = Field(default="Architect", max_length=40)
    quantity: Optional[float] = Field(default=None, gt=0, le=MAX_QUANTITY)
    message: str = Field(default="", max_length=1000)


class RequestPatch(BaseModel):
    status: REQUEST_STATUS
