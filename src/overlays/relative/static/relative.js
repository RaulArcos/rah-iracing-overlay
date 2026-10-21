document.addEventListener("DOMContentLoaded", function() {
    const socket = io('/relative', {
        reconnection: true,
        reconnectionAttempts: Infinity,
        reconnectionDelay: 1000,
        reconnectionDelayMax: 5000,
        timeout: 20000
    });

    const playerPos = document.getElementById('player-pos');
    const body = document.getElementById('relative-body');

    socket.on('relative_update', function(data) {
        if (!data || typeof data !== 'object') {
            return;
        }

        playerPos.textContent = `P${data.player_position || 0}`;
        const cars = Array.isArray(data.cars) ? data.cars : [];

        body.innerHTML = cars.slice(0, 12).map(function(car) {
            const gap = typeof car.gap === 'number' && isFinite(car.gap) ? car.gap : 0;
            // Positive gap = the car is ahead of the player (iRacing sign
            // convention); negative = behind.
            const rowClass = gap > 0 ? 'row-ahead' : 'row-behind';
            const pitClass = car.on_pit_road ? 'row-pit' : '';
            const estimatePrefix = car.gap_is_estimate ? '~' : '';
            const gapLabel = `${estimatePrefix}${gap > 0 ? '+' : ''}${gap.toFixed(2)}s`;
            const name = (car.name || `Car ${car.car_idx || 0}`).slice(0, 20);

            return `
                <tr class="${rowClass} ${pitClass}">
                    <td>${car.position || 0}</td>
                    <td>#${car.car_number || car.car_idx || 0}</td>
                    <td>${name}</td>
                    <td>${gapLabel}</td>
                </tr>
            `;
        }).join('');
    });
});
