document.addEventListener("DOMContentLoaded", function() {
    const socket = io('/blindspot', {
        reconnection: true,
        reconnectionAttempts: Infinity,
        reconnectionDelay: 1000,
        reconnectionDelayMax: 5000,
        timeout: 20000
    });

    const leftZone = document.getElementById('left-zone');
    const rightZone = document.getElementById('right-zone');
    const statusMsg = document.getElementById('status-msg');

    socket.on('blindspot_update', function(data) {
        if (!data || typeof data !== 'object') {
            return;
        }

        const left = Boolean(data.left_alert);
        const right = Boolean(data.right_alert);

        leftZone.classList.toggle('active', left);
        rightZone.classList.toggle('active', right);
        statusMsg.textContent = data.message || 'CLEAR';
    });
});
