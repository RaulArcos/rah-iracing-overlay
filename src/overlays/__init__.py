from flask import Blueprint, render_template, send_from_directory, Response, request
import os
import sys

def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller"""
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    return os.path.join(base_path, relative_path)

overlays_bp = Blueprint(
    'overlays', __name__,
    template_folder='.',
    static_folder=None 
)

@overlays_bp.route('/<overlay_name>')
def serve_overlay(overlay_name):
    html_file_path = os.path.join(resource_path('overlays'), overlay_name, f'{overlay_name}.html')
    if os.path.exists(html_file_path):
        # Render the template with transparency support
        rendered_html = render_template(f'{overlay_name}/{overlay_name}.html')
        # Per-overlay appearance settings (opacity, zoom, accent, parts shown).
        # Identical for every request; values are fetched client-side.
        rendered_html = rendered_html.replace(
            '</head>', '<script src="/common/js/overlay_settings.js"></script>\n</head>', 1)
        # Only an unambiguous explicit opt-in loads the browser-local feed.
        # All templates register their consumers on DOMContentLoaded; these
        # trusted scripts run after Socket.IO is defined and before that event.
        if request.args.getlist('demo') == ['1']:
            scripts = ''.join(f'<script src="/common/js/{name}.js"></script>'
                              for name in ('demo_race', 'demo_scenario', 'demo_adapter'))
            rendered_html = rendered_html.replace('</head>', scripts + '\n</head>', 1)
        
        # Return with appropriate headers
        response = Response(rendered_html)
        response.headers['Content-Type'] = 'text/html; charset=utf-8'
        return response
    else:
        return "Overlay not found", 404

@overlays_bp.route('/<overlay_name>/static/<path:filename>')
def serve_static(overlay_name, filename):
    static_folder = os.path.join(resource_path('overlays'), overlay_name, 'static')
    return send_from_directory(static_folder, filename)
