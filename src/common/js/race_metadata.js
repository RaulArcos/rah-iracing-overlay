/* Shared, null-first presentation for Relative and Standings only. */
const RahRaceMetadata = (() => {
    const numeric = value => typeof value === 'number' && Number.isFinite(value);
    const positive = value => numeric(value) && Number.isInteger(value) && value > 0;
    const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
    const safeColor = value => typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value);
    function cell(value, className = '') {
        const el = document.createElement('span');
        el.className = 'rah-num ' + className;
        el.textContent = value;
        return el;
    }
    function paint(el, property, value) {
        if (safeColor(value)) el.style.setProperty(property, value);
    }
    function rating(value) {
        return positive(value) ? (value / 1000).toFixed(1) + 'k' : '--';
    }
    function license(car) {
        if (car.is_ai === true) return 'AI';
        if (!/^(R|D|C|B|A|P|Pro|WC)$/.test(car.license || '')) return '--';
        return car.license + (numeric(car.safety_rating) && car.safety_rating > 0 && car.safety_rating < 5
            ? ' ' + car.safety_rating.toFixed(2) : ' --');
    }
    function gain(car) {
        return car.positions_gained_source && Number.isInteger(car.positions_gained)
            ? (car.positions_gained > 0 ? '+' : '') + car.positions_gained : '--';
    }
    function badges(car) {
        const lic = cell(license(car), 'race-license rah-badge');
        paint(lic, '--rah-license-color', car.license_color);
        const ir = cell(car.is_ai === true ? '--' : rating(car.irating), 'race-rating rah-badge');
        const reason = car.profile_unavailable_reason === 'ai_session_placeholder'
            ? 'Online profile unavailable: SDK supplies AI-session placeholders, not account license/iRating'
            : car.is_ai === true ? 'AI driver: no account license or iRating' : null;
        ir.title = reason || (positive(car.irating) ? 'iRating ' + car.irating : 'iRating unavailable');
        lic.title = reason || 'SDK license / safety rating; -- when unavailable';
        if (car.profile_source === 'last_online') {
            // AI session: last profile seen in an online session, not live data.
            const seen = numeric(car.profile_seen_at)
                ? ' (' + new Date(car.profile_seen_at * 1000).toLocaleDateString() + ')' : '';
            const note = 'Last known from an online session' + seen + '; AI sessions do not report your profile';
            ir.title = note; lic.title = note;
            ir.className += ' is-last-known'; lic.className += ' is-last-known';
        }
        const positions = cell(gain(car), 'race-gain');
        positions.title = 'Positions gained from confirmed race start; -- when unavailable';
        if (gain(car) !== '--') positions.className += car.positions_gained > 0 ? ' rah-improved' : ' rah-slower';
        return [lic, ir, positions];
    }
    function sof(value) {
        if (object(value) && value.is_ai_session === true) return 'AI session';
        if (!object(value) || !positive(value.value)) return 'SoF --';
        return 'SoF ' + value.value + (value.complete === true ? '' : ' · partial ' + value.rated + '/' + value.total);
    }
    function clock(seconds) {
        if (!numeric(seconds) || seconds < 0) return '--';
        const total = Math.floor(seconds);
        return Math.floor(total / 60) + ':' + String(total % 60).padStart(2, '0');
    }
    function summary(value) {
        if (!object(value)) return '--';
        return (typeof value.session_type === 'string' ? value.session_type : '--') +
            ' · Lap ' + (positive(value.lap) ? value.lap : '--') + '/' +
            (positive(value.lap_limit) ? value.lap_limit : '--') + ' · ' +
            clock(value.elapsed_s) + ' / ' + clock(value.time_limit_s);
    }
    return {numeric, positive, object, cell, paint, rating, license, badges, sof, summary};
})();
