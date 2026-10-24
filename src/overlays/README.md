# Creating a New Overlay for iRacing Input Telemetry

## Overlay Structure

Each overlay consists of the following components:

1. A folder in `src/overlays/` with the overlay name (e.g., `my_overlay`)
2. HTML file (`my_overlay.html`)
3. Static files folder containing:
   - CSS file (`static/my_overlay.css`)
   - JavaScript file (`static/my_overlay.js`)
   - Optional images (`static/images/`)
4. Configuration file (`properties.json`)

## Step-by-Step Implementation

### 1. Create the folder structure

```
src/overlays/my_overlay/
├── my_overlay.html
├── properties.json
└── static/
    ├── my_overlay.css
    ├── my_overlay.js
    └── images/
        └── ... (optional images)
```

### 2. Create the properties.json file

```json
{
    "name": "my_overlay",
    "display_name": "My Overlay",
    "description": "Description of what your overlay does",
    "resolution": {
        "width": 640,
        "height": 160
    },
    "position": {
        "x": 100,
        "y": 100
    },
    "dpi_info": {
        "scale": 1.25
    }
}
```

### 3. Create the HTML file

Create `my_overlay.html` with the basic structure:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>My Overlay</title>
    <link rel="stylesheet" href="{{ url_for('overlays.serve_static', overlay_name='my_overlay', filename='my_overlay.css') }}">
    <script src="{{ url_for('overlays.serve_static', overlay_name='my_overlay', filename='my_overlay.js') }}"></script>
    <script src="{{ url_for('serve_common_js', filename='socket.io.min.js') }}"></script>
</head>
<body>
    <div class="my-overlay-container pywebview-drag-region">
        <!-- Your overlay content goes here -->
    </div>
</body>
</html>
```

### 4. Create the CSS file

Create `static/my_overlay.css` with basic styling:

```css
html, body {
    margin: 0;
    padding: 0;
    width: 100%;
    height: 100%;
    background: rgba(0, 0, 0, 0); /* Fully transparent */
    position: relative;
    transform: translateZ(0);
    will-change: transform;
}

.my-overlay-container {
    background: rgba(15, 15, 15, 0.8);
    border-radius: 12px;
    padding: 12px;
    width: 300px;
    cursor: move;
    color: #f1f1f1;
    font-family: Arial, sans-serif;
    pointer-events: auto;
    z-index: 1000;
    position: relative;
    transform: translateZ(0);
    will-change: transform; 
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    border: 1px solid rgba(255, 255, 255, 0.1);
}

/* Add your custom styling here */
```

### 5. Create the JavaScript file

Create `static/my_overlay.js` with Socket.IO connection and data handling:

```javascript
document.addEventListener("DOMContentLoaded", function() {
    var socket = io('/my_overlay', {
        reconnection: true,
        reconnectionAttempts: Infinity,
        reconnectionDelay: 1000,
        reconnectionDelayMax: 5000,
        timeout: 20000
    });

    // Track connection status
    let isConnected = false;
    let reconnectTimer = null;

    socket.on('connect', function() {
        console.log("Connected to my_overlay namespace");
        isConnected = true;
        clearTimeout(reconnectTimer);
    });

    socket.on('my_overlay_update', function(data) {
        console.log("Received data update");
        updateOverlayData(data);
    });

    // Handle heartbeats to ensure connection is alive
    socket.on('heartbeat', function(data) {
        console.log("Heartbeat received");
    });

    socket.on('disconnect', function() {
        console.log("Disconnected from my_overlay namespace");
        isConnected = false;
        
        // Try to reconnect manually if socket.io reconnection fails
        reconnectTimer = setTimeout(function() {
            if (!isConnected) {
                console.log("Manually attempting to reconnect...");
                socket.connect();
            }
        }, 3000);
    });
    
    socket.on('error', function(error) {
        console.error("Socket error:", error);
    });
    
    socket.on('reconnect_attempt', function() {
        console.log("Attempting to reconnect...");
    });
    
    socket.on('reconnect', function(attemptNumber) {
        console.log("Reconnected after", attemptNumber, "attempts");
    });

    function updateOverlayData(data) {
        // Validate input data
        if (!data || typeof data !== 'object') {
            console.error('Invalid data received:', data);
            return;
        }

        // Your code to update the UI based on received data
        // Example:
        // document.getElementById('value-display').innerText = data.value;
    }
});
```

Overlays that follow the shared themes should load `overlay_theme.js` and the
shared `overlay-theme.css` after their own stylesheet and build on the
`.rah-card` / `.rah-metric` / `.rah-status` utility classes (see
`docs/overlay-themes.md`). `fuel_finish` and `session_strip` are complete
examples that also show a dedicated nullable event and an explicit
unavailable/disconnected state (see `docs/fuel-session.md`).

### 6. Modify web_interface.py to register your namespace

Add your namespace to the `_setup_namespaces` method in `web_interface.py`:

```python
def _setup_namespaces(self) -> None:
    # ... existing code ...
    
    for overlay in available_overlays:
        if overlay == 'driver_in_front':
            self.socketio.on_namespace(DriverInFrontNamespace(f'/{overlay}'))
        elif overlay == 'input_telemetry':
            self.socketio.on_namespace(TelemetryNamespace(f'/{overlay}'))
        elif overlay == 'my_overlay':
            # Register your overlay namespace
            self.socketio.on_namespace(YourNamespace(f'/{overlay}'))
```

### 7. Add your namespace class to web_interface.py

```python
class YourNamespace(Namespace):
    """Socket.IO namespace for your overlay data."""
    
    def on_connect(self) -> None:
        """Handle client connection to namespace."""
        logging.info("Client connected to your overlay namespace")

    def on_disconnect(self) -> None:
        """Handle client disconnection from namespace."""
        logging.info("Client disconnected from your overlay namespace")
```

### 8. If you need additional data, modify data_provider.py

If your overlay requires additional data not already provided by the DataProvider class:

1. Add the new data extraction to the `_extract_data` or create a new method.
2. Ensure your data is included in the returned dictionary.

```python
def _extract_data(self) -> Dict[str, float | int]:
    # ... existing code ...
    
    # Add your custom data extraction
    your_data = float(self.ir_sdk['YourDataField'] or 0.0)
    
    base = {
        # ... existing fields ...
        "your_data_field": your_data,
    }
    
    return {**base, **self._compute_overlay_metrics()}
```

### 9. Update the telemetry data emission in web_interface.py

In the `_process_telemetry_data` method, add emission for your overlay:

```python
def _process_telemetry_data(self) -> None:
    # ... existing code ...
    
    # Create your overlay data
    your_overlay_data = {
        'your_data_field': data.get('your_data_field', 0.0),
        # Add other fields as needed
    }
    
    try:
        self.socketio.emit('my_overlay_update', your_overlay_data, namespace='/my_overlay')
    except Exception as e:
        logging.error(f"Error in your overlay processing: {e}")
```

## Testing Your Overlay

1. Start the application
2. Your overlay should automatically appear in the list of available overlays
3. Click to enable your overlay and test its functionality

## Best Practices

1. Validate all data before using it in JavaScript
2. Handle connection issues gracefully
3. Keep your overlay's CPU and memory usage low
4. Follow the existing code style and patterns
5. Add clear error logging for debugging 