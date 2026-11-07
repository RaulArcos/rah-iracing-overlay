/*
 * RAH overlay settings runtime (injected into every overlay page).
 *
 * Applies the per-overlay appearance settings saved from the launcher:
 * whole-widget opacity, background opacity, zoom, accent colour, header and
 * footer visibility and overlay-specific parts ("hidden"). Sources, lowest to
 * highest precedence:
 *   1. defaults
 *   2. GET /overlay_settings/<name> (polled, so changes reach an open window
 *      or OBS source within ~2 s without reloading)
 *   3. URL overrides for OBS scenes:
 *      ?opacity=80&bg=60&scale=120&accent=ff6600&header=0&footer=0&hide=wheel,clutch
 *   4. launcher live preview: postMessage({type:'rah-settings', settings}) from
 *      the same origin while embedded (?embed=1)
 * Everything lands as CSS variables / classes on <html>; no markup is built.
 */
(function (global) {
    'use strict';
    var doc = global.document;
    if (!doc || !doc.documentElement) return;
    var root = doc.documentElement;
    var match = /\/overlay\/([a-z0-9_]+)/.exec(global.location.pathname);
    var name = match ? match[1] : null;
    var params = new URLSearchParams(global.location.search);
    var embedded = params.get('embed') === '1';
    var DEFAULTS = {theme: '', opacity: 100, bg_opacity: 100, scale: 100, accent: '#e2483d',
        show_header: true, show_footer: true, hidden: []};
    var last = '';
    var hiddenApplied = [];

    if (embedded) root.classList.add('rah-embed');
    // "Open full demo" from the launcher: present the widget centred on a
    // dark stage instead of pinned to the corner of a white browser page.
    if (params.get('stage') === '1') root.classList.add('rah-stage');

    function clamp(value, low, high, fallback) {
        var n = Number(value);
        return isFinite(n) ? Math.max(low, Math.min(high, Math.round(n))) : fallback;
    }

    function hex(value, fallback) {
        if (typeof value !== 'string') return fallback;
        var v = value.charAt(0) === '#' ? value : '#' + value;
        return /^#[0-9a-fA-F]{6}$/.test(v) ? v.toLowerCase() : fallback;
    }

    function keys(list) {
        return (Array.isArray(list) ? list : []).filter(function (k) {
            return typeof k === 'string' && /^[a-z0-9_]{1,32}$/.test(k);
        });
    }

    function normalise(raw) {
        raw = raw && typeof raw === 'object' ? raw : {};
        return {
            theme: raw.theme === 'original' || raw.theme === 'glass' ? raw.theme : '',
            opacity: clamp(raw.opacity, 20, 100, DEFAULTS.opacity),
            bg_opacity: clamp(raw.bg_opacity, 0, 100, DEFAULTS.bg_opacity),
            scale: clamp(raw.scale, 50, 200, DEFAULTS.scale),
            accent: hex(raw.accent, DEFAULTS.accent),
            show_header: raw.show_header !== false,
            show_footer: raw.show_footer !== false,
            hidden: keys(raw.hidden)
        };
    }

    function urlOverrides(settings) {
        var s = Object.assign({}, settings);
        if (params.has('opacity')) s.opacity = clamp(params.get('opacity'), 20, 100, s.opacity);
        if (params.has('bg')) s.bg_opacity = clamp(params.get('bg'), 0, 100, s.bg_opacity);
        if (params.has('scale')) s.scale = clamp(params.get('scale'), 50, 200, s.scale);
        if (params.has('accent')) s.accent = hex(params.get('accent'), s.accent);
        if (params.has('header')) s.show_header = params.get('header') !== '0';
        if (params.has('footer')) s.show_footer = params.get('footer') !== '0';
        if (params.has('hide')) s.hidden = keys((params.get('hide') || '').split(','));
        return s;
    }

    function apply(settings, fromPreview) {
        var s = normalise(settings);
        if (!fromPreview) s = urlOverrides(s);
        var signature = JSON.stringify(s);
        if (signature === last) return;
        last = signature;
        root.style.setProperty('--rah-opacity', String(s.opacity / 100));
        root.style.setProperty('--rah-bg-alpha', String(s.bg_opacity / 100));
        root.style.setProperty('--rah-zoom', String(s.scale / 100));
        root.style.setProperty('--rah-accent', s.accent);
        root.classList.toggle('rah-hide-header', !s.show_header);
        root.classList.toggle('rah-hide-footer', !s.show_footer);
        hiddenApplied.forEach(function (k) { root.classList.remove('rah-no-' + k); });
        s.hidden.forEach(function (k) { root.classList.add('rah-no-' + k); });
        hiddenApplied = s.hidden;
        var theme = global.RAHOverlayTheme;
        if (theme && s.theme && (fromPreview || !params.get('theme'))) {
            theme.apply(s.theme, root);
        }
        try {
            global.dispatchEvent(new global.CustomEvent('rah-settings', {detail: s}));
        } catch (error) { /* old engines: visual settings already applied */ }
    }

    function load() {
        if (!name || typeof global.fetch !== 'function') return;
        global.fetch('/overlay_settings/' + name, {cache: 'no-store'})
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (data) {
                if (!data) return;
                // Keep the widget at its native width in wide browser/OBS views.
                if (data.resolution && Number(data.resolution.width) > 0) {
                    root.style.setProperty('--rah-native-w', Number(data.resolution.width) + 'px');
                }
                apply(data, false);
            })
            .catch(function () { /* settings are cosmetic; keep defaults */ });
    }

    apply(DEFAULTS, false);
    if (embedded) {
        // The launcher drives the preview; it sends the settings being edited.
        global.addEventListener('message', function (event) {
            var data = event.data;
            if (event.origin !== global.location.origin || !data || data.type !== 'rah-settings') return;
            apply(data.settings, true);
        });
    } else {
        load();
        global.setInterval(load, 2000);
    }

    // Live windows / OBS sources: never show scrollbars. If the widget is
    // larger than its window (DPI scaling, fonts, long names...), shrink it to
    // fit instead of letting the window scroll or clip it.
    var live = !params.has('demo') && !embedded;
    var fitting = false;
    function fitToWindow() {
        if (!live || fitting || !doc.body) return;
        fitting = true;
        var fit = 1;
        root.style.setProperty('--rah-fit', '1');
        var card = doc.querySelector('.rah-race');
        for (var i = 0; i < 4; i++) {
            var rect = card ? card.getBoundingClientRect() : null;
            var w = Math.max(root.scrollWidth, rect ? Math.ceil(rect.right) : 0);
            var h = Math.max(root.scrollHeight, rect ? Math.ceil(rect.bottom) : 0);
            var vw = global.innerWidth, vh = global.innerHeight;
            if (!vw || !vh || (w <= vw + 1 && h <= vh + 1)) break;
            fit = Math.max(.4, fit * Math.min(vw / w, vh / h) * .995);
            root.style.setProperty('--rah-fit', String(fit));
        }
        fitting = false;
    }
    if (live) {
        root.classList.add('rah-live');
        global.addEventListener('resize', fitToWindow);
        global.addEventListener('rah-settings', function () { global.setTimeout(fitToWindow, 0); });
        doc.addEventListener('DOMContentLoaded', function () {
            fitToWindow();
            var card = doc.querySelector('.rah-race');
            if (card && typeof global.ResizeObserver === 'function') {
                new global.ResizeObserver(function () { global.requestAnimationFrame(fitToWindow); }).observe(card);
            }
            if (doc.fonts && doc.fonts.ready) doc.fonts.ready.then(fitToWindow);
        });
    }

    global.RAHOverlaySettings = {normalise: normalise, apply: apply, name: name, fit: fitToWindow};
}(typeof window !== 'undefined' ? window : globalThis));
