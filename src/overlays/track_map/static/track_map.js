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
    const HEX = /^#[0-9a-fA-F]{6}$/;
    let lastCars = [];

    function css(name, fallback) {
        const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
        return value || fallback;
    }

    // Crisp at any DPI/zoom: draw in CSS pixels on a device-pixel backing store.
    function fit() {
        const rect = canvas.getBoundingClientRect();
        const size = Math.max(1, Math.round(rect.width || 300));
        const ratio = window.devicePixelRatio || 1;
        if (canvas.width !== Math.round(size * ratio)) {
            canvas.width = Math.round(size * ratio);
            canvas.height = Math.round(size * ratio);
        }
        ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
        return size;
    }

    function draw(cars) {
        lastCars = cars;
        const size = fit();
        const c = size / 2;
        const radius = size / 2 - 22;
        const accent = css('--rah-accent', '#ed2727');
        const gold = css('--rah-race-gold', '#f5cd5b');

        ctx.clearRect(0, 0, size, size);

        // Track band with soft edges
        ctx.lineCap = 'butt';
        ctx.beginPath();
        ctx.strokeStyle = 'rgba(255,255,255,0.07)';
        ctx.lineWidth = 22;
        ctx.arc(c, c, radius, 0, Math.PI * 2);
        ctx.stroke();
        ctx.beginPath();
        ctx.strokeStyle = 'rgba(255,255,255,0.16)';
        ctx.lineWidth = 1;
        ctx.arc(c, c, radius + 11, 0, Math.PI * 2);
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(c, c, radius - 11, 0, Math.PI * 2);
        ctx.stroke();

        // Start / finish line at 12 o'clock
        ctx.beginPath();
        ctx.strokeStyle = accent;
        ctx.lineWidth = 3;
        ctx.moveTo(c, c - radius - 13);
        ctx.lineTo(c, c - radius + 13);
        ctx.stroke();

        const player = cars.find(car => car.is_player);
        let playerAngle = null;

        // Others first, player last so it always sits on top.
        cars.slice().sort((a, b) => (a.is_player ? 1 : 0) - (b.is_player ? 1 : 0)).forEach(function(car) {
            const pctRaw = typeof car.lap_dist_pct === 'number' ? car.lap_dist_pct : 0;
            const pct = ((pctRaw % 1) + 1) % 1;
            const angle = (pct * Math.PI * 2) - (Math.PI / 2);
            const x = c + Math.cos(angle) * radius;
            const y = c + Math.sin(angle) * radius;
            const classColor = typeof car.class_color === 'string' && HEX.test(car.class_color) ? car.class_color : '#c9ced8';
            const dot = car.is_player ? 9 : 7.5;
            if (car.is_player) playerAngle = angle;

            if (car.is_player) {
                ctx.beginPath();
                ctx.fillStyle = 'rgba(245,205,91,0.22)';
                ctx.arc(x, y, dot + 6, 0, Math.PI * 2);
                ctx.fill();
            }
            ctx.beginPath();
            ctx.fillStyle = car.is_player ? gold : (car.on_pit_road ? '#5d626d' : classColor);
            ctx.globalAlpha = car.on_pit_road && !car.is_player ? 0.75 : 1;
            ctx.arc(x, y, dot, 0, Math.PI * 2);
            ctx.fill();
            ctx.globalAlpha = 1;
            ctx.lineWidth = 1.5;
            ctx.strokeStyle = 'rgba(0,0,0,0.55)';
            ctx.stroke();

            if (Number.isInteger(car.position) && car.position > 0) {
                ctx.fillStyle = '#111317';
                ctx.font = '700 ' + (car.position > 9 ? 8 : 9) + 'px Archivo, "Segoe UI", sans-serif';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillText(String(car.position), x, y + 0.5);
            }
        });

        // Centre readout
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        if (player) {
            ctx.fillStyle = css('--rah-race-ink', '#f4f5f7');
            ctx.font = '700 56px Antonio, "Segoe UI", sans-serif';
            ctx.fillText(Number.isInteger(player.position) && player.position > 0 ? 'P' + player.position : '--', c, c - 8);
            const pct = typeof player.lap_dist_pct === 'number' ? ((player.lap_dist_pct % 1) + 1) % 1 : null;
            ctx.fillStyle = css('--rah-race-dim', '#a7acb8');
            ctx.font = '500 10px "IBM Plex Mono", Consolas, monospace';
            ctx.fillText(pct === null ? '--' : (Math.round(pct * 100) + '% OF LAP'), c, c + 28);
            if (playerAngle !== null) {
                ctx.beginPath();
                ctx.strokeStyle = 'rgba(245,205,91,0.55)';
                ctx.lineWidth = 3;
                ctx.lineCap = 'round';
                ctx.arc(c, c, radius - 22, -Math.PI / 2, playerAngle < -Math.PI / 2 ? playerAngle + Math.PI * 2 : playerAngle);
                ctx.stroke();
            }
        } else {
            ctx.fillStyle = css('--rah-race-faint', '#7d8290');
            ctx.font = '500 10px "IBM Plex Mono", Consolas, monospace';
            ctx.fillText(cars.length ? 'Player not on track' : 'Waiting for data', c, c);
        }
    }

    socket.on('track_map_update', function(data) {
        if (!data || typeof data !== 'object') {
            return;
        }
        draw(Array.isArray(data.cars) ? data.cars : []);
    });
    window.addEventListener('rah-settings', () => draw(lastCars));
    draw([]);
    if (document.fonts && document.fonts.load) {
        Promise.all(['700 56px Antonio', '500 10px "IBM Plex Mono"', '700 9px Archivo'].map(f => document.fonts.load(f)))
            .then(() => draw(lastCars), () => {});
    }
});
