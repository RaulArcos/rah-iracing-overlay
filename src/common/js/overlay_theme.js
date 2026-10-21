/*
 * RAH overlay theme runtime (shared by every overlay page and the launcher).
 *
 * Resolution order:
 *   1. ?theme=original|glass on the page URL (browser/OBS override, wins)
 *   2. the stored preference read defensively from localStorage
 *   3. 'original' (the existing RAH look, untouched)
 *
 * An explicit but invalid URL theme is rejected to 'original'; an empty URL
 * value counts as absent. Any storage access error (denied, missing, quota)
 * falls back to the default instead of crashing. The resolved theme is set as
 * <html data-rah-theme="...">, which the shared stylesheet
 * (/common/css/overlay-theme.css) consumes. This script never renders
 * untrusted content into the DOM; it only manages one attribute and one
 * storage key.
 */
(function (global) {
    'use strict';

    var THEMES = ['original', 'glass'];
    var DEFAULT_THEME = 'original';
    var STORAGE_KEY = 'rah_overlay_theme';

    function isTheme(value) {
        return typeof value === 'string' && THEMES.indexOf(value) !== -1;
    }

    function resolve(urlValue, storedValue) {
        if (urlValue !== undefined && urlValue !== null && String(urlValue).length > 0) {
            return isTheme(urlValue) ? urlValue : DEFAULT_THEME;
        }
        return isTheme(storedValue) ? storedValue : DEFAULT_THEME;
    }

    function readUrlTheme(location) {
        if (!location || typeof location.search !== 'string') {
            return null;
        }
        try {
            var match = /[?&]theme=([^&#]*)/.exec(location.search);
            if (!match) {
                return null;
            }
            return decodeURIComponent(match[1].replace(/\+/g, ' '));
        } catch (error) {
            return null;
        }
    }

    function defaultStorage(scope) {
        // Embedded web views and OBS browser sources can expose localStorage
        // while denying every call; probe once and treat it as unavailable.
        try {
            var storage = scope.localStorage;
            storage.getItem(STORAGE_KEY);
            return storage;
        } catch (error) {
            return null;
        }
    }

    function getStored(storage) {
        if (!storage) {
            return null;
        }
        try {
            return isTheme(storage.getItem(STORAGE_KEY)) ? storage.getItem(STORAGE_KEY) : null;
        } catch (error) {
            return null;
        }
    }

    function setStored(theme, storage) {
        if (!isTheme(theme) || !storage) {
            return false;
        }
        try {
            storage.setItem(STORAGE_KEY, theme);
        } catch (error) {
            return false;
        }
        return true;
    }

    function apply(theme, root) {
        var resolved = isTheme(theme) ? theme : DEFAULT_THEME;
        if (root && typeof root.setAttribute === 'function') {
            root.setAttribute('data-rah-theme', resolved);
        }
        return resolved;
    }

    function current(doc) {
        var root = doc ? doc.documentElement : (global.document || {}).documentElement;
        if (!root || typeof root.getAttribute !== 'function') {
            return DEFAULT_THEME;
        }
        var value = root.getAttribute('data-rah-theme');
        return isTheme(value) ? value : DEFAULT_THEME;
    }

    function init(options) {
        options = options || {};
        var doc = options.document || global.document;
        var location = options.location || global.location;
        var storage = ('storage' in options) ? options.storage : defaultStorage(global);
        var resolved = resolve(readUrlTheme(location), getStored(storage));
        apply(resolved, doc ? doc.documentElement : null);
        return resolved;
    }

    var api = {
        themes: THEMES.slice(),
        defaultTheme: DEFAULT_THEME,
        storageKey: STORAGE_KEY,
        resolve: resolve,
        readUrlTheme: readUrlTheme,
        getStored: getStored,
        setStored: setStored,
        apply: apply,
        current: current,
        init: init,
    };

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = api;
    }
    global.RAHOverlayTheme = api;

    // Auto-apply while still in <head> so the first paint already uses the
    // resolved theme; documentElement exists before the body is parsed.
    if (global.document && global.document.documentElement) {
        init();
    }
}(typeof window !== 'undefined' ? window : globalThis));
