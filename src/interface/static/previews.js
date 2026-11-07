/* Launcher preview URLs; the live iframe and actions live in main.js. */
(function (global) {
    'use strict';
    const imageUrl = (overlay, theme) => (overlay.preview_images || {})[theme] || overlay.preview_gif || null;
    const demoUrl = (overlay, theme) => '/overlay/' + encodeURIComponent(overlay.folder_name) +
        '?demo=1&theme=' + (theme === 'glass' ? 'glass' : 'original');
    // Embedded variant: hides the demo toolbar and listens for live settings.
    const embedUrl = (overlay, theme) => demoUrl(overlay, theme) + '&embed=1';
    global.RAHMenuPreviews = {imageUrl, demoUrl, embedUrl};
}(window));
