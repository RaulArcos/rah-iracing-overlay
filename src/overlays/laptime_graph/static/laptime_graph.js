document.addEventListener("DOMContentLoaded", function() {
    const socket = io('/laptime_graph', {
        reconnection: true,
        reconnectionAttempts: Infinity,
        reconnectionDelay: 1000,
        reconnectionDelayMax: 5000,
        timeout: 20000
    });

    const canvas = document.getElementById('laptime-canvas');
    const ctx = canvas.getContext('2d');
    const bestEl = document.getElementById('best');
    const lastEl = document.getElementById('last');
    const deltaEl = document.getElementById('delta');

    function draw(history) {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        if (!history.length) {
            return;
        }

        const min = Math.min.apply(null, history);
        const max = Math.max.apply(null, history);
        const range = Math.max(max - min, 0.01);
        const stepX = canvas.width / Math.max(history.length - 1, 1);

        ctx.lineWidth = 2;
        ctx.strokeStyle = '#4fc3f7';
        ctx.beginPath();

        history.forEach(function(value, idx) {
            const x = idx * stepX;
            const y = canvas.height - ((value - min) / range) * (canvas.height - 16) - 8;
            if (idx === 0) {
                ctx.moveTo(x, y);
            } else {
                ctx.lineTo(x, y);
            }
        });

        ctx.stroke();
    }

    socket.on('laptime_graph_update', function(data) {
        if (!data || typeof data !== 'object') {
            return;
        }

        const history = Array.isArray(data.history) ? data.history : [];
        draw(history);

        const best = typeof data.best_lap_time === 'number' ? data.best_lap_time : 0;
        const last = typeof data.last_lap_time === 'number' ? data.last_lap_time : 0;
        const delta = typeof data.delta_to_best === 'number' ? data.delta_to_best : 0;

        bestEl.textContent = `Best: ${best.toFixed(3)}`;
        lastEl.textContent = `Last: ${last.toFixed(3)}`;
        deltaEl.textContent = `Delta: ${delta >= 0 ? '+' : ''}${delta.toFixed(3)}`;
    });
});
