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

        const nearby = Array.isArray(data.nearby) ? data.nearby : [];
        nearbyList.innerHTML = nearby.slice(0, 6).map(function(item) {
            const pct = typeof item.distance_pct === 'number' ? item.distance_pct : 0;
            const meters = Math.abs(pct * 5500).toFixed(0);
            const relation = item.relation === 'ahead' ? 'AHEAD' : 'BEHIND';
            return `<div class="nearby-item"><span>Car ${item.car_idx}</span><span>${relation} ${meters}m</span></div>`;
        }).join('');
    });
});
