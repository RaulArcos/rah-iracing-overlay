document.addEventListener("DOMContentLoaded", function() {
    const socket = io('/track_map', {
        reconnection: true,
        reconnectionAttempts: Infinity,
        reconnectionDelay: 1000,
        reconnectionDelayMax: 5000,
        timeout: 20000
    });

    const canvas = document.getElementById('track-map-canvas');
    const ctx = canvas.getContext('2d');

    function draw(cars) {
        const centerX = canvas.width / 2;
        const centerY = canvas.height / 2;
        const radius = 130;

        ctx.clearRect(0, 0, canvas.width, canvas.height);

        ctx.beginPath();
        ctx.strokeStyle = 'rgba(255,255,255,0.2)';
        ctx.lineWidth = 18;
        ctx.arc(centerX, centerY, radius, 0, Math.PI * 2);
        ctx.stroke();

        ctx.beginPath();
        ctx.strokeStyle = 'rgba(0,0,0,0.55)';
        ctx.lineWidth = 2;
        ctx.arc(centerX, centerY, radius, 0, Math.PI * 2);
        ctx.stroke();

        cars.forEach(function(car) {
            const pctRaw = typeof car.lap_dist_pct === 'number' ? car.lap_dist_pct : 0;
            const pct = ((pctRaw % 1) + 1) % 1;
            const angle = (pct * Math.PI * 2) - (Math.PI / 2);
            const x = centerX + Math.cos(angle) * radius;
            const y = centerY + Math.sin(angle) * radius;

            ctx.beginPath();
            ctx.fillStyle = car.is_player ? '#f6d743' : (car.on_pit_road ? '#8f8f8f' : '#4fc3f7');
            ctx.arc(x, y, car.is_player ? 6 : 4, 0, Math.PI * 2);
            ctx.fill();
        });
    }

    socket.on('track_map_update', function(data) {
        if (!data || typeof data !== 'object') {
            return;
        }
        draw(Array.isArray(data.cars) ? data.cars : []);
    });
});
