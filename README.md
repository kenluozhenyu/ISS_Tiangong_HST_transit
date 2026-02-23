# Satellite Transit Finder (ISS, Tiangong, HST)

A modern, high-performance web application designed to predict and visualize celestial transits of major satellites (ISS, Tiangong, Hubble Space Telescope) across the Sun and Moon.

## 🚀 Features

- **Multi-Satellite Support**: Real-time TLE fetching for ISS (Zarya), CSS (Tiangong/Tianhe), and HST.
- **Precision Calculations**: Uses `Skyfield` and `DE421` ephemris for rigorous astronomical positioning.
- **Visibility Band (Swath)**: Calculates the physical width of the transit path on the Earth's surface based on the apparent angular radius of the Sun/Moon.
- **Interactive Map**: 
    - Full-screen responsive modal using `Leaflet.js`.
    - Semi-transparent visibility bands drawn using `Turf.js`.
    - Centerline visualization and search radius boundary (dashed circle).
- **Premium UI**: Glassmorphism design with dark mode, subtle animations, and an embedded API Debug Console.
- **Optimized Performance**: Custom "Coarse-to-Fine" search algorithm + multi-process parallelization reducing computation time from minutes to seconds.

## 🧠 Core Algorithm

### Stage 1 — Coarse-to-Fine Search (per Pass)

Traditional transit search involves checking satellite positions at high resolution (e.g., 10Hz) across entire orbital passes. This is computationally expensive in Python. Our optimized algorithm implements:

1.  **Event Detection**: `skyfield.find_events()` quickly discovers all rise/set pairs over the entire date range (~0.1s).
2.  **Coarse Scan (2.0s steps)**: Sub-sample each pass at a coarse interval to find the point of minimal shadow distance to the observer.
3.  **Fast Pruning**: Passes with a coarse closest approach > `Search Radius + 500km` are discarded instantly.
4.  **Fine Refinement (0.1s steps)**: Only perform high-resolution (10Hz) shadow projection within a ±10-second window around the coarse minimum.
5.  **Geometric Projection**: The ground track is calculated by finding the intersection of the Sun-Satellite vector with the WGS84 Earth ellipsoid.

### Stage 2 — Multi-Process Parallelization

Each satellite pass is an independent, atomic computation unit (no cross-day splitting issues). The architecture:

1.  **Main Process**: Runs `find_events()` for all satellites once (fast: <0.1s), producing a list of `(satellite, body, t_rise, t_set)` tasks.
2.  **ProcessPoolExecutor**: Distributes all tasks across `N-1` CPU cores (where N = `os.cpu_count()`). Each child process independently loads Skyfield data and runs the Coarse→Fine pipeline.
3.  **Result Aggregation**: Main process collects results, sorts by time, and returns the JSON response.

```
Main Process                     Worker Processes (CPU cores)
┌────────────────────┐
│  find_events()     │──┐
│  (all sats, fast)  │  │    ┌──────────────────────────┐
└────────────────────┘  ├───>│ Core 1: ISS×Sun Pass #1  │
                        ├───>│ Core 2: ISS×Moon Pass #1  │
                        ├───>│ Core 3: ISS×Sun Pass #2   │
                        ├───>│ Core 4: HST×Sun Pass #1   │
                        ├───>│ Core 5: Tiangong×Moon #1  │
                        │    └──────────────────────────┘
                        │         ... (hundreds of tasks)
┌────────────────────┐  │
│  Collect & Sort    │<─┘
│  Return JSON       │
└────────────────────┘
```

### Performance Benchmarks

| Metric | Brute Force | + Coarse-to-Fine | + Multi-Process |
|---|---|---|---|
| 20-day search (Beijing, 100km) | ~90s | ~15s | **~5.8s** ✅ |
| Events found | 9 | 9 | **9** ✅ |

## 🛠️ Tech Stack

- **Backend**: Python 3.x, FastAPI, Skyfield, NumPy, Pydantic.
- **Frontend**: Vanilla JavaScript (ES6+), Vanilla CSS (Glassmorphism), Leaflet.js, Turf.js.
- **Data**: Celestrak TLE (Visual Group), NASA JPL DE421 Ephemeris.

## 📦 Installation & Setup

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/kenluozhenyu/ISS_Tiangong_HST_transit
    cd ISS_Tiangong_HST_transit
    ```

2.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

3.  **Run the application**:
    ```bash
    uvicorn main:app --port 8080
    ```

4.  **Access the UI**:
    Open `http://localhost:8080` in your browser.

## 📝 License
MIT License. Created by Antigravity AI Assistant.
