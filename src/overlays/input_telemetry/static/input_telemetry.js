document.addEventListener("DOMContentLoaded", function() {
    var socket = io('/input_telemetry', {
        reconnection: true,
        reconnectionAttempts: Infinity,
        reconnectionDelay: 1000,
        reconnectionDelayMax: 5000,
        timeout: 20000
    });

    // Track connection status
    let isConnected = false;
    let reconnectTimer = null;

    const HISTORY = 300; // samples kept on screen, independent of canvas pixels
    const canvas = document.getElementById("telemetry-graph");
    const ctx = canvas.getContext("2d");
    const steeringWheelImage = document.getElementById("steering-wheel");
    const gearEl = document.getElementById('gear-display');
    const speedEl = document.getElementById('speed-display');
    const fills = {
        brake: document.getElementById('brake-fill'),
        throttle: document.getElementById('throttle-fill'),
        clutch: document.getElementById('clutch-fill')
    };
    const values = {
        brake: document.getElementById('brake-value'),
        throttle: document.getElementById('throttle-value'),
        clutch: document.getElementById('clutch-value')
    };

    let throttleData = [];
    let brakeData = [];
    let clutchData = [];
    let dirty = true;
    let colors = null;

    socket.on('connect', function() {
        isConnected = true;
        clearTimeout(reconnectTimer);
    });

    socket.on('telemetry_update', function(data) {
        updateTelemetryData(data);
    });

    // Handle heartbeats to ensure connection is alive
    socket.on('heartbeat', function() {});

    socket.on('disconnect', function() {
        isConnected = false;
        // Try to reconnect manually if socket.io reconnection fails
        reconnectTimer = setTimeout(function() {
            if (!isConnected) {
                socket.connect();
            }
        }, 3000);
    });

    socket.on('error', function(error) {
        console.error("Socket error:", error);
    });

    function cssColor(name, fallback) {
        const container = document.querySelector('.telemetry-container');
        const value = container ? getComputedStyle(container).getPropertyValue(name).trim() : '';
        return value || fallback;
    }

    function readColors() {
        colors = {
            throttle: cssColor('--it-throttle', '#4fdc8a'),
            brake: cssColor('--it-brake', '#ff4d4d'),
            clutch: cssColor('--it-clutch', '#6ea8ff')
        };
    }

    // Render at the real pixel density so lines stay crisp at any zoom.
    function resizeCanvas() {
        const rect = canvas.getBoundingClientRect();
        const ratio = window.devicePixelRatio || 1;
        const width = Math.max(1, Math.round(rect.width * ratio));
        const height = Math.max(1, Math.round(rect.height * ratio));
        if (canvas.width !== width || canvas.height !== height) {
            canvas.width = width;
            canvas.height = height;
        }
        dirty = true;
    }

    function clamp01(value) {
        return typeof value === 'number' && isFinite(value) ? Math.max(0, Math.min(1, value)) : 0;
    }

    function updateTelemetryData(data) {
        // Validate input data
        if (!data || typeof data !== 'object') {
            return;
        }

        // Process gear with validation
        let gearValue = data.gear;
        if (gearValue === null || gearValue === undefined) gearValue = 0;
        gearEl.textContent = gearValue === 0 ? "N" : gearValue === -1 ? "R" : gearValue;

        // Process speed with validation
        let speedValue = parseFloat(data.speed);
        if (isNaN(speedValue)) speedValue = 0;
        speedEl.textContent = `${speedValue.toFixed(0)} km/h`;

        // Process pedal inputs with validation
        const brakeValue = clamp01(data.brake);
        const throttleValue = clamp01(data.throttle);
        const clutchValue = clamp01(data.clutch);

        fills.brake.style.height = `${brakeValue * 100}%`;
        fills.throttle.style.height = `${throttleValue * 100}%`;
        fills.clutch.style.height = `${clutchValue * 100}%`;
        values.brake.textContent = Math.round(brakeValue * 100);
        values.throttle.textContent = Math.round(throttleValue * 100);
        values.clutch.textContent = Math.round(clutchValue * 100);

        // Process steering angle with validation
        const steeringAngleRadians = typeof data.steering_wheel_angle === 'number' ? data.steering_wheel_angle : 0;
        const steeringAngleDegrees = -steeringAngleRadians * (180 / Math.PI);
        steeringWheelImage.style.transform = `rotate(${steeringAngleDegrees}deg)`;

        // Update graph history
        throttleData.push(throttleValue);
        brakeData.push(brakeValue);
        clutchData.push(clutchValue);
        if (throttleData.length > HISTORY) {
            throttleData.shift();
            brakeData.shift();
            clutchData.shift();
        }
        dirty = true;
    }

    function trace(series, color, width, fillAlpha) {
        if (series.length < 2) return;
        const w = canvas.width, h = canvas.height;
        const pad = Math.round(4 * (window.devicePixelRatio || 1));
        const step = w / (HISTORY - 1);
        const offset = (HISTORY - series.length) * step;
        const y = v => pad + (1 - v) * (h - pad * 2);
        ctx.beginPath();
        series.forEach((value, index) => {
            const x = offset + index * step;
            if (index === 0) ctx.moveTo(x, y(value)); else ctx.lineTo(x, y(value));
        });
        if (fillAlpha > 0) {
            ctx.save();
            ctx.lineTo(offset + (series.length - 1) * step, h);
            ctx.lineTo(offset, h);
            ctx.closePath();
            const gradient = ctx.createLinearGradient(0, 0, 0, h);
            gradient.addColorStop(0, color);
            gradient.addColorStop(1, 'transparent');
            ctx.globalAlpha = fillAlpha;
            ctx.fillStyle = gradient;
            ctx.fill();
            ctx.restore();
            ctx.beginPath();
            series.forEach((value, index) => {
                const x = offset + index * step;
                if (index === 0) ctx.moveTo(x, y(value)); else ctx.lineTo(x, y(value));
            });
        }
        ctx.strokeStyle = color;
        ctx.lineWidth = width;
        ctx.stroke();
    }

    function drawGraph() {
        const ratio = window.devicePixelRatio || 1;
        const w = canvas.width, h = canvas.height;
        ctx.clearRect(0, 0, w, h);
        if (!colors) readColors();

        // Quiet 25 % grid
        ctx.strokeStyle = 'rgba(255,255,255,0.06)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        [0.25, 0.5, 0.75].forEach(f => {
            const y = Math.round(h * f) + 0.5;
            ctx.moveTo(0, y);
            ctx.lineTo(w, y);
        });
        ctx.stroke();

        ctx.lineJoin = 'round';
        ctx.lineCap = 'round';
        const hideClutch = document.documentElement.classList.contains('rah-no-clutch');
        if (!hideClutch) trace(clutchData, colors.clutch, 1.5 * ratio, 0);
        trace(throttleData, colors.throttle, 2 * ratio, 0.22);
        trace(brakeData, colors.brake, 2 * ratio, 0.22);
    }

    function animate() {
        if (dirty) {
            dirty = false;
            drawGraph();
        }
        requestAnimationFrame(animate);
    }

    if (typeof ResizeObserver === 'function') {
        new ResizeObserver(resizeCanvas).observe(canvas);
    }
    window.addEventListener('rah-settings', function() { colors = null; resizeCanvas(); });
    resizeCanvas();
    requestAnimationFrame(animate);
});
