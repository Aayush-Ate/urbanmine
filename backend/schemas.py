"""Schemas: shapes of JSON in and out.

WHY: FastAPI validates requests against these before your code runs —
wrong types get a 422 error automatically, not a crash.
"""
from typing import Optional

from pydantic import BaseModel


class ListingConfirm(BaseModel):
    material: str
    quantity: float
    unit: Optional[str] = None
    condition: str = "Good"
    price_per_unit: Optional[float] = None
    lat: float = 12.9716
    lng: float = 77.5946
    address: str = "Bengaluru"
    contractor: str = "Demo Contractor"
    title: Optional[str] = None
    description: str = ""
    confidence: float = 1.0


class ListingPatch(BaseModel):
    quantity: Optional[float] = None
    condition: Optional[str] = None
    price_per_unit: Optional[float] = None
    status: Optional[str] = None


class MatchRequest(BaseModel):
    material: str
    quantity: float = 100
    lat: float = 12.9716
    lng: float = 77.5946
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
