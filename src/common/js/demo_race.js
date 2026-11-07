/* Fictional Harbor Park endurance race. Browser-only, no simulator provenance. */
(function (global) {
    'use strict';
    const names = ['Avery Vale', 'Morgan Reed', 'Casey Hart', 'Riley Stone',
        'Jordan Lake', 'Alex North', 'Taylor West', 'Sam Rivers', 'Jamie Frost'];
    const colors = ['#55b9ff', '#ed9251', '#a88bfa'];
    const classNames = ['GTP', 'LMP2', 'GT3'];
    const lapTimes = [91.432, 91.108, 91.754, 90.987, 91.250,
        90.842, 91.325, 91.075, 90.915, 91.126];
    const round = value => Math.round(value * 1000) / 1000;
    function race(tick) {
        // Four-lap replay, each lap 360 frames at 250 ms. No wall-clock input.
        const t = ((Math.floor(tick) % 1440) + 1440) % 1440;
        // Continuous time for smooth in-between frames; equals t on whole ticks.
        const tf = t + (tick - Math.floor(tick));
        const phaseF = tf % 360;
        const completed = 22 + Math.floor(t / 360);
        const phase = t % 360;
        // One pit stop per four-lap replay (lap 4), not every lap, so the demo
        // opens at racing pace instead of crawling down the pit lane.
        const pit = Math.floor(t / 360) === 3 && phase >= 290 && phase <= 340;
        const records = lapTimes.map((time, i) => ({lap_number: completed - 9 + i,
            time_s: round(time + Math.floor(t / 360) * .012),
            track_temp_c: round(31.2 + i * .08), incident: i === 2}));
        const best = Math.min(...records.map(r => r.time_s));
        const cars = names.map((name, i) => {
            const group = Math.floor(i / 3), rank = i % 3 + 1;
            const player = i === 4;
            const delta = round((i - 4) * .175);
            const recent = records.slice(-5).map(r => round(r.time_s + delta));
            const mean = round(recent.reduce((a, b) => a + b, 0) / recent.length);
            const slope = round(recent.reduce((sum, value, j) => sum + (j - 2) * (value - mean), 0) / 10);
            // Gaps breathe visibly (±0.2 s) but never let neighbours swap order.
            const offset = (4 - i) * .004 + Math.sin(tf / 16 + i) * .0025;
            return {car_idx: i, name, car_number: String(11 + i * 7), position: i + 1,
                class_position: rank, class_id: group + 1, class_name: classNames[group],
                class_color: colors[group], is_player: player, laps_completed: completed,
                best_lap_s: round(best + delta), last_lap_s: recent.at(-1),
                best_lap_delta_s: round((rank - 1) * .175), on_pit_road: player && pit,
                gap_to_leader_s: round(i * 1.5), laps_down: 0, interval_s: rank === 1 ? 0 : 1.5,
                irating: 2800 - i * 85, license: 'A', safety_rating: round(3.8 - i * .07),
                license_color: '#55b9ff', positions_gained: null, positions_gained_source: null,
                lap_dist_pct: (phaseF / 360 + offset + 1) % 1, track_surface: 3,
                gap: player ? 0 : round(offset * 90), gap_is_estimate: !player, lap_delta: 0,
                recent_laps_s: recent, pace: {avg_lap_s: mean, laps: 5,
                    trend: slope <= -.03 ? 'improving' : slope >= .03 ? 'worsening' : 'steady',
                    trend_s_per_lap: slope}};
        });
        const player = cars[4];
        const rival = i => {
            const car = cars[i];
            const deltas = car.recent_laps_s.map((v, j) => round(v - player.recent_laps_s[j]));
            return {...car, gap_s: round(1.5 + Math.sin(tf / 16) * .35),
                last_lap_delta_s: round(car.last_lap_s - player.last_lap_s),
                best_lap_delta_s: round(car.best_lap_s - player.best_lap_s),
                pace_delta_s: round(car.pace.avg_lap_s - player.pace.avg_lap_s), recent_deltas_s: deltas};
        };
        const summary = {session_type: 'Race', elapsed_s: 1980 + t / 4,
            time_limit_s: 3600, lap: completed + 1, lap_limit: 40,
            track_temp_c: 32 + Math.sin(t / 180) * .3, field_size: cars.length};
        const classes = classNames.map((name, i) => ({class_id: i + 1, class_name: name,
            known: true, class_color: colors[i], cars: cars.slice(i * 3, i * 3 + 3),
            sof: {value: 2714 - i * 255, total: 3, rated: 3, complete: true}}));
        return {t, tf, phase, pit, records, best, cars, player, rival, summary, classes, round};
    }
    global.RAHDemoRace = {race};
}(globalThis));
