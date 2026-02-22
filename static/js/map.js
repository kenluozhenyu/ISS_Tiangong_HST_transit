let mapInstance = null;
let currentPolyline = null;
let userMarker = null;

function showMapModal(pointsJson) {
    const points = JSON.parse(decodeURIComponent(pointsJson));
    const modal = document.getElementById('map-modal');
    modal.classList.remove('hidden');

    if (!mapInstance) {
        mapInstance = L.map('map').setView([0, 0], 2);

        // Use a nicer dark-themed map layer if possible, or standard openstreetmap
        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
            subdomains: 'abcd',
            maxZoom: 20
        }).addTo(mapInstance);
    }

    // Important: Invalidate size when unhiding a div containing a Leaflet map
    setTimeout(() => {
        mapInstance.invalidateSize();

        if (currentPolyline) {
            mapInstance.removeLayer(currentPolyline);
        }
        if (userMarker) {
            mapInstance.removeLayer(userMarker);
        }

        const latLngs = points.map(p => [p.lat, p.lon]);

        // Draw the transit band centerline
        currentPolyline = L.polyline(latLngs, {
            color: '#38bdf8', // Neon blue
            weight: 4,
            opacity: 0.9,
            lineCap: 'round',
            lineJoin: 'round'
        }).addTo(mapInstance);

        // Draw user's search location
        const userLat = parseFloat(document.getElementById('lat').value);
        const userLon = parseFloat(document.getElementById('lon').value);
        if (!isNaN(userLat) && !isNaN(userLon)) {
            userMarker = L.circleMarker([userLat, userLon], {
                color: '#f43f5e',
                fillColor: '#f43f5e',
                fillOpacity: 1,
                radius: 6
            }).addTo(mapInstance).bindPopup('<strong style="color:black;">Your Search Center</strong>');
        }

        // Fit bounds to include both user and the swath
        const group = new L.featureGroup([currentPolyline]);
        if (userMarker) {
            group.addLayer(userMarker);
        }

        mapInstance.fitBounds(group.getBounds(), { padding: [50, 50] });
    }, 200);
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('close-modal').addEventListener('click', () => {
        document.getElementById('map-modal').classList.add('hidden');
    });
});
