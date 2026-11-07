document.addEventListener('DOMContentLoaded', function() {
    const socket = io('/laptime_graph', {reconnection: true, reconnectionAttempts: Infinity,
        reconnectionDelay: 1000, reconnectionDelayMax: 5000, timeout: 20000});
    const canvas = document.getElementById('laptime-canvas');
    const ctx = canvas.getContext('2d');
    const bestEl = document.getElementById('best');
    const lastEl = document.getElementById('last');
    const deltaEl = document.getElementById('delta');
    const band = document.getElementById('log-best');
    const bestLabel = document.getElementById('log-best-label');
    const temp = document.getElementById('log-best-temp');
    const status = document.getElementById('log-status');
    const empty = document.getElementById('log-empty');
    const rows = document.getElementById('laplog-rows');
    const number = v => typeof v === 'number' && Number.isFinite(v);
    const valid = v => number(v) && v > 0;
    const object = v => v && typeof v === 'object' && !Array.isArray(v);
    const signed = v => number(v) ? (v >= 0 ? '+' : '') + v.toFixed(3) : '--';
    function lap(v) {
        if (!valid(v)) return '--';
        const ms = Math.round(v * 1000);
        return Math.floor(ms / 60000) + ':' + String(Math.floor(ms / 1000) % 60).padStart(2, '0')
            + '.' + String(ms % 1000).padStart(3, '0');
    }
    let lastUpdate = null;
    let lastDraw = [[], null];
    // Draw in CSS pixels on a device-pixel backing store so the chart never
    // stretches when the panel is wider/narrower than the canvas attribute.
    function fit() {
        let W = canvas.width || 500, H = canvas.height || 150;
        if (typeof canvas.getBoundingClientRect === 'function' && typeof ctx.setTransform === 'function') {
            const rect = canvas.getBoundingClientRect();
            if (rect.width > 0 && rect.height > 0) {
                const ratio = (typeof window !== 'undefined' && window.devicePixelRatio) || 1;
                W = Math.round(rect.width); H = Math.round(rect.height);
                if (canvas.width !== Math.round(W * ratio) || canvas.height !== Math.round(H * ratio)) {
                    canvas.width = Math.round(W * ratio); canvas.height = Math.round(H * ratio);
                }
                ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
            }
        }
        return {W, H};
    }
    function draw(records, best) {
        lastDraw = [records, best];
        const {W, H} = fit();
        ctx.clearRect(0, 0, W, H);
        const times = records.map(r => r.time_s).filter(valid);
        empty.textContent = times.length ? '' : 'No observed completed laps';
        if (!times.length) return;
        // Quantised half-second ticks, at least a meaningful two-second span.
        const lo = Math.max(0.001, Math.floor((Math.min(...times) - .5) * 2) / 2);
        const hi = Math.max(lo + 2, Math.ceil((Math.max(...times) + .5) * 2) / 2);
        const left = 12, right = W - 88, top = 14, bottom = H - 22;
        const x = i => left + i / Math.max(records.length - 1, 1) * (right - left);
        const y = t => top + (t - lo) / (hi - lo) * (bottom - top);
        ctx.font = '500 10px "IBM Plex Mono", Consolas, monospace';
        for (let i = 0; i <= 4; i++) {
            const t = lo + (hi - lo) * i / 4;
            ctx.beginPath(); ctx.strokeStyle = 'rgba(255,255,255,.17)'; ctx.lineWidth = 1;
            ctx.moveTo(left, y(t)); ctx.lineTo(right, y(t)); ctx.stroke();
            ctx.fillStyle = '#b7bac2'; ctx.fillText(lap(t), right + 8, y(t) + 4);
        }
        let previous = null;
        records.forEach((r, i) => {
            if (!valid(r.time_s)) { previous = null; return; }
            const color = r.time_s === best ? '#e46cf0'
                : previous && r.time_s < previous.time_s ? '#55dd8d' : '#ff6868';
            if (previous) {
                ctx.beginPath(); ctx.strokeStyle = color; ctx.lineWidth = 2;
                ctx.moveTo(x(i-1), y(previous.time_s)); ctx.lineTo(x(i), y(r.time_s)); ctx.stroke();
            }
            ctx.beginPath(); ctx.fillStyle = color; ctx.arc(x(i), y(r.time_s), 4, 0, Math.PI * 2); ctx.fill();
            if (r.incident === true) { ctx.fillStyle = '#ff6868'; ctx.fillText('×', x(i)-4, y(r.time_s)-10); }
            ctx.fillStyle = '#b7bac2';
            ctx.fillText(Number.isInteger(r.lap_number) && r.lap_number >= 0 ? String(r.lap_number) : '--', x(i)-4, H-3);
            previous = r;
        });
    }
    if (typeof window !== 'undefined' && window.addEventListener) {
        window.addEventListener('resize', () => draw(lastDraw[0], lastDraw[1]));
    }
    function clear(message) {
        lastUpdate = null;
        rows.textContent = ''; band.textContent = '--'; temp.textContent = '--';
        bestEl.textContent = 'Best: --'; lastEl.textContent = 'Last: --'; deltaEl.textContent = 'Delta: --';
        draw([], null); status.textContent = message;
    }
    socket.on('laptime_graph_update', function(data) {
        if (!object(data)) { clear('No data'); return; }
        lastUpdate = Date.now();
        const records = Array.isArray(data.records) ? data.records.filter(object).slice(-10) : [];
        const times = records.map(r => r.time_s).filter(valid);
        const best = valid(data.best_lap_time) ? data.best_lap_time : times.length ? Math.min(...times) : null;
        bestLabel.textContent = valid(data.best_lap_time) ? 'SESSION BEST' : 'OBSERVED BEST';
        const bestRecord = records.find(r => r.time_s === best);
        band.textContent = lap(best);
        temp.textContent = bestRecord && number(bestRecord.track_temp_c) ? bestRecord.track_temp_c.toFixed(1) + '°C' : '--';
        rows.textContent = '';
        records.forEach(r => {
            const row = document.createElement('div');
            row.className = 'laplog-row rah-table-row' + (valid(r.time_s) && r.time_s === best ? ' rah-best' : '');
            const delta = valid(r.time_s) && valid(best) ? r.time_s - best : null;
            [Number.isInteger(r.lap_number) && r.lap_number >= 0 ? r.lap_number : '--', lap(r.time_s),
                signed(delta), number(r.track_temp_c) ? r.track_temp_c.toFixed(1) + '°C' : '--',
                r.incident === true ? '×' : r.incident === false ? '·' : '--'].forEach((value, i) => {
                const cell = document.createElement('span'); cell.textContent = value;
                if (i === 2 && delta > 0) cell.className = 'rah-slower';
                if (i === 4 && r.incident === true) cell.className = 'rah-slower';
                row.appendChild(cell);
            });
            rows.appendChild(row);
        });
        // Legacy history still plots without inventing labels or observation metadata.
        const chart = records.length ? records : (Array.isArray(data.history) ? data.history.slice(-10).map(t => ({time_s: t})) : []);
        draw(chart, Math.min(...chart.map(r => r.time_s).filter(valid)));
        bestEl.textContent = 'Best: ' + (valid(data.best_lap_time) ? data.best_lap_time.toFixed(3) : '--');
        lastEl.textContent = 'Last: ' + lap(data.last_lap_time);
        deltaEl.textContent = 'Delta: ' + (data.delta_valid === true ? signed(data.delta_to_best) : '--');
        status.textContent = times.length ? 'Live' : 'No observed laps';
    });
    socket.on('connect', () => clear('Waiting for data'));
    socket.on('disconnect', () => clear('Disconnected'));
    socket.on('connect_error', () => clear('Disconnected'));
    setInterval(() => { if (lastUpdate !== null && Date.now() - lastUpdate > 3000) clear('Stale: no data'); }, 1000);
    clear('Waiting for data');
});
