import os
import sys
import platform
import logging

# Windows-specific configuration for eventlet
if platform.system() == 'Windows':
    # Patch environment before importing eventlet
    os.environ['EVENTLET_NO_GREENDNS'] = 'yes'
    # Force using threading mode for reliability
    os.environ['FORCE_THREADING_MODE'] = 'true'


def _resolve_runtime_root() -> str:
    if getattr(sys, 'frozen', False):
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass and os.path.isdir(meipass):
            return meipass
        return os.path.join(os.path.dirname(sys.executable), '_internal')
    return os.path.abspath(os.path.dirname(__file__))


def _clear_zone_identifier(path: str) -> bool:
    zone_identifier_path = f"{path}:Zone.Identifier"
    try:
        os.remove(zone_identifier_path)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def _unblock_runtime_binaries() -> None:
    if platform.system() != 'Windows':
        return

    if os.environ.get('RAH_SKIP_MOTW_UNBLOCK', '0') == '1':
        return

    runtime_root = _resolve_runtime_root()
    if not os.path.isdir(runtime_root):
        return

    target_extensions = {'.dll', '.pyd', '.exe'}
    unblocked_count = 0
    unchanged_count = 0

    for root, _, files in os.walk(runtime_root):
        for filename in files:
            _, extension = os.path.splitext(filename)
            if extension.lower() not in target_extensions:
                continue

            if _clear_zone_identifier(os.path.join(root, filename)):
                unblocked_count += 1
            else:
                unchanged_count += 1

    if unblocked_count:
        logging.info("Removed Mark-of-the-Web from %s runtime binaries", unblocked_count)
    if unchanged_count:
        logging.debug("No Mark-of-the-Web change for %s runtime binaries", unchanged_count)


_unblock_runtime_binaries()

import multiprocessing
import atexit
import signal
import time
import threading

from web_interface import WebInterface, using_fallback_mode
from overlay_window import OverlayWindow

overlay_processes = []
web_interface_process = None
exit_flag = multiprocessing.Value('i', 0)  # Shared flag to signal program exit

def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller"""
    base_path = getattr(sys, '_MEIPASS', os.path.abspath(os.path.dirname(__file__)))
    return os.path.join(base_path, relative_path)

def detect_overlays():
    """
    Detect available overlays in the overlays directory.
    """
    overlays_dir = resource_path('overlays')
    return [name for name in os.listdir(overlays_dir) if os.path.isdir(os.path.join(overlays_dir, name))]

def cleanup():
    """
    Cleanup function to terminate all processes on exit
    """
    print("Cleaning up resources...")
    
    try:
        from interface import opened_overlays
        print(f"Found {len(opened_overlays)} active overlay windows to close")
        
        for overlay_name, process in opened_overlays.items():
            try:
                if process and process.is_alive():
                    print(f"Terminating overlay: {overlay_name}")
                    process.terminate()
                    process.join(timeout=1)
            except Exception as e:
                print(f"Error closing overlay {overlay_name}: {e}")
    except Exception as e:
        print(f"Error accessing opened overlays: {e}")
    
    for process in overlay_processes:
        if process.is_alive():
            process.terminate()
            process.join(timeout=1)
    
    if web_interface_process and web_interface_process.is_alive():
        web_interface_process.terminate()
        web_interface_process.join(timeout=1)
    
    print("All processes terminated successfully")

def signal_handler(sig, frame):
    """
    Handle termination signals
    """
    print(f"Received signal {sig}, shutting down...")
    cleanup()
    sys.exit(0)

def create_main_window(exit_flag):
    """
    Create the main window in a separate process
    """
    try:
        _create_main_window(exit_flag)
    except Exception as e:
        print(f"Error in main window process: {e}")
        exit_flag.value = 1


def _create_main_window(exit_flag):
    interface = OverlayWindow('http://127.0.0.1:8085/', width=1000, height=700, frameless=False)

    def on_window_closed():
        exit_flag.value = 1

    interface.set_on_closed(on_window_closed)
    interface.create_overlay_window()


def _wait_for_exit_flag():
    while True:
        if exit_flag.value == 1:
            print("Main window closed, initiating shutdown...")
            cleanup()
            break
        time.sleep(0.1)

def run_web_interface(selected_overlays):
    """
    Run the web interface in a separate process
    """
    try:
        web_interface = WebInterface(selected_overlays)
        web_interface.run()
    except Exception as e:
        print(f"Error in web interface: {e}")

def run_unified_app(selected_overlays):
    """
    Run both web interface and create window in the main thread
    This is used when we're in fallback mode to ensure pywebview runs in the main thread
    """
    try:
        web_interface = WebInterface(selected_overlays)
        
        web_thread = threading.Thread(target=lambda: web_interface.run())
        web_thread.daemon = True
        web_thread.start()
        
        time.sleep(1)
        
        print("Creating main window in main thread...")
        interface = OverlayWindow('http://127.0.0.1:8085/', width=1000, height=700, frameless=False)
        
        interface.create_overlay_window()
        print("Main window closed, shutting down...")
        
    except Exception as e:
        print(f"Error in unified app: {e}")

def main():
    """
    Main entry point for the iRacing Telemetry Overlay application.
    Initializes and runs the web interface with detected overlays.
    """
    global overlay_processes, web_interface_process
    
    atexit.register(cleanup)
    
    signal.signal(signal.SIGINT, signal_handler)  
    signal.signal(signal.SIGTERM, signal_handler) 
    
    try:
        selected_overlays = detect_overlays()
        frozen_on_windows = platform.system() == 'Windows' and getattr(sys, 'frozen', False)
        
        if using_fallback_mode or frozen_on_windows:
            print("Running in unified mode - web interface and window in same process")
            run_unified_app(selected_overlays)
            cleanup()
            return
            
        web_interface_process = multiprocessing.Process(
            target=run_web_interface,
            args=(selected_overlays,)
        )
        web_interface_process.start()
        
        time.sleep(0.5)
        
        overlay_process = multiprocessing.Process(
            target=create_main_window,
            args=(exit_flag,)
        )
        overlay_process.start()
        overlay_processes.append(overlay_process)
        _wait_for_exit_flag()
            
        sys.exit(0)

    except KeyboardInterrupt:
        print("Shutting down gracefully...")
        cleanup()
        sys.exit(0)

if __name__ == '__main__':
    multiprocessing.freeze_support()
    main()
