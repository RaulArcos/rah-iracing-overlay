/* RAH launcher v2: overlay list, live preview, per-overlay settings, OBS URL. */
'use strict';

// Overlay-specific parts the user can switch off (CSS: html.rah-no-<key>).
const OVERLAY_PARTS = {
    input_telemetry: {graph: 'Trace graph', pedals: 'Pedal bars', clutch: 'Clutch', pedal_values: 'Pedal %',
        gear: 'Gear', speed: 'Speed', wheel: 'Steering wheel'},
    standings: {class_pos: 'Class pos', laps: 'Laps', license: 'Licence / SR', irating: 'iRating',
        gain: '±Positions', interval: 'Interval'},
    relative: {car_number: 'Car number', license: 'Licence / SR', irating: 'iRating', gain: '±Positions',
        meta: 'Track temp & SoF'},
    laptime_graph: {graph: 'Graph', table: 'Lap table'},
    battle_pace: {recent: 'Recent-lap comparison'},
    delta: {live_delta: 'Live delta', bar: 'Delta bar', sectors: 'Sectors', split: 'Sector pop-up'}
};
const ACCENTS = ['#ed2727', '#ff7a1a', '#f5cd5b', '#4fdc8a', '#2ec4d6', '#6ea8ff', '#a77bff', '#ff5fa2', '#e6e8ec'];
const DEFAULT_SETTINGS = {theme: '', opacity: 100, bg_opacity: 100, scale: 100, accent: '#ed2727',
    show_header: true, show_footer: true, hidden: []};
const LAST_KEY = 'rah_launcher_last_overlay';

const state = {
    overlays: [],
    selected: null,
    settings: {},
    resolution: {},
    open: new Set(),
    saveTimer: null,
    savedScale: {},
    savedTheme: {}
};

const $ = id => document.getElementById(id);

document.addEventListener('DOMContentLoaded', function() {
    initThemeSelector();
    bindDetail();

    fetch('/get_overlays')
        .then(response => response.json())
        .then(overlays => {
            state.overlays = overlays.slice().sort((a, b) =>
                (a.display_name || '').localeCompare(b.display_name || ''));
            renderList();
            $('overlayCount').textContent = String(state.overlays.length).padStart(2, '0');
            syncActiveOverlays();
            let last = null;
            try { last = window.localStorage.getItem(LAST_KEY); } catch (error) { last = null; }
            const first = state.overlays.find(o => o.folder_name === last) || state.overlays[0];
            if (first) selectOverlay(first.folder_name);
        })
        .catch(() => showToast('Could not load the overlay list', true));

    setInterval(syncActiveOverlays, 3000);
    window.addEventListener('resize', fitStage);
});

/* ---------- List ---------- */
function renderList() {
    const list = $('overlayList');
    const query = ($('overlaySearch').value || '').trim().toLowerCase();
    list.textContent = '';
    const shown = state.overlays.filter(o => !query ||
        (o.display_name + ' ' + o.description).toLowerCase().includes(query));
    shown.forEach((overlay, position) => {
        const folder = overlay.folder_name;
        const item = document.createElement('div');
        item.className = 'ov-item' + (state.selected === folder ? ' active' : '') +
            (state.open.has(folder) ? ' is-open' : '');
        item.setAttribute('role', 'listitem');
        item.dataset.folder = folder;
        item.style.setProperty('--i', position);

        const dot = document.createElement('span');
        dot.className = 'ov-item__num';
        dot.setAttribute('aria-hidden', 'true');
        dot.textContent = String(state.overlays.indexOf(overlay) + 1).padStart(2, '0');

        const select = document.createElement('button');
        select.type = 'button';
        select.className = 'ov-item__select';
        const name = document.createElement('span');
        name.className = 'ov-item__name';
        name.textContent = overlay.display_name || folder;
        const meta = document.createElement('span');
        meta.className = 'ov-item__meta';
        meta.textContent = state.open.has(folder) ? 'Running' : shortDescription(overlay.description);
        select.append(name, meta);
        select.addEventListener('click', () => selectOverlay(folder));

        const toggle = document.createElement('label');
        toggle.className = 'switch';
        toggle.title = state.open.has(folder) ? 'Close overlay' : 'Launch overlay';
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.checked = state.open.has(folder);
        input.setAttribute('aria-label', 'Run ' + (overlay.display_name || folder));
        input.addEventListener('change', () => toggleOverlay(folder));
        const track = document.createElement('span');
        track.className = 'switch__track';
        toggle.append(input, track);

        item.append(dot, select, toggle);
        item.addEventListener('click', e => {
            if (!e.target.closest('label, button')) selectOverlay(folder);
        });
        list.appendChild(item);
    });
    if (!shown.length) {
        const empty = document.createElement('div');
        empty.className = 'empty-list';
        empty.textContent = 'No overlays match your search';
        list.appendChild(empty);
    }
}

function shortDescription(text) {
    const value = (text || '').split(/[.(]/)[0].trim();
    return value || 'Overlay';
}

function overlayByFolder(folder) {
    return state.overlays.find(o => o.folder_name === folder) || null;
}

/* ---------- Selection & preview ---------- */
function selectOverlay(folder) {
    const overlay = overlayByFolder(folder);
    if (!overlay) return;
    state.selected = folder;
    try { window.localStorage.setItem(LAST_KEY, folder); } catch (error) { /* optional */ }
    document.querySelectorAll('.ov-item').forEach(el => el.classList.toggle('active', el.dataset.folder === folder));
    document.querySelector('.preview-placeholder').hidden = true;
    const content = document.querySelector('.preview-content');
    content.hidden = false;
    const index = state.overlays.indexOf(overlay) + 1;
    $('detailKicker').textContent = `Overlay ${String(index).padStart(2, '0')} / ${String(state.overlays.length).padStart(2, '0')}`;
    $('previewTitle').textContent = overlay.display_name;
    $('previewDescription').textContent = overlay.description;
    updateActionButtons();

    loadSettings(folder).then(() => {
        if (state.selected !== folder) return;
        fillControls();
        loadPreview();
    });
}

function loadSettings(folder) {
    if (state.settings[folder]) return Promise.resolve(state.settings[folder]);
    return fetch('/overlay_settings/' + encodeURIComponent(folder), {cache: 'no-store'})
        .then(r => r.ok ? r.json() : {})
        .catch(() => ({}))
        .then(data => {
            state.resolution[folder] = data.resolution || {width: 600, height: 300};
            delete data.resolution;
            state.settings[folder] = Object.assign({}, DEFAULT_SETTINGS, data);
            state.savedScale[folder] = state.settings[folder].scale;
            state.savedTheme[folder] = state.settings[folder].theme;
            return state.settings[folder];
        });
}

function current() {
    return state.settings[state.selected] || Object.assign({}, DEFAULT_SETTINGS);
}

function effectiveTheme(folder) {
    const settings = state.settings[folder];
    return settings && settings.theme ? settings.theme : getSelectedTheme();
}

function loadPreview() {
    const overlay = overlayByFolder(state.selected);
    if (!overlay) return;
    const theme = effectiveTheme(state.selected);
    const frame = $('previewFrame');
    const holder = $('stageFrame');
    holder.classList.add('is-loading');
    frame.onload = () => { pushPreview(); fitStage(); setTimeout(() => holder.classList.remove('is-loading'), 120); };
    frame.src = window.RAHMenuPreviews.embedUrl(overlay, theme);
    $('previewDemo').href = window.RAHMenuPreviews.demoUrl(overlay, theme) + '&stage=1';
    fitStage();
    updateObs();
}

function pushPreview() {
    const frame = $('previewFrame');
    if (!frame.contentWindow) return;
    const settings = Object.assign({}, current(), {theme: effectiveTheme(state.selected)});
    frame.contentWindow.postMessage({type: 'rah-settings', settings}, window.location.origin);
}

function fitStage() {
    const folder = state.selected;
    const res = state.resolution[folder];
    if (!res) return;
    const scale = current().scale / 100;
    const width = Math.round(res.width * scale);
    const height = Math.round(res.height * scale);
    const frame = $('previewFrame');
    frame.width = width;
    frame.height = height;
    // The stage keeps one fixed size for every overlay; only the overlay
    // inside is scaled down (never up) to fit with a constant margin.
    const canvas = $('stageCanvas');
    const fit = Math.min(1, Math.max(100, canvas.clientWidth - 64) / width,
        Math.max(100, canvas.clientHeight - 64) / height);
    $('stageFrame').style.transform = `translate(-50%, -50%) scale(${fit})`;
    $('stageFrame').style.transformOrigin = '50% 50%';
    $('stageSize').textContent = `${width} × ${height} px` + (fit < 1 ? ` · shown at ${Math.round(fit * 100)}%` : '');
}

/* ---------- Settings controls ---------- */
function bindDetail() {
    $('overlaySearch').addEventListener('input', renderList);
    $('actionToggle').addEventListener('click', () => state.selected && toggleOverlay(state.selected));
    $('actionPosition').addEventListener('click', () => {
        const overlay = overlayByFolder(state.selected);
        if (overlay) launchOverlay(overlay.display_name, overlay.folder_name, false);
    });
    $('actionBrowser').addEventListener('click', () => {
        const overlay = overlayByFolder(state.selected);
        if (overlay) openOverlayUrl(overlay.url, effectiveTheme(overlay.folder_name));
    });

    [['setOpacity', 'opacity'], ['setBg', 'bg_opacity'], ['setScale', 'scale']].forEach(([id, key]) => {
        $(id).addEventListener('input', e => change({[key]: Number(e.target.value)}));
    });
    $('setHeader').addEventListener('change', e => change({show_header: e.target.checked}));
    $('setFooter').addEventListener('change', e => change({show_footer: e.target.checked}));
    $('setAccent').addEventListener('input', e => change({accent: e.target.value}));

    document.querySelectorAll('#themeSegment button').forEach(button => {
        button.addEventListener('click', () => change({theme: button.dataset.value}));
    });

    const thumb = document.createElement('span');
    thumb.className = 'segmented__thumb';
    thumb.setAttribute('aria-hidden', 'true');
    $('themeSegment').prepend(thumb);

    const swatches = $('accentSwatches');
    ACCENTS.forEach(color => {
        const swatch = document.createElement('button');
        swatch.type = 'button';
        swatch.className = 'swatch';
        swatch.style.setProperty('--c', color);
        swatch.dataset.color = color;
        swatch.setAttribute('aria-label', 'Accent ' + color);
        swatch.addEventListener('click', () => change({accent: color}));
        swatches.insertBefore(swatch, $('setAccent'));
    });

    $('resetSettings').addEventListener('click', () => change(Object.assign({}, DEFAULT_SETTINGS, {hidden: []})));
    $('copyObs').addEventListener('click', copyObsUrl);
    $('obsUrl').addEventListener('focus', e => e.target.select());
}

function fillControls() {
    const s = current();
    setRange('setOpacity', 'outOpacity', s.opacity);
    setRange('setBg', 'outBg', s.bg_opacity);
    setRange('setScale', 'outScale', s.scale);
    $('setHeader').checked = s.show_header;
    $('setFooter').checked = s.show_footer;
    $('setAccent').value = s.accent;
    const segments = Array.from(document.querySelectorAll('#themeSegment button'));
    segments.forEach(b => b.setAttribute('aria-checked', String(b.dataset.value === s.theme)));
    $('themeSegment').style.setProperty('--pos', Math.max(0, segments.findIndex(b => b.dataset.value === s.theme)));
    document.querySelectorAll('.swatch').forEach(b =>
        b.setAttribute('aria-pressed', String(b.dataset.color === s.accent)));

    const parts = OVERLAY_PARTS[state.selected] || {};
    const list = $('partsList');
    list.textContent = '';
    Object.entries(parts).forEach(([key, label]) => {
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'chip';
        chip.textContent = label;
        chip.setAttribute('aria-pressed', String(!s.hidden.includes(key)));
        chip.addEventListener('click', () => {
            const hidden = new Set(current().hidden);
            if (hidden.has(key)) hidden.delete(key); else hidden.add(key);
            change({hidden: Array.from(hidden)});
        });
        list.appendChild(chip);
    });
    $('partsField').hidden = !Object.keys(parts).length;
}

function setRange(inputId, outputId, value) {
    const input = $(inputId);
    input.value = value;
    const min = Number(input.min), max = Number(input.max);
    input.style.setProperty('--fill', ((value - min) / (max - min) * 100) + '%');
    $(outputId).textContent = value + '%';
}

function change(patch) {
    const folder = state.selected;
    if (!folder) return;
    const before = current();
    state.settings[folder] = Object.assign({}, before, patch);
    fillControls();
    pushPreview();
    if ('scale' in patch) fitStage();
    updateObs();
    scheduleSave(folder);
}

function scheduleSave(folder) {
    clearTimeout(state.saveTimer);
    setSaveState('Saving…');
    state.saveTimer = setTimeout(() => saveSettings(folder), 400);
}

function saveSettings(folder) {
    const settings = state.settings[folder];
    const bar = $('saveProgress');
    bar.classList.remove('is-running');
    void bar.offsetWidth;
    bar.classList.add('is-running');
    fetch('/overlay_settings/' + encodeURIComponent(folder), {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(settings)
    })
        .then(r => r.json())
        .then(data => {
            if (data.status !== 'success') throw new Error('save failed');
            setSaveState('Saved', 'is-saved');
            // Window size and pinned theme are fixed at launch: relaunch an
            // open overlay so the new size/theme apply without user action.
            const needsRelaunch = settings.scale !== state.savedScale[folder] ||
                settings.theme !== state.savedTheme[folder];
            state.savedScale[folder] = settings.scale;
            state.savedTheme[folder] = settings.theme;
            if (needsRelaunch && state.open.has(folder)) {
                const overlay = overlayByFolder(folder);
                launchOverlay(overlay.display_name, folder, true, true);
            }
        })
        .catch(() => setSaveState('Not saved', 'is-error'));
}

function setSaveState(text, cls) {
    const el = $('saveState');
    el.textContent = text;
    el.className = 'save-state' + (cls ? ' ' + cls : '');
}

/* ---------- OBS ---------- */
function obsUrl() {
    const overlay = overlayByFolder(state.selected);
    return overlay ? `${overlay.url}?theme=${effectiveTheme(overlay.folder_name)}` : '';
}

function updateObs() {
    $('obsUrl').value = obsUrl();
    const res = state.resolution[state.selected];
    if (res) {
        const scale = current().scale / 100;
        $('obsHint').textContent = `Browser source: width ${Math.round(res.width * scale)}, height ${Math.round(res.height * scale)}. ` +
            'Appearance follows these settings automatically.';
    }
}

function copyObsUrl() {
    const url = obsUrl();
    const done = () => showToast('OBS URL copied');
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(done, () => { $('obsUrl').select(); document.execCommand('copy'); done(); });
    } else {
        $('obsUrl').select();
        document.execCommand('copy');
        done();
    }
}

/* ---------- Running state ---------- */
function syncActiveOverlays() {
    fetch('/get_active_overlays')
        .then(response => response.json())
        .then(data => {
            if (data.status !== 'success') return;
            const next = new Set(Object.keys(data.active_overlays || {}));
            const changed = next.size !== state.open.size || [...next].some(f => !state.open.has(f));
            state.open = next;
            if (changed) refreshRunningUi();
        })
        .catch(() => { /* launcher keeps the last known state */ });
}

function refreshRunningUi() {
    renderList();
    updateActionButtons();
    const count = state.open.size;
    const label = $('activeCount');
    label.querySelector('.live-pill__text').textContent = count ? `Live · ${count}` : 'Idle';
    label.title = count ? `${count} overlay${count === 1 ? '' : 's'} running` : 'No overlays running';
    label.classList.toggle('is-live', count > 0);
}

function updateActionButtons() {
    const button = $('actionToggle');
    const open = state.selected && state.open.has(state.selected);
    button.classList.toggle('is-open', !!open);
    button.querySelector('use').setAttribute('href', open ? '#i-stop' : '#i-play');
    button.querySelector('span').textContent = open ? 'Close' : 'Launch';
}

function toggleOverlay(folder) {
    const overlay = overlayByFolder(folder);
    if (!overlay) return;
    if (state.open.has(folder)) closeOverlay(overlay.display_name, folder);
    else launchOverlay(overlay.display_name, folder, true);
}

/* ---------- Theme ---------- */
function initThemeSelector() {
    const themeSelect = document.getElementById('themeSelect');
    if (!themeSelect || !window.RAHOverlayTheme) {
        return;
    }

    const stored = window.RAHOverlayTheme.getStored(window.localStorage);
    themeSelect.value = stored || window.RAHOverlayTheme.defaultTheme;

    themeSelect.addEventListener('change', function() {
        if (window.RAHOverlayTheme.setStored(themeSelect.value, window.localStorage)) {
            showToast(`Default theme: ${themeSelect.options[themeSelect.selectedIndex].text}`);
        } else {
            showToast('Could not save theme preference; it applies to this session only', true);
        }
        if (state.selected) loadPreview();
        // Relaunch running overlays that follow the default theme.
        state.open.forEach(folder => {
            const settings = state.settings[folder];
            if (!settings || !settings.theme) {
                const overlay = overlayByFolder(folder);
                if (overlay) launchOverlay(overlay.display_name, folder, true, true);
            }
        });
    });
}

function getSelectedTheme() {
    const themeSelect = document.getElementById('themeSelect');
    if (window.RAHOverlayTheme && themeSelect && themeSelect.value) {
        return window.RAHOverlayTheme.apply(themeSelect.value, document.documentElement);
    }
    return window.RAHOverlayTheme ? window.RAHOverlayTheme.defaultTheme : 'original';
}

/* ---------- Backend actions ---------- */
function openOverlayUrl(url, theme) {
    window.open(`${url}?theme=${theme || getSelectedTheme()}`, '_blank');
}

function launchOverlay(displayName, folderName, isTransparent = true, quiet = false) {
    const theme = effectiveTheme(folderName);
    fetch('/launch', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            overlay: displayName,
            transparent: isTransparent,
            theme: theme
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            state.open.add(folderName);
            refreshRunningUi();
            if (!isTransparent) {
                showToast('Drag the window into place, then press Save Position inside it', false, 6000);
            } else if (!quiet) {
                showToast(`${displayName} launched`);
            }
        } else {
            showToast(data.message || 'Could not launch overlay', true);
            refreshRunningUi();
        }
    })
    .catch(error => {
        console.error('Error launching overlay:', error);
        showToast('Network error launching overlay', true);
        refreshRunningUi();
    });
}

function closeOverlay(displayName, folderName) {
    fetch('/close_overlay', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            overlay: displayName,
            folder_name: folderName
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            state.open.delete(folderName);
            showToast(`${displayName} closed`);
        } else {
            showToast('Error closing overlay', true);
        }
        refreshRunningUi();
    })
    .catch(error => {
        console.error('Error closing overlay:', error);
        showToast('Network error closing overlay', true);
        refreshRunningUi();
    });
}

let toastTimer = null;
function showToast(message, isError = false, duration = 3000) {
    const toast = $('toast');
    toast.textContent = message;
    toast.className = 'toast show' + (isError ? ' error' : '');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toast.className = 'toast' + (isError ? ' error' : ''); }, duration);
}
