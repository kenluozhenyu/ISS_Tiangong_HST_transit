// App Logic for formatting and handling API calls
document.addEventListener('DOMContentLoaded', () => {

    // Set default dates (Today to Today + 1 month)
    const today = new Date();
    const nextMonth = new Date();
    nextMonth.setMonth(today.getMonth() + 1);

    document.getElementById('start-date').value = today.toISOString().split('T')[0];
    document.getElementById('end-date').value = nextMonth.toISOString().split('T')[0];

    // Geolocation API
    document.getElementById('btn-geolocate').addEventListener('click', () => {
        if (navigator.geolocation) {
            navigator.geolocation.getCurrentPosition((position) => {
                document.getElementById('lat').value = position.coords.latitude.toFixed(4);
                document.getElementById('lon').value = position.coords.longitude.toFixed(4);
            }, (error) => {
                alert("Geolocation failed or denied. Please enter coordinates manually.");
            });
        } else {
            alert("Geolocation is not supported by your browser.");
        }
    });

    // Form Submission
    document.getElementById('calc-form').addEventListener('submit', async (e) => {
        e.preventDefault();

        const payload = {
            lat: parseFloat(document.getElementById('lat').value),
            lon: parseFloat(document.getElementById('lon').value),
            radius_km: parseFloat(document.getElementById('radius').value),
            start_date: document.getElementById('start-date').value,
            end_date: document.getElementById('end-date').value
        };

        const loading = document.getElementById('loading');
        const resultsContainer = document.getElementById('results-container');
        const submitBtn = document.getElementById('btn-calculate');
        const consolePre = document.querySelector('#debug-console pre code');

        loading.classList.remove('hidden');
        resultsContainer.innerHTML = '';
        consolePre.innerHTML = `[INFO] Sending API request to /api/calculate\nPayload: ${JSON.stringify(payload, null, 2)}\n\nComputing...`;
        consolePre.className = '';

        submitBtn.disabled = true;
        submitBtn.style.opacity = '0.5';

        try {
            const response = await fetch('/api/calculate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                const errText = await response.text();
                throw new Error(`HTTP ${response.status}: ${errText}`);
            }

            const data = await response.json();

            // Log response summary
            consolePre.innerHTML += `\n\n[SUCCESS] Response received (Status ${response.status})\n`;
            consolePre.innerHTML += `Events parsed: ${data.events ? data.events.length : 0}\n`;

            // Truncate path_points array in the log to keep it readable
            const safeLogData = JSON.parse(JSON.stringify(data));
            if (safeLogData.events) {
                safeLogData.events.forEach(e => {
                    if (e.path_points) {
                        e.path_points = `[Array of ${e.path_points.length} points]`;
                    }
                });
            }

            consolePre.innerHTML += `\nData Preview:\n${JSON.stringify(safeLogData, null, 2)}`;

            renderResults(data.events);
        } catch (error) {
            resultsContainer.innerHTML = `<div class="empty-state" style="color:#ef4444;">Error: ${error.message}</div>`;
            consolePre.innerHTML += `\n\n[ERROR] ${error.message}`;
            consolePre.className = 'console-error';
        } finally {
            loading.classList.add('hidden');
            submitBtn.disabled = false;
            submitBtn.style.opacity = '1';
        }
    });
});

let currentPathPoints = null;

function renderResults(events) {
    const container = document.getElementById('results-container');
    container.innerHTML = '';

    if (!events || events.length === 0) {
        container.innerHTML = `<div class="empty-state">No transits found in this timeframe and radius. Try expanding the date range or radius.</div>`;
        return;
    }

    events.forEach((evt, idx) => {
        // Fix for Python UTC trailing 'Z' offset issue
        let timeStrRaw = evt.time_utc;
        if (timeStrRaw.includes('+00:00Z')) {
            timeStrRaw = timeStrRaw.replace('+00:00Z', 'Z');
        }

        const dateObj = new Date(timeStrRaw);
        const dateStr = dateObj.toLocaleDateString();
        const timeStr = dateObj.toLocaleTimeString();

        const card = document.createElement('div');
        card.className = 'transit-card';

        // Escape specific attributes
        const safePoints = encodeURIComponent(JSON.stringify(evt.path_points));

        card.innerHTML = `
            <div class="transit-info">
                <h3>${evt.satellite} across ${evt.celestial_body} <span class="transit-tag">${evt.transit_type}</span></h3>
                <div class="transit-details">
                    <div><strong>Date:</strong> ${dateStr}</div>
                    <div><strong>Time:</strong> ${timeStr}</div>
                    <div><strong>Separation:</strong> ${evt.separation_deg.toFixed(3)}&deg;</div>
                    <div><strong>Azimuth:</strong> ${evt.azimuth_deg.toFixed(1)}&deg;</div>
                    <div><strong>Elevation:</strong> ${evt.elevation_deg.toFixed(1)}&deg;</div>
                </div>
            </div>
            <div class="transit-actions">
                <button class="btn-map" onclick="showMapModal('${safePoints}', ${evt.swath_width_km}, '${evt.satellite}', '${evt.celestial_body}', '${dateStr}', '${timeStr}', ${document.getElementById('radius').value})">SHOW ON MAP</button>
            </div>
        `;
        container.appendChild(card);
    });
}
