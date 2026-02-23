from fastapi import APIRouter, HTTPException
from .schemas import CalculateRequest, CalculateResponse, TransitEvent, TransitPoint
from skyfield.api import load, wgs84
from skyfield.positionlib import Geocentric
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np
import os

router = APIRouter()

# ── Shared ephemeris (loaded once at import time) ──────────────────────
ts = load.timescale()
eph = load('de421.bsp')
sun = eph['sun']
moon = eph['moon']
earth = eph['earth']

# Use all available CPU cores, leaving 1 for the main thread
_MAX_WORKERS = max(1, os.cpu_count() - 1)

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
        'HST': by_name.get('HST'),
        'KH-11 13': by_name.get('USA-245')
    }

# ── Pure math helpers (no Skyfield objects, pickle-safe) ───────────────
def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat/2.0)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2.0)**2
    c = 2 * np.arcsin(np.sqrt(a))
    return R * c

def _get_shadow_path(sat, body, times, earth_obj):
    """Calculate the ground track of the satellite's shadow on Earth."""
    sat_pos = sat.at(times).position.km
    body_pos = earth_obj.at(times).observe(body).apparent().position.km

    direction = sat_pos - body_pos
    u = direction / np.linalg.norm(direction, axis=0)

    a_coeff = 1.0
    b_coeff = 2.0 * np.sum(sat_pos * u, axis=0)
    R = 6378.137
    c_coeff = np.sum(sat_pos * sat_pos, axis=0) - R**2

    discriminant = b_coeff**2 - 4*a_coeff*c_coeff
    valid = discriminant >= 0

    d = (-b_coeff - np.sqrt(np.maximum(0, discriminant))) / 2.0
    shadow_km = sat_pos + u * d

    AU_km = 149597870.7
    shadow_au = shadow_km / AU_km

    geo = Geocentric(shadow_au, t=times)
    geo.center = 399

    subpts = wgs84.subpoint_of(geo)
    return valid, subpts


# ── Per-pass worker function (runs in child process) ──────────────────
def _process_single_pass(sat_name, body_name, t_rise_tt, t_set_tt,
                         obs_lat, obs_lon, radius_km):
    """
    Evaluate ONE satellite pass for a potential transit/close-pass.
    This function is designed to be called in a child process.
    It re-loads ephemeris and TLE data in the child process context.
    Returns a dict (TransitEvent data) or None.
    """
    # Each child process must load its own Skyfield objects (not picklable)
    _ts = load.timescale()
    _eph = load('de421.bsp')
    _sun = _eph['sun']
    _moon = _eph['moon']
    _earth = _eph['earth']

    body = _sun if body_name == "Sun" else _moon

    sats = get_satellites()
    sat = sats.get(sat_name)
    if sat is None:
        return None

    topos = wgs84.latlon(obs_lat, obs_lon)
    observer = _earth + topos

    t_rise = _ts.tt_jd(t_rise_tt)
    t_set = _ts.tt_jd(t_set_tt)

    duration = (t_set_tt - t_rise_tt) * 24.0 * 3600.0
    if duration <= 0:
        return None

    # ── COARSE SEARCH (2s steps) ──
    coarse_samples = max(2, int(duration / 2.0))
    coarse_times_array = t_rise_tt + np.arange(0, coarse_samples) * 2.0 / (24.0 * 3600.0)
    coarse_times = _ts.tt_jd(coarse_times_array)

    valid, subpts = _get_shadow_path(sat, body, coarse_times, _earth)

    if not np.any(valid):
        return None

    lats = subpts.latitude.degrees
    lons = subpts.longitude.degrees

    dists = haversine(lats, lons, obs_lat, obs_lon)
    dists[~valid] = np.inf

    min_dist_idx = np.argmin(dists)
    min_dist = dists[min_dist_idx]

    if min_dist > radius_km + 500:
        return None

    # ── FINE SEARCH (0.1s steps, ±10s window) ──
    fine_center_tt = coarse_times_array[min_dist_idx]
    fine_start_tt = max(t_rise_tt, fine_center_tt - 10.0 / (24.0 * 3600.0))
    fine_end_tt = min(t_set_tt, fine_center_tt + 10.0 / (24.0 * 3600.0))

    fine_duration_sec = (fine_end_tt - fine_start_tt) * 24.0 * 3600.0
    fine_samples = int(fine_duration_sec * 10)
    if fine_samples < 2:
        return None

    fine_times_array = fine_start_tt + np.arange(0, fine_samples) / (24.0 * 3600.0 * 10)
    fine_times = _ts.tt_jd(fine_times_array)

    fine_valid, fine_subpts = _get_shadow_path(sat, body, fine_times, _earth)

    if not np.any(fine_valid):
        return None

    fine_lats = fine_subpts.latitude.degrees
    fine_lons = fine_subpts.longitude.degrees

    fine_dists = haversine(fine_lats, fine_lons, obs_lat, obs_lon)
    fine_dists[~fine_valid] = np.inf

    fine_min_idx = np.argmin(fine_dists)
    fine_min_dist = fine_dists[fine_min_idx]

    if fine_min_dist > radius_km:
        return None

    transit_time = fine_times[fine_min_idx]

    # ── Classification ──
    body_apparent = observer.at(transit_time).observe(body).apparent()
    sat_apparent = (sat - topos).at(transit_time)

    body_alt, _, _ = body_apparent.altaz()
    sat_alt, sat_az, _ = sat_apparent.altaz()

    if body_alt.degrees < -2.0:
        return None

    sep = body_apparent.separation_from(sat_apparent).degrees
    transit_type = "Transit" if sep < 0.28 else "Close Pass"

    if sep > 5.0:
        return None

    # ── Swath Width ──
    sat_dist_km = sat_apparent.distance().km
    body_dist_km = body_apparent.distance().km
    body_radius_km = 696340.0 if body_name == "Sun" else 1737.4

    angular_radius_rad = np.arcsin(body_radius_km / body_dist_km)
    swath_radius_km = sat_dist_km * np.tan(angular_radius_rad)
    swath_width_km = float(swath_radius_km * 2)

    # ── Path Points ──
    path_points = []
    for j in range(fine_samples):
        if fine_valid[j]:
            path_points.append({"lat": float(fine_lats[j]), "lon": float(fine_lons[j])})

    return {
        "satellite": sat_name,
        "celestial_body": body_name,
        "transit_type": transit_type,
        "time_utc": transit_time.utc_datetime().isoformat() + "Z",
        "duration_sec": 1.5,
        "swath_width_km": swath_width_km,
        "separation_deg": float(sep),
        "azimuth_deg": float(sat_az.degrees),
        "elevation_deg": float(sat_alt.degrees),
        "path_points": path_points,
    }


# ── Fast pass-discovery (main process, uses shared Skyfield objects) ──
def _discover_passes(sat, topos, t0, t1):
    """
    Quickly find all rise/set pairs for a satellite. Returns list of
    (t_rise_tt, t_set_tt) tuples. This is very fast (<0.1s for 30 days).
    """
    t, events = sat.find_events(topos, t0, t1, altitude_degrees=0.0)
    passes = []
    for i in range(len(t)):
        if events[i] != 0:
            continue
        end_idx = i
        while end_idx < len(t) and events[end_idx] != 2:
            end_idx += 1
        if end_idx >= len(t):
            break
        passes.append((t[i].tt, t[end_idx].tt))
    return passes


# ── API Endpoint ──────────────────────────────────────────────────────
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

    # ── Step 1: Discover all passes (fast, single-threaded) ────────
    tasks = []  # list of (sat_name, body_name, t_rise_tt, t_set_tt)
    for sat_name, sat in sats.items():
        if not sat:
            continue
        passes = _discover_passes(sat, topos, t0, t1)
        for (rise_tt, set_tt) in passes:
            tasks.append((sat_name, "Sun", rise_tt, set_tt))
            tasks.append((sat_name, "Moon", rise_tt, set_tt))

    # ── Step 2: Parallel fine calculation (multi-process) ──────────
    all_events = []

    if tasks:
        with ProcessPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            futures = {
                pool.submit(
                    _process_single_pass,
                    sat_name, body_name, rise_tt, set_tt,
                    request.lat, request.lon, request.radius_km
                ): (sat_name, body_name)
                for (sat_name, body_name, rise_tt, set_tt) in tasks
            }
            for future in as_completed(futures):
                try:
                    result = future.result()
                except Exception:
                    continue
                if result is not None:
                    all_events.append(TransitEvent(
                        satellite=result["satellite"],
                        celestial_body=result["celestial_body"],
                        transit_type=result["transit_type"],
                        time_utc=result["time_utc"],
                        duration_sec=result["duration_sec"],
                        swath_width_km=result["swath_width_km"],
                        separation_deg=result["separation_deg"],
                        azimuth_deg=result["azimuth_deg"],
                        elevation_deg=result["elevation_deg"],
                        path_points=[TransitPoint(**p) for p in result["path_points"]],
                    ))

    all_events.sort(key=lambda x: x.time_utc)

    return CalculateResponse(events=all_events)
