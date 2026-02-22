from fastapi import APIRouter, HTTPException
from .schemas import CalculateRequest, CalculateResponse, TransitEvent, TransitPoint
from skyfield.api import load, wgs84
from skyfield.positionlib import Geocentric
import math
from datetime import datetime
import numpy as np

router = APIRouter()

ts = load.timescale()
eph = load('de421.bsp')
sun = eph['sun']
moon = eph['moon']
earth = eph['earth']

def get_satellites():
    stations_url = 'stations.txt'
    satellites = load.tle_file(stations_url)
    by_name = {sat.name: sat for sat in satellites}
    return {
        'ISS': by_name.get('ISS (ZARYA)'),
        'Tiangong': by_name.get('CSS (TIANGONG)')
    }

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat/2.0)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2.0)**2
    c = 2 * np.arcsin(np.sqrt(a))
    return R * c

def get_shadow_path(sat, body, times):
    sat_pos = sat.at(times).position.km
    body_pos = earth.at(times).observe(body).apparent().position.km
    
    direction = sat_pos - body_pos
    u = direction / np.linalg.norm(direction, axis=0)
    
    a = 1.0
    b = 2.0 * np.sum(sat_pos * u, axis=0)
    R = 6378.137
    c = np.sum(sat_pos * sat_pos, axis=0) - R**2
    
    discriminant = b**2 - 4*a*c
    valid = discriminant >= 0
    
    d = (-b - np.sqrt(np.maximum(0, discriminant))) / 2.0
    shadow_km = sat_pos + u * d
    
    AU_km = 149597870.7
    shadow_au = shadow_km / AU_km
    
    geo = Geocentric(shadow_au, t=times)
    geo.center = 399
    
    subpts = wgs84.subpoint_of(geo)
    return valid, subpts

def calculate_pass(sat, sat_name, body, body_name, topos, t0, t1, radius_km, obs_lat, obs_lon):
    observer = earth + topos
    t, events = sat.find_events(topos, t0, t1, altitude_degrees=0.0)
    
    results = []
    
    for i in range(len(t)):
        if events[i] != 0:
            continue
            
        end_idx = i
        while end_idx < len(t) and events[end_idx] != 2:
            end_idx += 1
            
        if end_idx >= len(t):
            break
            
        t_rise = t[i]
        t_set = t[end_idx]
        
        duration = (t_set.utc_datetime() - t_rise.utc_datetime()).total_seconds()
        if duration <= 0:
            continue
            
        # Sample every 0.1 seconds for high resolution shadow path
        samples = int(duration * 10)
        times_array = t_rise.tt + np.arange(0, samples) / (24.0 * 3600.0 * 10)
        times = ts.tt_jd(times_array)
        
        valid, subpts = get_shadow_path(sat, body, times)
        
        if not np.any(valid):
            continue
            
        lats = subpts.latitude.degrees
        lons = subpts.longitude.degrees
        
        # Calculate distance to observer for all valid shadow points
        dists = haversine(lats, lons, obs_lat, obs_lon)
        # Apply valid mask
        dists[~valid] = np.inf
        
        min_dist_idx = np.argmin(dists)
        min_dist = dists[min_dist_idx]
        
        if min_dist <= radius_km:
            transit_time = times[min_dist_idx]
            
            # Now we need to determine if it's a Transit or Close Pass based on angular separation from the observer's POV
            # Because the map centerline is independent of observer's exact spot, we use observer's POV to classify transit vs close pass.
            body_apparent = observer.at(transit_time).observe(body).apparent()
            sat_apparent = (sat - topos).at(transit_time)
            
            body_alt, _, _ = body_apparent.altaz()
            sat_alt, sat_az, _ = sat_apparent.altaz()
            
            # The body must be above the horizon (or slightly below)
            if body_alt.degrees < -2.0:
                continue

            sep = body_apparent.separation_from(sat_apparent).degrees
            transit_type = "Transit" if sep < (0.27 + 0.01) else "Close Pass" # Sun/Moon angular radius is ~0.26 deg
            # Filter completely irrelevant passes if sep is too large
            if sep > 5.0:
                 continue
                 
            # Calculate Swath Width
            sat_dist_km = sat_apparent.distance().km
            body_dist_km = body_apparent.distance().km
            if body_name == "Sun":
                body_radius_km = 696340.0
            else:
                body_radius_km = 1737.4
            
            angular_radius_rad = np.arcsin(body_radius_km / body_dist_km)
            swath_radius_km = sat_dist_km * np.tan(angular_radius_rad)
            swath_width_km = float(swath_radius_km * 2)
                 
            # Extract the active segment of the shadow path for the map 
            # (e.g., +/- 10 seconds around transit)
            start_idx = max(0, min_dist_idx - 100)
            end_idx = min(len(times), min_dist_idx + 100)
            
            path_points = []
            for j in range(start_idx, end_idx):
                if valid[j]:
                    path_points.append(TransitPoint(lat=float(lats[j]), lon=float(lons[j])))
                    
            results.append(TransitEvent(
                satellite=sat_name,
                celestial_body=body_name,
                transit_type=transit_type,
                time_utc=transit_time.utc_datetime().isoformat() + "Z",
                duration_sec=1.5, # Will make accurate duration later if needed
                swath_width_km=swath_width_km,
                separation_deg=float(sep),
                azimuth_deg=float(sat_az.degrees),
                elevation_deg=float(sat_alt.degrees),
                path_points=path_points
            ))
            
    return results

@router.post("/calculate", response_model=CalculateResponse)
async def calculate_transits(request: CalculateRequest):
    try:
        t0_dt = datetime.fromisoformat(request.start_date)
        t1_dt = datetime.fromisoformat(request.end_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
        
    t0 = ts.utc(t0_dt.year, t0_dt.month, t0_dt.day)
    t1 = ts.utc(t1_dt.year, t1_dt.month, t1_dt.day)
    
    topos = wgs84.latlon(request.lat, request.lon)
    sats = get_satellites()
    
    all_events = []
    
    for sat_name, sat in sats.items():
        if not sat:
            continue
        sun_events = calculate_pass(sat, sat_name, sun, "Sun", topos, t0, t1, request.radius_km, request.lat, request.lon)
        all_events.extend(sun_events)
        
        moon_events = calculate_pass(sat, sat_name, moon, "Moon", topos, t0, t1, request.radius_km, request.lat, request.lon)
        all_events.extend(moon_events)
        
    all_events.sort(key=lambda x: x.time_utc)
        
    return CalculateResponse(events=all_events)
