document.addEventListener("DOMContentLoaded", function() {
    const socket = io('/radar', {
        reconnection: true,
        reconnectionAttempts: Infinity,
        reconnectionDelay: 1000,
        reconnectionDelayMax: 5000,
        timeout: 20000
    });

    const leftAlert = document.getElementById('left-alert');
    const rightAlert = document.getElementById('right-alert');
    const nearbyList = document.getElementById('nearby-list');

    socket.on('radar_update', function(data) {
        if (!data || typeof data !== 'object') {
            return;
        }

        leftAlert.classList.toggle('active', Boolean(data.left_alert));
        rightAlert.classList.toggle('active', Boolean(data.right_alert));

        // Meters are only shown when the backend derived a real track length
        // from WeekendInfo.TrackLength; never invent one.
        const trackLengthM = (typeof data.track_length_m === 'number' && isFinite(data.track_length_m) && data.track_length_m > 0)
            ? data.track_length_m
            : null;

        const nearby = Array.isArray(data.nearby) ? data.nearby : [];
        nearbyList.innerHTML = nearby.slice(0, 6).map(function(item) {
            const pct = typeof item.distance_pct === 'number' && isFinite(item.distance_pct) ? item.distance_pct : 0;
            const meters = trackLengthM !== null ? ` ${Math.abs(pct * trackLengthM).toFixed(0)}m` : '';
            const relation = item.relation === 'ahead' ? 'AHEAD' : 'BEHIND';
            return `<div class="nearby-item"><span>Car ${item.car_idx}</span><span>${relation}${meters}</span></div>`;
        }).join('');
    });
});
