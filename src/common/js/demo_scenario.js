/* Public event payloads for the fictional race; never imported by the server. */
(function (global) {
    'use strict';
    const clamp01 = v => Math.max(0, Math.min(1, v));
    const ease = v => { v = clamp01(v); return v * v * (3 - 2 * v); };
    const span = (u, a, b) => clamp01((u - a) / (b - a));
    // Real-time driving loop: one corner every 4.5 s (18 ticks at 4 Hz) —
    // straight on full throttle, hard braking, turn-in, apex, exit.
    // Corners alternate left/right with varying severity.
    function driving(tf, pit) {
        if (pit) {
            return {gear: 2, speed: 58 + Math.sin(tf / 3) * .6, throttle: .32 + Math.sin(tf / 2) * .03,
                brake: 0, clutch: 0, steering_wheel_angle: Math.sin(tf / 7) * .08};
        }
        const cycle = 18, k = Math.floor(tf / cycle), u = (tf % cycle) / cycle;
        const dir = k % 2 ? 1 : -1, severity = .45 + .55 * ((k * 7) % 5) / 4;
        let throttle, brake, steer, f;
        if (u < .42) {            // straight
            throttle = 1; brake = 0;
            steer = Math.sin(tf * 3.1) * .04 + Math.sin(tf * 7.3) * .015;
            f = .35 + .65 * (1 - Math.pow(1 - span(u, 0, .42), 2));
        } else if (u < .6) {     // threshold braking, trail off, turn in late
            const b = span(u, .42, .6);
            throttle = 0;
            brake = b < .12 ? .95 * ease(b / .12) : .95 - .65 * ease((b - .12) / .88);
            steer = dir * severity * 1.2 * ease((b - .55) / .45);
            f = 1 - .95 * ease(b);
        } else if (u < .76) {     // apex: trail brake to maintenance throttle
            const c = span(u, .6, .76);
            brake = .3 * (1 - ease(c / .4));
            throttle = .15 + .25 * ease((c - .3) / .7);
            steer = dir * severity * (1.2 + .1 * Math.sin(c * Math.PI));
            f = .05 * (1 - c);
        } else {                  // exit: unwind and feed in throttle
            const e = span(u, .76, 1);
            brake = 0;
            throttle = .4 + .6 * ease(e / .7);
            steer = dir * severity * 1.2 * (1 - ease(e));
            f = .35 * ease(e);
        }
        const vmin = 95 - 45 * severity;
        const speed = vmin + (255 - vmin) * f;
        const gear = speed < 75 ? 2 : speed < 115 ? 3 : speed < 155 ? 4 : speed < 195 ? 5 : 6;
        const blip = u > .44 && u < .47 ? .7 : 0; // clutch blip on the downshift
        return {gear, speed, throttle: clamp01(throttle), brake: clamp01(brake), clutch: blip,
            steering_wheel_angle: steer};
    }

    // F1-style qualifying timer for the Delta overlay: a four-lap run where
    // the driver improves, so every colour shows up — purple (session best,
    // including the other cars' RIVAL sectors), green (personal best) and
    // yellow (slower than personal best). History is the run's earlier laps.
    const BASE = [29.10, 32.40, 28.80];
    const VARIATION = [[.30, .30, .30], [.15, .40, .05], [-.35, -.20, -.05], [-.25, -.25, -.30]];
    const RIVAL = [28.90, 32.25, 28.62];
    const loopLap = lap => ((lap % 4) + 4) % 4;
    const lapSectors = lap => BASE.map((b, j) => +(b + VARIATION[loopLap(lap)][j]).toFixed(3));
    const total = sectors => sectors.reduce((a, b) => a + b, 0);
    const history = lap => Array.from({length: loopLap(lap)}, (_, k) => lapSectors(k));
    function sectorResults(lap) {
        const mine = lapSectors(lap), past = history(lap);
        return mine.map((time, j) => {
            const pb = past.length ? Math.min(...past.map(h => h[j])) : null;
            const overall = pb === null ? RIVAL[j] : Math.min(pb, RIVAL[j]);
            return {index: j, time_s: time, delta_pb_s: pb === null ? null : +(time - pb).toFixed(3),
                state: time < overall ? 'purple' : pb === null || time < pb ? 'green' : 'yellow'};
        });
    }
    function lapResult(lap) {
        const time = total(lapSectors(lap)), past = history(lap).map(total);
        const pb = past.length ? Math.min(...past) : null;
        const overall = pb === null ? total(RIVAL) : Math.min(pb, total(RIVAL));
        return {time_s: +time.toFixed(3), sectors: sectorResults(lap),
            delta_pb_s: pb === null ? null : +(time - pb).toFixed(3),
            state: time < overall ? 'purple' : pb === null || time < pb ? 'green' : 'yellow'};
    }
    function qualifying(tf) {
        const lapLen = 360, lap = Math.floor(tf / lapLen), phase = (tf % lapLen) / lapLen;
        const sectors = lapSectors(lap), lapTime = total(sectors);
        const starts = [0, sectors[0] / lapTime, (sectors[0] + sectors[1]) / lapTime];
        const results = sectorResults(lap);
        const done = starts.map((_, j) => j + 1 < starts.length && phase >= starts[j + 1]);
        // Live delta to the best earlier lap (the previous run's best on lap 1).
        const past = history(lap);
        const ref = past.length ? past.reduce((a, b) => total(a) <= total(b) ? a : b) : lapSectors(3);
        let delta = 0;
        sectors.forEach((time, j) => {
            const from = starts[j], to = j + 1 < starts.length ? starts[j + 1] : 1;
            delta += Math.max(0, Math.min(1, (phase - from) / (to - from))) * (time - ref[j]);
        });
        return {available: true, lap: 22 + lap, lap_time_s: phase * lapTime, lap_dist_pct: phase,
            sector_starts: starts, current_sector: starts.filter(s => phase >= s).length - 1,
            current: results.filter((_, j) => done[j]), last: lapResult(lap - 1),
            last_age_s: phase * lapTime, result_hold_s: 7, best_lap_s: +total(ref).toFixed(3),
            delta_s: +delta.toFixed(3), delta_ref: 'personal_best', out_lap: false};
    }

    function frame(tick) {
        const r = global.RAHDemoRace.race(tick);
        const {t, tf, phase, pit, player, records, best, round} = r;
        const speed = driving(t, pit).speed;
        const fuel = round(38.4 - (t % 360) / 360 * 2.6);
        const remaining = 40 - r.summary.lap + 1;
        const left = Math.floor(t / 12) % 4 < 2, right = Math.floor(t / 12) % 4 === 1;
        const alerts = {left_alert: left, right_alert: right, both_alert: left && right};
        const data = {
            input_telemetry: driving(tf, pit),
            relative: {player_car_idx: 4, player_position: player.position, player,
                cars: r.cars.filter(c => !c.is_player), gap_is_estimate: true,
                player_class_sof: r.classes[1].sof, session_summary: r.summary},
            standings: {session_type: 'Race', gap_basis: 'race_f2time', player_car_idx: 4,
                classes: r.classes, session_summary: r.summary},
            battle_pace: {context: 'ok', class_id: 2, class_name: 'LMP2', session_type: 'Race',
                gap_basis: 'race_f2time', lap_time_source: 'simulated observed laps',
                player, ahead: r.rival(3), behind: r.rival(5)},
            track_map: {player_car_idx: 4, player_lap_dist_pct: player.lap_dist_pct, cars: r.cars},
            radar: {...alerts, track_length_m: 4500,
                nearby: r.cars.filter(c => !c.is_player).map(c => ({car_idx: c.car_idx,
                    distance_pct: round(c.gap / 90), relation: c.gap > 0 ? 'ahead' : 'behind'}))},
            blindspot: {...alerts, active: left || right,
                message: left && right ? 'CARS BOTH SIDES' : left ? 'CAR LEFT' : right ? 'CAR RIGHT' : 'CLEAR'},
            laptime_graph: {history: records.map(r => r.time_s), records, best_lap_time: best,
                last_lap_time: player.last_lap_s, current_lap_time: phase / 4,
                delta_to_best: round(Math.sin(t / 24) * .3), delta_valid: true},
            session_strip: {session_type: 'Race', limit: 'laps_and_time', session_laps_total: 40,
                session_time_total_s: 3600, laps_remaining: remaining,
                laps_remaining_source: 'simulated', time_remaining_s: 3600 - r.summary.elapsed_s,
                state: 'racing', state_code: 4, flags: ['green'],
                position: player.position, class_position: 2, lap: r.summary.lap},
            fuel_finish: {fuel_level_l: fuel, fuel_level_pct: fuel / 80 * 100,
                avg_burn_l_per_lap: 2.6, burn_sample_count: 10, burn_source: 'simulated observed laps',
                laps_of_fuel: fuel / 2.6, finish_laps_remaining: remaining, finish_basis: 'laps_remaining',
                finish_fuel_needed_l: remaining * 2.6,
                finish_fuel_to_add_l: Math.max(0, remaining * 2.6 - fuel), is_estimate: true, advisory: true},
            pit_assistant: {speed_kmh: speed, on_pit_road: pit, in_pit_stall: false,
                pits_open: true, service_active: false, pit_speed_limit_kmh: 60,
                pit_speed_limit_source: 'simulated', pit_speed_margin_kmh: pit ? 60 - speed : null,
                pit_speed_state: pit ? 'within_limit' : null,
                repair_left_s: 0, optional_repair_left_s: 4.5, tow_time_s: 0,
                service_flags: ['fuel_fill', 'lf_tire_change', 'rf_tire_change'], service_flags_raw: 19,
                service_status: 'none', service_status_code: 0,
                service_fuel_amount: 18, service_fuel_unit: 'L/kWh', service_fuel_requested: true, read_only: true},
            weather: {air_temp_c: 23.4, track_temp_c: r.summary.track_temp_c, humidity_pct: 54,
                wind_speed_ms: 3.2 + Math.sin(t / 50) * .4,
                wind_speed_kmh: (3.2 + Math.sin(t / 50) * .4) * 3.6,
                wind_dir_deg: 225 + Math.sin(t / 80) * 10, precipitation_pct: 0,
                track_wetness: 'dry', track_wetness_code: 1, declared_wet: false, observed: true},
            broadcast_driver: {...player, available: true, reason: null,
                camera_car_idx: 4, identity_available: true, session_type: 'Race', source: 'simulated camera'},
            delta: qualifying(tf)
        };
        Object.values(data).forEach(payload => { payload.simulated = true; });
        return data;
    }
    global.RAHDemoScenario = {frame};
}(globalThis));
