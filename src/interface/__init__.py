from flask import Blueprint, render_template, send_from_directory, jsonify, request
import os
import multiprocessing
from overlay_window import OverlayWindow
import json
import logging
import sys
import time

interface_bp = Blueprint(
    'interface', __name__,
    template_folder='.',
    static_folder=None
)

opened_overlays = {}
overlay_windows = {}

# Supported overlay themes. Small explicit whitelist: the only values ever
# appended to a desktop launch URL. The preference itself is persisted by the
# launcher (localStorage) and pinned per overlay here, in memory only.
OVERLAY_THEMES = ('original', 'glass')

# folder_name -> last validated theme chosen at /launch (None = no pin).
overlay_theme_preferences = {}

logging.basicConfig(level=logging.DEBUG)

@interface_bp.route('/')
def index():
    return render_template('index.html')

@interface_bp.route('/static/<filename>')
def serve_static(filename):
    return send_from_directory(os.path.join(interface_bp.root_path, 'static'), filename)

@interface_bp.route('/images/<filename>')
def serve_images(filename):
    return send_from_directory(os.path.join(interface_bp.root_path, 'static', 'images'), filename)

@interface_bp.route('/common/css/<path:filename>')
def serve_common_css(filename):
    common_css_folder = os.path.join(os.path.dirname(__file__), '..', 'common', 'css')
    return send_from_directory(common_css_folder, filename)

@interface_bp.route('/common/fonts/<path:filename>')
def serve_common_fonts(filename):
    fonts_folder = os.path.join(os.path.dirname(__file__), '..', 'common', 'fonts')
    response = send_from_directory(fonts_folder, filename)
    response.headers['Cache-Control'] = 'public, max-age=604800'
    return response

@interface_bp.route('/get_overlays')
def get_overlays():
    overlays_dir = os.path.join(os.path.dirname(__file__), '..', 'overlays')
    overlays = []
    for name in os.listdir(overlays_dir):
        overlay_path = os.path.join(overlays_dir, name)
        properties_path = os.path.join(overlay_path, 'properties.json')
        if os.path.isdir(overlay_path) and os.path.exists(properties_path):
            with open(properties_path, 'r') as properties_file:
                properties = json.load(properties_file)
                display_name = properties.get('display_name', name)
                description = properties.get('description', 'No description available.')
                position = properties.get('position', None)
                dpi_info = properties.get('dpi_info', {'scale': 1.0})
                
                preview_gif = properties.get('preview_gif', None)
                if not preview_gif:
                    images_folder = os.path.join(overlay_path, 'static', 'images')
                    if os.path.exists(images_folder):
                        preview_file = os.path.join(images_folder, 'preview.gif')
                        if os.path.exists(preview_file):
                            preview_gif = f"/overlay/{name}/static/images/preview.gif"
                    
                    if not preview_gif:
                        static_folder = os.path.join(overlay_path, 'static')
                        if os.path.exists(static_folder):
                            preview_file = os.path.join(static_folder, 'preview.gif')
                            if os.path.exists(preview_file):
                                preview_gif = f"/overlay/{name}/static/preview.gif"
                
                overlays.append({
                    'display_name': display_name,
                    'folder_name': name,
                    'description': description,
                    'url': f"http://127.0.0.1:8085/overlay/{name}",
                    'position': position,
                    'dpi_info': dpi_info,
                    'preview_images': {
                        theme: f'/overlay/{name}/static/images/preview-{theme}.png'
                        for theme in OVERLAY_THEMES
                        if os.path.isfile(os.path.join(overlay_path, 'static', 'images',
                                                       f'preview-{theme}.png'))
                    },
                    'preview_gif': preview_gif
                })
    return jsonify(overlays)

# --------------------------------------------------------------------------
# Per-overlay appearance settings
#
# Stored under the "settings" key of each overlay's properties.json, served to
# the overlay page (desktop window and OBS browser source alike) by
# /overlay_settings/<name>. Every value is validated and clamped here, so the
# overlay runtime only ever receives a known, bounded shape.
# --------------------------------------------------------------------------
SETTINGS_DEFAULTS = {
    'theme': '',          # '' follows the launcher's global theme
    'opacity': 100,       # whole widget opacity, %
    'bg_opacity': 100,    # panel background opacity, % of the theme's own alpha
    'scale': 100,         # widget zoom, %
    'accent': '#e2483d',  # header strip / highlight colour
    'show_header': True,
    'show_footer': True,
    'hidden': [],         # overlay-specific parts switched off by the user
}
SETTINGS_LIMITS = {'opacity': (20, 100), 'bg_opacity': (0, 100), 'scale': (50, 200)}
_OPTION_KEY_CHARS = set('abcdefghijklmnopqrstuvwxyz0123456789_')


def _overlay_properties_path(folder_name):
    if not isinstance(folder_name, str) or not folder_name or \
            not set(folder_name) <= _OPTION_KEY_CHARS:
        return None
    path = os.path.join(os.path.dirname(__file__), '..', 'overlays', folder_name, 'properties.json')
    return path if os.path.exists(path) else None


def sanitize_settings(raw):
    """Return a complete, validated settings dict from untrusted input."""
    raw = raw if isinstance(raw, dict) else {}
    clean = dict(SETTINGS_DEFAULTS)
    clean['hidden'] = []
    theme = raw.get('theme')
    if theme in OVERLAY_THEMES:
        clean['theme'] = theme
    for key, (low, high) in SETTINGS_LIMITS.items():
        value = raw.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value == value:
            clean[key] = int(max(low, min(high, round(value))))
    accent = raw.get('accent')
    if isinstance(accent, str) and len(accent) == 7 and accent[0] == '#' and \
            all(c in '0123456789abcdefABCDEF' for c in accent[1:]):
        clean['accent'] = accent.lower()
    for key in ('show_header', 'show_footer'):
        if isinstance(raw.get(key), bool):
            clean[key] = raw[key]
    hidden = raw.get('hidden')
    if isinstance(hidden, list):
        clean['hidden'] = sorted({h for h in hidden if isinstance(h, str) and 0 < len(h) <= 32
                                  and set(h) <= _OPTION_KEY_CHARS})[:24]
    return clean


def read_overlay_settings(folder_name):
    path = _overlay_properties_path(folder_name)
    if not path:
        return None
    try:
        with open(path, 'r') as handle:
            return sanitize_settings(json.load(handle).get('settings'))
    except (OSError, ValueError, AttributeError):
        return sanitize_settings(None)


def scaled_resolution(resolution, folder_name):
    """Grow the native window with the user's zoom so nothing is clipped."""
    settings = read_overlay_settings(folder_name) or SETTINGS_DEFAULTS
    factor = settings.get('scale', 100) / 100.0
    if factor == 1:
        return resolution
    return {'width': int(round(resolution['width'] * factor)),
            'height': int(round(resolution['height'] * factor))}


@interface_bp.route('/overlay_settings/<folder_name>', methods=['GET'])
def get_overlay_settings(folder_name):
    settings = read_overlay_settings(folder_name)
    if settings is None:
        return jsonify({'status': 'error', 'message': 'Overlay not found.'}), 404
    payload = dict(settings)
    # Read-only native size so the launcher can frame its live preview.
    try:
        with open(_overlay_properties_path(folder_name), 'r') as handle:
            resolution = json.load(handle).get('resolution') or {}
        payload['resolution'] = {'width': int(resolution.get('width', 800)),
                                 'height': int(resolution.get('height', 600))}
    except (OSError, ValueError, TypeError, AttributeError):
        payload['resolution'] = {'width': 800, 'height': 600}
    response = jsonify(payload)
    response.headers['Cache-Control'] = 'no-store'
    return response


@interface_bp.route('/overlay_settings/<folder_name>', methods=['POST'])
def save_overlay_settings(folder_name):
    path = _overlay_properties_path(folder_name)
    if not path:
        return jsonify({'status': 'error', 'message': 'Overlay not found.'}), 404
    settings = sanitize_settings(request.get_json(silent=True))
    with open(path, 'r') as handle:
        properties = json.load(handle)
    properties['settings'] = settings
    with open(path, 'w') as handle:
        json.dump(properties, handle, indent=4)
    return jsonify({'status': 'success', 'settings': settings}), 200


def validated_theme(value):
    """Return the theme only when it is whitelisted, else None."""
    return value if value in OVERLAY_THEMES else None


def overlay_launch_url(folder_name, theme):
    """Build the overlay window URL, pinning a whitelisted ?theme= when given.

    A missing or non-whitelisted theme keeps the plain URL, so legacy
    launcher requests behave exactly as before this theme system existed.
    """
    theme = validated_theme(theme)
    url = f"http://127.0.0.1:8085/overlay/{folder_name}"
    if theme:
        url = f"{url}?theme={theme}"
    return url


@interface_bp.route('/launch', methods=['POST'])
def launch_overlay():
    data = request.get_json()
    overlay_name = data.get('overlay')
    is_transparent = data.get('transparent', True) 
    theme = validated_theme(data.get('theme'))
    
    folder_name = next((overlay['folder_name'] for overlay in get_overlays().json if overlay['display_name'] == overlay_name), None)
    
    if folder_name:
        logging.debug(f"Attempting to launch overlay: {folder_name}")
        
        if folder_name in opened_overlays and opened_overlays[folder_name] is not None and opened_overlays[folder_name].is_alive():
            logging.debug(f"Closing existing overlay: {folder_name}")
            opened_overlays[folder_name].terminate()
            opened_overlays[folder_name].join(timeout=1)
            del opened_overlays[folder_name]
            time.sleep(0.5)
        
        overlay_theme_preferences[folder_name] = theme
        overlay_url = overlay_launch_url(folder_name, theme)
        properties_path = os.path.join(os.path.dirname(__file__), '..', 'overlays', folder_name, 'properties.json')
        
        logging.debug(f"Properties path: {properties_path}")
        
        if os.path.exists(properties_path):
            with open(properties_path, 'r') as properties_file:
                properties = json.load(properties_file)
                resolution = properties.get('resolution', {'width': 800, 'height': 600})
                position = properties.get('position', None)
                logging.debug(f"Overlay properties: {properties}")
        else:
            logging.error(f"Overlay properties file not found for {folder_name}")
            return jsonify({'status': 'error', 'message': f'Overlay {folder_name} not found.'}), 404
        
        exit_flag = multiprocessing.Value('i', 0)
        
        process = multiprocessing.Process(
            target=launch_overlay_window, 
            args=(overlay_url, scaled_resolution(resolution, folder_name), exit_flag, is_transparent, position, folder_name)
        )
        process.daemon = True  
        process.start()
        
        opened_overlays[folder_name] = process
        
        return jsonify({
            'status': 'success', 
            'message': f'Overlay {folder_name} launched.',
            'transparent': is_transparent
        }), 200
    return jsonify({'status': 'error', 'message': 'Overlay name not provided.'}), 400

@interface_bp.route('/toggle_transparency', methods=['POST'])
def toggle_transparency():
    data = request.get_json()
    overlay_name = data.get('overlay')
    
    folder_name = next((overlay['folder_name'] for overlay in get_overlays().json if overlay['display_name'] == overlay_name), None)
    
    if folder_name:
        properties_path = os.path.join(os.path.dirname(__file__), '..', 'overlays', folder_name, 'properties.json')
        position = None
        
        if os.path.exists(properties_path):
            with open(properties_path, 'r') as properties_file:
                properties = json.load(properties_file)
                position = properties.get('position', None)
        
        if folder_name in opened_overlays and opened_overlays[folder_name] is not None and opened_overlays[folder_name].is_alive():
            opened_overlays[folder_name].terminate()
            opened_overlays[folder_name].join(timeout=1)
            time.sleep(0.5)
        
        return launch_overlay_with_transparency(folder_name, False)
    
    return jsonify({'status': 'error', 'message': 'Overlay not found.'}), 404

@interface_bp.route('/toggle_to_transparent', methods=['POST'])
def toggle_to_transparent():
    data = request.get_json()
    overlay_name = data.get('overlay')
    position = data.get('position')
    
    folder_name = next((overlay['folder_name'] for overlay in get_overlays().json if overlay['display_name'] == overlay_name), None)
    
    if folder_name:
        if position:
            save_overlay_position(folder_name, position['x'], position['y'])
        
        if folder_name in opened_overlays and opened_overlays[folder_name] is not None and opened_overlays[folder_name].is_alive():
            opened_overlays[folder_name].terminate()
            opened_overlays[folder_name].join(timeout=1)
            time.sleep(0.5)
        
        return launch_overlay_with_transparency(folder_name, True)
    
    return jsonify({'status': 'error', 'message': 'Overlay not found.'}), 404

@interface_bp.route('/report_window_position', methods=['POST'])
def report_window_position():
    """
    Endpoint for pywebview windows to report their position directly from the window process
    """
    data = request.get_json()
    folder_name = data.get('folder_name')
    position = data.get('position')
    dpi_scale = data.get('dpi_scale', 1.0) 
    
    if not folder_name or not position:
        return jsonify({'status': 'error', 'message': 'Missing required data'}), 400
    
    position['x'] = int(position['x'])
    position['y'] = int(position['y'])
    
    logging.info(f"Saving position for {folder_name}: x={position['x']}, y={position['y']} with DPI scale: {dpi_scale}")
    
    properties_path = os.path.join(os.path.dirname(__file__), '..', 'overlays', folder_name, 'properties.json')
    
    if os.path.exists(properties_path):
        with open(properties_path, 'r') as properties_file:
            properties = json.load(properties_file)
            
        properties['position'] = {'x': position['x'], 'y': position['y']}
        properties['dpi_info'] = {'scale': dpi_scale}
            
        with open(properties_path, 'w') as properties_file:
            json.dump(properties, properties_file, indent=4)
    
    if save_overlay_position(folder_name, position['x'], position['y']):
        if folder_name in opened_overlays and opened_overlays[folder_name] is not None and opened_overlays[folder_name].is_alive():
            try:
                opened_overlays[folder_name].terminate()
                opened_overlays[folder_name].join(timeout=1)
                time.sleep(0.5)
                
                return launch_overlay_with_transparency(folder_name, True)
            except Exception as e:
                logging.error(f"Error toggling overlay: {e}")
                return jsonify({'status': 'error', 'message': 'Error toggling overlay', 'error': str(e)}), 500
        
        return jsonify({
            'status': 'success',
            'message': f'Position for {folder_name} saved',
            'position': position,
            'dpi_scale': dpi_scale
        }), 200
    else:
        return jsonify({'status': 'error', 'message': 'Failed to save position'}), 500

def launch_overlay_with_transparency(folder_name, is_transparent):
    """Helper function to launch overlay with specified transparency"""
    # Reuse the theme pinned by the last /launch for this overlay so
    # positioning toggles do not silently revert the theme.
    overlay_url = overlay_launch_url(folder_name, overlay_theme_preferences.get(folder_name))
    properties_path = os.path.join(os.path.dirname(__file__), '..', 'overlays', folder_name, 'properties.json')
    
    if os.path.exists(properties_path):
        with open(properties_path, 'r') as properties_file:
            properties = json.load(properties_file)
            resolution = properties.get('resolution', {'width': 800, 'height': 600})
            position = properties.get('position', None)
    else:
        return jsonify({'status': 'error', 'message': f'Overlay {folder_name} properties not found.'}), 404
    
    exit_flag = multiprocessing.Value('i', 0)
    
    process = multiprocessing.Process(
        target=launch_overlay_window, 
        args=(overlay_url, scaled_resolution(resolution, folder_name), exit_flag, is_transparent, position, folder_name)
    )
    process.daemon = True
    process.start()
    
    opened_overlays[folder_name] = process
    
    return jsonify({
        'status': 'success', 
        'message': f'Overlay {folder_name} launched with transparency={is_transparent}.',
        'transparent': is_transparent
    }), 200

@interface_bp.route('/save_position', methods=['POST'])
def save_position():
    data = request.get_json()
    overlay_name = data.get('overlay')
    
    folder_name = next((overlay['folder_name'] for overlay in get_overlays().json if overlay['display_name'] == overlay_name), None)
    
    if folder_name:
        position = data.get('position')
        
        if position:
            save_overlay_position(folder_name, position['x'], position['y'])
            
            return jsonify({
                'status': 'success', 
                'message': f'Position saved for {folder_name}.', 
                'position': position
            }), 200
        else:
            return jsonify({'status': 'error', 'message': 'No position data provided.'}), 400
    
    return jsonify({'status': 'error', 'message': 'Overlay not found.'}), 404

def save_overlay_position(folder_name, x, y):
    """
    Save the overlay position to its properties.json file
    """
    properties_path = os.path.join(os.path.dirname(__file__), '..', 'overlays', folder_name, 'properties.json')
    
    if os.path.exists(properties_path):
        with open(properties_path, 'r') as properties_file:
            properties = json.load(properties_file)
        
        # Update position
        properties['position'] = {'x': x, 'y': y}
        
        # Write back to file
        with open(properties_path, 'w') as properties_file:
            json.dump(properties, properties_file, indent=4)
        
        logging.debug(f"Saved position for {folder_name}: {x}, {y}")
        return True
    
    logging.error(f"Could not find properties file for {folder_name}")
    return False

@interface_bp.route('/close_overlay', methods=['POST'])
def close_overlay():
    """
    Close a specific overlay
    """
    data = request.get_json()
    overlay_name = data.get('overlay')
    folder_name = data.get('folder_name')
    
    if not folder_name:
        folder_name = next((overlay['folder_name'] for overlay in get_overlays().json 
                            if overlay['display_name'] == overlay_name), None)
    
    if folder_name:
        logging.debug(f"Attempting to close overlay: {folder_name}")
        
        if folder_name in opened_overlays and opened_overlays[folder_name] is not None and opened_overlays[folder_name].is_alive():
            try:
                logging.debug(f"Terminating overlay process: {folder_name}")
                opened_overlays[folder_name].terminate()
                opened_overlays[folder_name].join(timeout=1)
                del opened_overlays[folder_name]
                return jsonify({'status': 'success', 'message': f'Overlay {overlay_name} closed successfully'}), 200
            except Exception as e:
                logging.error(f"Error closing overlay: {e}")
                return jsonify({'status': 'error', 'message': str(e)}), 500
        else:
            logging.debug(f"Overlay {folder_name} is not running or already closed")
            return jsonify({'status': 'success', 'message': f'Overlay {overlay_name} is already closed'}), 200
    
    return jsonify({'status': 'error', 'message': 'Invalid overlay name provided'}), 400

@interface_bp.route('/get_active_overlays', methods=['GET'])
def get_active_overlays():
    """
    Return a list of currently active overlays
    """
    active = {}
    
    for folder_name, process in opened_overlays.items():
        if process is not None and process.is_alive():
            display_name = None
            for overlay in get_overlays().json:
                if overlay['folder_name'] == folder_name:
                    display_name = overlay['display_name']
                    break
            
            active[folder_name] = {
                'display_name': display_name,
                'folder_name': folder_name,
                'active': True
            }
    
    return jsonify({
        'status': 'success',
        'active_overlays': active
    }), 200

def launch_overlay_window(url, resolution, exit_flag=None, transparent=True, position=None, folder_name=None):
    """
    Launch the overlay window in a separate process with the specified resolution.
    """
    try:
        overlay_window = OverlayWindow(
            url, 
            width=resolution['width'], 
            height=resolution['height'], 
            transparent=transparent,
            on_top=True
        )
        
        if folder_name:
            overlay_window.set_folder_name(folder_name)
            
        if position:
            logging.info(f"Setting position for {folder_name}: {position}")
            overlay_window.position = position
        
        def on_closed():
            logging.debug(f"Window for {folder_name} closed")
            if folder_name and folder_name in opened_overlays:
                del opened_overlays[folder_name]
            sys.exit(0)
            
        overlay_window.set_on_closed(on_closed)
        
        overlay_window.create_overlay_window()
    except Exception as e:
        logging.error(f"Error launching overlay window: {e}")
        sys.exit(1)
