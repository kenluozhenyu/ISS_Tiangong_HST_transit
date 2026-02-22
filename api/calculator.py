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
    stations_url = 'visual.txt'
    try:
        satellites = load.tle_file(stations_url)
    except FileNotFoundError:
        import subprocess
        subprocess.run(['python', 'download_tle.py'])
        satellites = load.tle_file(stations_url)
        
    by_name = {sat.name: sat for sat in satellites}
    return {
        'ISS': by_name.get('ISS (ZARYA)'),
        'Tiangong': by_name.get('CSS (TIANHE)') or by_name.get('CSS (TIANGONG)'),
        'HST': by_name.get('HST')
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
            
        # COARSE SEARCH: Sample every 2 seconds to find the closest approach
        coarse_samples = int(duration / 2.0)
        if coarse_samples < 2:
             coarse_samples = 2
             
        coarse_times_array = t_rise.tt + np.arange(0, coarse_samples) * 2.0 / (24.0 * 3600.0)
        coarse_times = ts.tt_jd(coarse_times_array)
        
        valid, subpts = get_shadow_path(sat, body, coarse_times)
        
        if not np.any(valid):
            continue
            
        lats = subpts.latitude.degrees
        lons = subpts.longitude.degrees
        
        # Calculate distance to observer for all valid coarse shadow points
        dists = haversine(lats, lons, obs_lat, obs_lon)
        dists[~valid] = np.inf
        
        min_dist_idx = np.argmin(dists)
        min_dist = dists[min_dist_idx]
        
        # If even the closest point in the coarse search is too far (e.g. > radius + 500km leeway), skip this pass entirely
        if min_dist > radius_km + 500:
            continue
            
        # FINE SEARCH: we found a point close enough. Let's do high-res (0.1s) strictly around the closest coarse point
        # Time window: +/- 10 seconds around the coarse minimum
        fine_center_tt = coarse_times_array[min_dist_idx]
        fine_start_tt = max(t_rise.tt, fine_center_tt - 10.0 / (24.0 * 3600.0))
        fine_end_tt = min(t_set.tt, fine_center_tt + 10.0 / (24.0 * 3600.0))
        
        fine_duration_sec = (fine_end_tt - fine_start_tt) * 24.0 * 3600.0
        fine_samples = int(fine_duration_sec * 10) # 10 frames per second
        if fine_samples < 2:
            continue
            
        fine_times_array = fine_start_tt + np.arange(0, fine_samples) / (24.0 * 3600.0 * 10)
        fine_times = ts.tt_jd(fine_times_array)
        
        fine_valid, fine_subpts = get_shadow_path(sat, body, fine_times)
        
        if not np.any(fine_valid):
            continue
            
        fine_lats = fine_subpts.latitude.degrees
        fine_lons = fine_subpts.longitude.degrees
        
        fine_dists = haversine(fine_lats, fine_lons, obs_lat, obs_lon)
        fine_dists[~fine_valid] = np.inf
        
        fine_min_idx = np.argmin(fine_dists)
        fine_min_dist = fine_dists[fine_min_idx]
        
        if fine_min_dist <= radius_km:
            transit_time = fine_times[fine_min_idx]
            
            # Now determine Transit or Close Pass based on angular separation
            body_apparent = observer.at(transit_time).observe(body).apparent()
            sat_apparent = (sat - topos).at(transit_time)
            
            body_alt, _, _ = body_apparent.altaz()
            sat_alt, sat_az, _ = sat_apparent.altaz()
            
            # The body must be above the horizon
            if body_alt.degrees < -2.0:
                continue

            sep = body_apparent.separation_from(sat_apparent).degrees
            transit_type = "Transit" if sep < (0.27 + 0.01) else "Close Pass" 
            
            if sep > 5.0:
                 continue
                 
            # Calculate Swath Width
            sat_dist_km = sat_apparent.distance().km
            body_dist_km = body_apparent.distance().km
            body_radius_km = 696340.0 if body_name == "Sun" else 1737.4
            
            angular_radius_rad = np.arcsin(body_radius_km / body_dist_km)
            swath_radius_km = sat_dist_km * np.tan(angular_radius_rad)
            swath_width_km = float(swath_radius_km * 2)
                 
            # Extract the active segment of the shadow path for the map 
            path_points = []
            for j in range(fine_samples):
                if fine_valid[j]:
                    path_points.append(TransitPoint(lat=float(fine_lats[j]), lon=float(fine_lons[j])))
                    
            results.append(TransitEvent(
                satellite=sat_name,
                celestial_body=body_name,
                transit_type=transit_type,
                time_utc=transit_time.utc_datetime().isoformat() + "Z",
                duration_sec=1.5,
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
