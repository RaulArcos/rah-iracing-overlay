document.addEventListener('DOMContentLoaded', function() {
    const socket = io('/blindspot', { reconnection: true, reconnectionAttempts: Infinity,
        reconnectionDelay: 1000, reconnectionDelayMax: 5000, timeout: 20000 });
    const el = id => document.getElementById(id);
    const status = el('status-msg');
    let lastUpdate = null;
    function render(data) {
        const left = data.left_alert === true, right = data.right_alert === true;
        el('left-zone').classList.toggle('active', left);
        el('right-zone').classList.toggle('active', right);
        el('left-label').textContent = left ? 'CAR LEFT' : data.left_alert === false ? 'LEFT —' : 'LEFT ?';
        el('right-label').textContent = right ? 'CAR RIGHT' : data.right_alert === false ? 'RIGHT —' : 'RIGHT ?';
        el('proximity-panel').classList.toggle('both-active', left && right);
        const known = typeof data.left_alert === 'boolean' && typeof data.right_alert === 'boolean';
        status.textContent = left && right ? 'CARS BOTH SIDES' :
            [left ? 'CAR LEFT' : right ? 'CAR RIGHT' : '', known ? '' : 'Spotter unavailable'].filter(Boolean).join(' · ') || 'No side alerts';
    }
    function clear(reason) {
        lastUpdate = null;
        render({});
        status.textContent = reason;
    }
    socket.on('blindspot_update', data => {
        if (!data || typeof data !== 'object' || Array.isArray(data)) {
            clear('Spotter unavailable');
            return;
        }
        lastUpdate = Date.now();
        render(data);
    });
    socket.on('disconnect', () => clear('Disconnected · unavailable'));
    socket.on('connect_error', () => clear('Connection unavailable'));
    setInterval(() => {
        if (lastUpdate !== null && Date.now() - lastUpdate > 3000) clear('Stale · unavailable');
    }, 250);
    clear('Spotter unavailable');
});
