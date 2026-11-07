document.addEventListener('DOMContentLoaded', function() {
    const socket = io('/delta', {reconnection: true, reconnectionAttempts: Infinity,
        reconnectionDelay: 1000, reconnectionDelayMax: 5000, timeout: 20000});
    const el = id => document.getElementById(id);
    const timeBox = el('dl-time-box');
    const timeEl = el('dl-time');
    const timeNote = el('dl-time-note');
    const deltaBox = el('dl-delta');
    const deltaValue = el('dl-delta-value');
    const barFill = el('dl-bar-fill');
    const sectorsEl = el('dl-sectors');
    const split = el('dl-split');
    const lapEl = el('dl-lap');
    const status = el('dl-status');
    const STATES = ['purple', 'green', 'yellow', 'out'];
    const BAR_RANGE_S = 1.0;
    let lastUpdate = null;
    let boxes = [];
    let shown = [];          // signature of what each sector box shows
    let lastSplitKey = null;
    let finalKey = null;
    let primed = false;      // no F1 animations for what was already there on load

    const num = v => typeof v === 'number' && Number.isFinite(v);
    // State lives in classes (st-purple / st-green / st-yellow / st-out).
    function setState(node, state) {
        STATES.forEach(name => node.classList.remove('st-' + name));
        node.classList.toggle('has-state', !!state);
        if (state) node.classList.add('st-' + state);
    }
    function clock(seconds) {
        if (!num(seconds) || seconds < 0) return '--:--.---';
        const ms = Math.round(seconds * 1000);
        const m = Math.floor(ms / 60000);
        const s = Math.floor(ms / 1000) % 60;
        return m + ':' + String(s).padStart(2, '0') + '.' + String(ms % 1000).padStart(3, '0');
    }
    function sectorClock(seconds) {
        if (!num(seconds)) return '';
        return seconds >= 60 ? clock(seconds) : seconds.toFixed(3);
    }
    function signed(value, digits) {
        return num(value) ? (value > 0 ? '+' : value < 0 ? '−' : '±') + Math.abs(value).toFixed(digits) : '--';
    }
    function setStatus(text, level) {
        status.textContent = text;
        status.classList.toggle('rah-status--ok', level === 'ok');
        status.classList.toggle('rah-status--warn', level === 'warn');
        status.classList.toggle('rah-status--bad', level === 'bad');
    }

    function buildSectors(count) {
        if (boxes.length === count) return;
        sectorsEl.textContent = '';
        sectorsEl.classList.toggle('many', count > 4);
        boxes = [];
        shown = [];
        for (let i = 0; i < count; i++) {
            const box = document.createElement('div');
            box.className = 'dl-sector';
            const progress = document.createElement('div');
            progress.className = 'dl-sector__progress';
            const fill = document.createElement('div');
            fill.className = 'dl-sector__fill';
            const label = document.createElement('span');
            label.className = 'dl-sector__label';   // "S1", "S2"… drawn by a CSS counter
            const time = document.createElement('span');
            time.className = 'dl-sector__time';
            [progress, fill, label, time].forEach(child => box.appendChild(child));
            sectorsEl.appendChild(box);
            boxes.push({box, progress, time});
            shown.push('');
        }
    }

    function paintSector(i, result, animate) {
        const {box, time} = boxes[i];
        const state = result && STATES.includes(result.state) ? result.state : null;
        const signature = state ? state + ':' + result.time_s : '';
        if (signature === shown[i]) return;
        shown[i] = signature;
        setState(box, state);
        time.textContent = result ? sectorClock(result.time_s) : '';
        box.classList.remove('just-set');
        if (state && animate) {
            void box.offsetWidth;            // restart the animation
            box.classList.add('just-set');
        }
    }

    function showSplit(result) {
        if (!result || !STATES.includes(result.state)) return;
        split.textContent = '';
        setState(split, result.state);
        const head = document.createElement('div');
        head.className = 'dl-split__head';
        const name = document.createElement('span');
        name.textContent = 'Sector ' + (result.index + 1);
        const delta = document.createElement('span');
        if (num(result.delta_pb_s)) {
            delta.className = result.delta_pb_s < 0 ? 'is-gain' : result.delta_pb_s > 0 ? 'is-loss' : '';
            delta.textContent = signed(result.delta_pb_s, 3);
        } else {
            delta.textContent = result.state === 'out' ? 'OUT LAP' : 'FIRST';
        }
        head.appendChild(name);
        head.appendChild(delta);
        const time = document.createElement('div');
        time.className = 'dl-split__time';
        time.textContent = sectorClock(result.time_s);
        split.appendChild(head);
        split.appendChild(time);
        split.classList.remove('show');
        void split.offsetWidth;
        split.classList.add('show');
    }

    function setDelta(value) {
        if (!num(value)) {
            deltaBox.classList.remove('sign-gain', 'sign-loss');
            deltaValue.textContent = '--.---';
            barFill.className = 'dl-bar__fill';
            barFill.style.width = '0';
            barFill.style.left = '50%';
            return;
        }
        const sign = value < 0 ? 'gain' : value > 0 ? 'loss' : 'none';
        deltaBox.classList.toggle('sign-gain', sign === 'gain');
        deltaBox.classList.toggle('sign-loss', sign === 'loss');
        deltaValue.textContent = signed(value, 3);
        const half = Math.min(Math.abs(value), BAR_RANGE_S) / BAR_RANGE_S * 50;
        barFill.className = 'dl-bar__fill ' + sign;
        barFill.style.width = half + '%';
        barFill.style.left = value < 0 ? (50 - half) + '%' : '50%';
    }

    function clear(message, level) {
        lastUpdate = null;
        timeEl.textContent = '--:--.---';
        timeNote.textContent = 'Lap time';
        setState(timeBox, null);
        timeBox.classList.remove('is-final');
        lapEl.textContent = 'Lap --';
        setDelta(null);
        boxes.forEach((_, i) => paintSector(i, null, false));
        boxes.forEach(b => { b.box.classList.remove('is-current'); b.progress.style.width = '0'; });
        setStatus(message, level);
    }

    function render(data) {
        const starts = Array.isArray(data.sector_starts) && data.sector_starts.length ? data.sector_starts : [0, 1 / 3, 2 / 3];
        buildSectors(starts.length);
        lapEl.textContent = Number.isInteger(data.lap) ? 'Lap ' + data.lap : 'Lap --';
        const last = data.last && typeof data.last === 'object' ? data.last : null;
        const hold = num(data.result_hold_s) ? data.result_hold_s : 7;
        const holding = last && num(data.last_age_s) && data.last_age_s < hold;
        const current = Array.isArray(data.current) ? data.current : [];

        if (holding) {
            // Lap just finished: freeze the lap time in its colour, F1 style.
            const key = String(last.time_s) + '|' + (last.sectors || []).map(s => s.time_s).join(',');
            timeEl.textContent = clock(last.time_s);
            timeNote.textContent = last.state === 'out' ? 'Out lap' : num(last.delta_pb_s)
                ? 'Lap · ' + signed(last.delta_pb_s, 3) + ' to best' : 'Lap complete';
            setState(timeBox, STATES.includes(last.state) ? last.state : null);
            if (key !== finalKey) {
                finalKey = key;
                timeBox.classList.remove('is-final');
                void timeBox.offsetWidth;
                if (primed) timeBox.classList.add('is-final');
            }
            const byIndex = {};
            (last.sectors || []).forEach(s => { byIndex[s.index] = s; });
            boxes.forEach((b, i) => {
                paintSector(i, byIndex[i] || null, primed);
                b.box.classList.remove('is-current');
                b.progress.style.width = '0';
            });
            const finalSector = (last.sectors || []).slice(-1)[0];
            const splitKey = finalSector ? 'L' + key : null;
            if (splitKey && splitKey !== lastSplitKey) { lastSplitKey = splitKey; if (primed) showSplit(finalSector); }
        } else {
            setState(timeBox, null);
            timeBox.classList.remove('is-final');
            timeEl.textContent = clock(data.lap_time_s);
            timeNote.textContent = data.out_lap ? 'Out lap' : 'Lap time';
            const byIndex = {};
            current.forEach(s => { byIndex[s.index] = s; });
            const pct = num(data.lap_dist_pct) ? data.lap_dist_pct : null;
            boxes.forEach((b, i) => {
                paintSector(i, byIndex[i] || null, primed);
                const isCurrent = data.current_sector === i && !byIndex[i];
                b.box.classList.toggle('is-current', isCurrent);
                let progress = 0;
                if (isCurrent && pct !== null) {
                    const from = starts[i], to = i + 1 < starts.length ? starts[i + 1] : 1;
                    progress = Math.max(0, Math.min(1, (pct - from) / (to - from)));
                }
                b.progress.style.width = (progress * 100) + '%';
            });
            const latest = current.slice(-1)[0];
            const splitKey = latest ? 'S' + latest.index + ':' + latest.time_s : null;
            if (splitKey && splitKey !== lastSplitKey) { lastSplitKey = splitKey; if (primed) showSplit(latest); }
        }
        setDelta(data.delta_s);
        primed = true;
        setStatus(data.available === false ? 'Not on track' : 'Live', data.available === false ? 'warn' : 'ok');
    }

    socket.on('delta_update', function(data) {
        if (!data || typeof data !== 'object' || Array.isArray(data)) {
            clear('No data', 'warn');
            return;
        }
        lastUpdate = Date.now();
        render(data);
    });
    socket.on('connect', () => clear('Waiting for data', 'warn'));
    socket.on('disconnect', () => clear('Disconnected', 'bad'));
    socket.on('connect_error', () => clear('Disconnected', 'bad'));
    setInterval(() => {
        if (lastUpdate !== null && Date.now() - lastUpdate > 3000) clear('Stale: no data', 'warn');
    }, 1000);
    buildSectors(3);
    clear('Waiting for data', 'warn');
});
