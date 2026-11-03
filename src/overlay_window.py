import webview
import sys
import threading
import time
import ctypes
import logging
import os

def get_windows_dpi_scaling():
    """Get the Windows DPI scaling factor.
    
    Returns:
        float: The DPI scaling factor (1.0 if not on Windows or on error)
    """
    try:
        if sys.platform == 'win32':
            user32 = ctypes.windll.user32
            try: 
                awareness = user32.GetDpiAwarenessContextForWindow(0)
                if awareness:
                    dpi = user32.GetDpiForWindow(0)
                    return dpi / 96.0 
            except AttributeError:
                try:
                    user32.SetProcessDPIAware()
                    dc = user32.GetDC(0)
                    dpi_x = ctypes.windll.gdi32.GetDeviceCaps(dc, 88)
                    user32.ReleaseDC(0, dc)
                    return dpi_x / 96.0
                except Exception:
                    pass
        return 1.0
    except Exception as e:
        logging.error(f"Error getting DPI scaling: {e}")
        return 1.0

def resource_path(relative_path):
    """Get absolute path to resource, works for both development and PyInstaller.
    
    Args:
        relative_path: The relative path to the resource
        
    Returns:
        str: The absolute path to the resource
    """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(base_path, relative_path)

class OverlayWindow:
    """Manages a webpage overlay window for displaying iRacing telemetry.
    
    This class handles window creation, positioning, and JavaScript interactions
    for telemetry overlays.
    """
    
    def __init__(self, url, width, height, frameless=True, transparent=False, on_top=False):
        """Initialize the overlay window.
        
        Args:
            url (str): URL to load in the window
            width (int): Window width
            height (int): Window height
            frameless (bool): Whether to create a window without frame
            transparent (bool): Whether to create a transparent window
        """
        self.url = url
        self.window = None
        self.width = width
        self.height = height
        self.frameless = frameless
        self.transparent = transparent
        self.on_top = on_top
        self.on_closed = None
        self.position = None
        self.folder_name = None  
        self.position_tracker_thread = None
        self.position_offset = {'x': 0, 'y': 0} 
        self.dpi_scale = get_windows_dpi_scaling() 
        logging.info(f"Windows DPI scaling detected: {self.dpi_scale}")
        self.window_closed = threading.Event()

    def set_folder_name(self, folder_name):
        """Set the folder name for position reporting.
        
        Args:
            folder_name (str): Folder name for saving position data
        """
        self.folder_name = folder_name

    def set_on_closed(self, callback):
        """Set the callback function to be called when the window is closed.
        
        Args:
            callback (callable): Function to call when window is closed
        """
        self.on_closed = callback

    def create_overlay_window(self):
        """Create and display the overlay window.
        
        This initializes the webview window with the configured settings and
        starts position tracking if appropriate.
        """
        self.window_closed.clear()
        adjusted_position = self._calculate_dpi_adjusted_position()
        window_args = self._prepare_window_arguments(adjusted_position)
        
        try:
            self.window = webview.create_window(**window_args)
            
            if self.on_closed:
                self.window.events.closed += self.on_closed_handler
                
            if not self.transparent and self.folder_name:
                # Load external JS files after window is loaded
                self.window.events.loaded += self.inject_scripts
                self._start_position_tracking()
            
            webview.start(gui='edgechromium', debug=False)
        except Exception as e:
            logging.error(f"Error creating overlay window: {e}")
    
    def _calculate_dpi_adjusted_position(self):
        """Calculate DPI-adjusted position for the window.
        
        Returns:
            dict or None: Adjusted position dictionary or None if position not set
        """
        if not self.position:
            return None
            
        adjusted_position = {
            'x': int(self.position.get('x', 0) / self.dpi_scale),
            'y': int(self.position.get('y', 0) / self.dpi_scale)
        }
        logging.info(f"Original position: {self.position}, Adjusted for DPI: {adjusted_position}")
        return adjusted_position
    
    def _prepare_window_arguments(self, position=None):
        """Prepare arguments for window creation.
        
        Args:
            position (dict, optional): Window position coordinates
            
        Returns:
            dict: Arguments for webview.create_window
        """
        window_args = {
            "title": "RAH iRacing Overlay",
            "url": self.url,
            "width": self.width,
            "height": self.height,
            "frameless": self.frameless,
            "transparent": self.transparent,
            "on_top": self.on_top,
            "easy_drag": True,
            "min_size": (200, 100),
            "background_color": "#000000",
            "text_select": False
        }
        
        if position:
            window_args["x"] = position.get('x', 0)
            window_args["y"] = position.get('y', 0)
            
        return window_args
    
    def _start_position_tracking(self):
        """Start the position tracking thread."""
        self.position_tracker_thread = threading.Thread(target=self.track_window_position)
        self.position_tracker_thread.daemon = True
        self.position_tracker_thread.start()
    
    def track_window_position(self):
        """Continuously track window position and expose it to the window."""
        if not self.window:
            return
            
        try:
            time.sleep(1)
            self._inject_dpi_scale_info()
            
            while self.window and not self.window_closed.is_set():
                try:
                    self._update_position_in_window()
                except Exception as e:
                    logging.error(f"Error updating position in JavaScript: {e}")
                    
                time.sleep(0.1)
        except Exception as e:
            logging.error(f"Error in position tracker thread: {e}")
    
    def _inject_dpi_scale_info(self):
        """Inject DPI scale information into the window."""
        js_dpi = f"""
        if (!window.pywebview) {{
            window.pywebview = {{}};
        }}
        window.pywebview.dpiScale = {self.dpi_scale};
        console.log("DPI Scale:", {self.dpi_scale});
        """
        self.window.evaluate_js(js_dpi)
    
    def _update_position_in_window(self):
        """Update the window position in JavaScript."""
        x, y = self.window.x, self.window.y
        
        scaled_x = int(x * self.dpi_scale)
        scaled_y = int(y * self.dpi_scale)
        
        js = f"""
        if (!window.pywebview) {{
            window.pywebview = {{}};
        }}
        window.pywebview.position = {{
            x: {scaled_x},
            y: {scaled_y}
        }};
        
        // Update position display if the external JS has created it
        if (typeof updatePositionDisplay === 'function') {{
            updatePositionDisplay({scaled_x}, {scaled_y}, {self.dpi_scale});
        }}
        """
        self.window.evaluate_js(js)
    
    def _load_external_js_files(self):
        """Load the external JavaScript files into the window."""
        js_files = [
            '/common/js/positioning_mode.js',
            '/common/js/position_reporter.js'
        ]
        
        js_loader = """
        function loadScriptsSequentially(scripts, callback) {
            if (scripts.length === 0) {
                if (callback) callback();
                return;
            }
            
            var src = scripts.shift();
            var script = document.createElement('script');
            script.src = src;
            
            script.onload = function() {
                console.log('Loaded script: ' + src);
                loadScriptsSequentially(scripts, callback);
            };
            
            script.onerror = function() {
                console.error('Failed to load script: ' + src);
                loadScriptsSequentially(scripts, callback);
            };
            
            document.head.appendChild(script);
        }
        
        // Load the scripts in sequence
        loadScriptsSequentially([
            '%s',
            '%s'
        ], function() {
            // Call initializers after all scripts are loaded
            console.log('All scripts loaded, initializing...');
            if (typeof initPositioningMode === 'function') {
                initPositioningMode();
            }
            
            if (typeof initPositionReporter === 'function') {
                initPositionReporter('%s');
            }
        });
        """ % (js_files[0], js_files[1], self.folder_name)
        
        self.window.evaluate_js(js_loader)

    def inject_scripts(self):
        """Inject all necessary JavaScript files and initialize them."""
        if not self.window or not self.folder_name:
            return
    
        self._load_external_js_files()
    
    def on_closed_handler(self):
        """Handler called when the window is closed."""
        self.window_closed.set()
        
        if self.on_closed:
            self.on_closed()
            
    def get_position(self):
        """Get the current position of the window.
        
        Returns:
            dict or None: Position dictionary with x, y coordinates or None if window is not available
        """
        if self.window:
            raw_x, raw_y = self.window.x, self.window.y
            return {
                'x': int(raw_x * self.dpi_scale), 
                'y': int(raw_y * self.dpi_scale)
            }
        return None
        
    def set_position(self, x, y):
        """Set the position of the window.
        
        Args:
            x (int): X coordinate
            y (int): Y coordinate
        """
        self.position = {'x': x, 'y': y}
        
        if self.window:
            adjusted_x = int(x / self.dpi_scale)
            adjusted_y = int(y / self.dpi_scale)
            logging.info(f"Moving window to: {adjusted_x}, {adjusted_y} (original: {x}, {y})")
            self.window.move(adjusted_x, adjusted_y)
            
    def toggle_transparency(self):
        """Toggle the transparency of the window.
        
        This destroys and recreates the window as transparency cannot be changed after creation.
        
        Returns:
            bool: Current transparency state
        """
        if self.window:
            position = self.get_position()
            self.window_closed.set() 
            self.window.destroy()            
            self.transparent = not self.transparent
            self.position = position
            self.create_overlay_window()
            
        return self.transparent