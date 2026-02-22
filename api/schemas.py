from pydantic import BaseModel
from typing import List, Optional

class CalculateRequest(BaseModel):
    lat: float
    lon: float
    radius_km: float
    start_date: str # YYYY-MM-DD
    end_date: str   # YYYY-MM-DD

class TransitPoint(BaseModel):
    lat: float
    lon: float

class TransitEvent(BaseModel):
    satellite: str # "ISS" or "Tiangong"
    celestial_body: str # "Sun" or "Moon"
    transit_type: str # "Transit" or "Close Pass"
    time_utc: str
    duration_sec: float
    swath_width_km: float
    separation_deg: float
    azimuth_deg: float
    elevation_deg: float
    path_points: List[TransitPoint] # Coordinates of the centerline on earth

class CalculateResponse(BaseModel):
    events: List[TransitEvent]
