document.addEventListener("DOMContentLoaded", function() {
    const socket = io('/weather', {
        reconnection: true,
        reconnectionAttempts: Infinity,
        reconnectionDelay: 1000,
        reconnectionDelayMax: 5000,
        timeout: 20000
    });

    const UNAVAILABLE = '—';
    const STALE_AFTER_MS = 3000;

    const airEl = document.getElementById('wx-air');
    const trackEl = document.getElementById('wx-track');
    const humidityEl = document.getElementById('wx-humidity');
    const windEl = document.getElementById('wx-wind');
    const windMsEl = document.getElementById('wx-wind-ms');
    const windDirEl = document.getElementById('wx-wind-dir');
    const precipEl = document.getElementById('wx-precip');
    const wetnessEl = document.getElementById('wx-wetness');
    const declaredEl = document.getElementById('wx-declared');
    const statusEl = document.getElementById('wx-status');
    const valueEls = [airEl, trackEl, humidityEl, windEl, windMsEl, windDirEl, precipEl, wetnessEl, declaredEl];

    let lastUpdate = null;

    function isNumber(value) {
        return typeof value === 'number' && isFinite(value);
    }

    function formatted(value, digits, suffix) {
        return isNumber(value) ? value.toFixed(digits) + (suffix || '') : UNAVAILABLE;
    }

    function setLevel(el, level) {
        el.classList.toggle('rah-status--ok', level === 'ok');
        el.classList.toggle('rah-status--warn', level === 'warn');
        el.classList.toggle('rah-status--bad', level === 'bad');
    }

    function renderWetness(data) {
        if (typeof data.track_wetness === 'string' && data.track_wetness.length) {
            wetnessEl.textContent = data.track_wetness.replace(/_/g, ' ').toUpperCase();
        } else {
            wetnessEl.textContent = isNumber(data.track_wetness_code) ? 'CODE ' + data.track_wetness_code : UNAVAILABLE;
        }
    }

    // The steward's rain-tire declaration is text first, colour second.
    function renderDeclared(declaredWet) {
        if (typeof declaredWet !== 'boolean') {
            declaredEl.textContent = UNAVAILABLE;
            setLevel(declaredEl, null);
            return;
        }
        declaredEl.textContent = declaredWet ? 'YES' : 'NO';
        setLevel(declaredEl, declaredWet ? 'warn' : null);
    }

    function setStatus(text, level) {
        statusEl.textContent = text;
        setLevel(statusEl, level);
    }

    function clear(text, level) {
        lastUpdate = null;
        valueEls.forEach(function(el) {
            el.textContent = UNAVAILABLE;
            setLevel(el, null);
        });
        setStatus(text, level);
    }

    function render(data) {
        airEl.textContent = formatted(data.air_temp_c, 1);
        trackEl.textContent = formatted(data.track_temp_c, 1);
        humidityEl.textContent = formatted(data.humidity_pct, 0, '%');
        windEl.textContent = formatted(data.wind_speed_kmh, 1);
        windMsEl.textContent = formatted(data.wind_speed_ms, 1, ' m/s');
        windDirEl.textContent = formatted(data.wind_dir_deg, 0, '°');
        precipEl.textContent = formatted(data.precipitation_pct, 1, '%');
        renderWetness(data);
        renderDeclared(data.declared_wet);
        setStatus('Live', 'ok');
    }

    socket.on('connect', function() {
        clear('Waiting for data', 'warn');
    });

    socket.on('disconnect', function() {
        clear('Disconnected', 'bad');
    });

    socket.on('connect_error', function() {
        clear('Disconnected', 'bad');
    });

    socket.on('weather_update', function(data) {
        if (!data || typeof data !== 'object' || Array.isArray(data)) {
            clear('No data', 'warn');
            return;
        }
        lastUpdate = Date.now();
        render(data);
    });

    setInterval(function() {
        if (lastUpdate !== null && Date.now() - lastUpdate > STALE_AFTER_MS) {
            clear('Stale: no data', 'warn');
        }
    }, 1000);
});
