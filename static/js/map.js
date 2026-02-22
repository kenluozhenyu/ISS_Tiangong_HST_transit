let mapInstance = null;
let currentLayer = null;
let userMarker = null;

function showMapModal(pointsJson, swathWidthKm, satellite, celestialBody, dateStr, timeStr) {
    const points = JSON.parse(decodeURIComponent(pointsJson));
    const modal = document.getElementById('map-modal');
    modal.classList.remove('hidden');

    document.getElementById('modal-title').innerText = `${satellite} Transit Visibility Band`;
    document.getElementById('modal-subtitle').innerHTML = `Across the <strong>${celestialBody}</strong> on ${dateStr} at ${timeStr}`;

    if (!mapInstance) {
        mapInstance = L.map('map').setView([0, 0], 2);

        // Use standard OpenStreetMap layer
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
            maxZoom: 19
        }).addTo(mapInstance);
    }

    // Important: Invalidate size when unhiding a div containing a Leaflet map
    setTimeout(() => {
        mapInstance.invalidateSize();

        if (currentLayer) {
            mapInstance.removeLayer(currentLayer);
        }
        if (userMarker) {
            mapInstance.removeLayer(userMarker);
        }

        const latLngs = points.map(p => [p.lat, p.lon]);

        // Use Turf to create a polygon if we have a swath width
        if (typeof turf !== 'undefined' && swathWidthKm && latLngs.length >= 2) {
            const turfLngLats = points.map(p => [p.lon, p.lat]);
            const line = turf.lineString(turfLngLats);
            const radius = swathWidthKm / 2;
            const buffered = turf.buffer(line, radius, { units: 'kilometers' });

            currentLayer = L.geoJSON(buffered, {
                style: function (feature) {
                    return {
                        color: '#ef4444',
                        weight: 2,
                        fillColor: '#ef4444',
                        fillOpacity: 0.3
                    };
                }
            }).addTo(mapInstance);

            // Add centerline to the layer group
            L.polyline(latLngs, {
                color: '#ef4444',
                weight: 2,
                dashArray: '5, 5'
            }).addTo(currentLayer);

        } else {
            // Draw the transit band centerline only
            currentLayer = L.polyline(latLngs, {
                color: '#ef4444',
                weight: 4,
                opacity: 0.9,
                lineCap: 'round',
                lineJoin: 'round'
            }).addTo(mapInstance);
        }

        // Draw user's search location
        const userLat = parseFloat(document.getElementById('lat').value);
        const userLon = parseFloat(document.getElementById('lon').value);
        const searchRadiusKm = parseFloat(document.getElementById('radius').value) || 50;

        if (!isNaN(userLat) && !isNaN(userLon)) {
            userMarker = L.featureGroup().addTo(mapInstance);

            // Center Dot
            L.circleMarker([userLat, userLon], {
                color: '#3b82f6',
                fillColor: '#3b82f6',
                fillOpacity: 1,
                radius: 6
            }).addTo(userMarker).bindPopup('<strong style="color:black;">Your Search Center</strong>');

            // Radius Circle (dashed)
            L.circle([userLat, userLon], {
                color: '#3b82f6',
                weight: 1.5,
                fillColor: '#3b82f6',
                fillOpacity: 0.05,
                dashArray: '5, 5',
                radius: searchRadiusKm * 1000 // Leaflet radius is in meters
            }).addTo(userMarker);
        }

        // Fit bounds to include both user and the swath
        const group = new L.featureGroup();
        if (currentLayer) group.addLayer(currentLayer);
        if (userMarker) group.addLayer(userMarker);

        mapInstance.fitBounds(group.getBounds(), { padding: [50, 50] });
    }, 200);
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('close-modal').addEventListener('click', () => {
        document.getElementById('map-modal').classList.add('hidden');
    });
});
