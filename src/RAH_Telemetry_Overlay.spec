# -*- mode: python ; coding: utf-8 -*-

import os
import sys
import platform
from pathlib import Path
import eventlet

# Define the base directory
base_dir = os.path.abspath(os.path.dirname('src'))
if os.path.basename(os.getcwd()) == 'src':
    base_dir = os.getcwd()
else:
    base_dir = os.path.join(os.getcwd(), 'src')

# Define directories for data files
overlays_dir = os.path.join(base_dir, 'overlays')
interface_dir = os.path.join(base_dir, 'interface')
common_dir = os.path.join(base_dir, 'common')

def collect_data_files(root_dir, project_base_dir):
    collected_files = []
    for current_root, _, files in os.walk(root_dir):
        for filename in files:
            src_path = os.path.join(current_root, filename)
            rel_path = os.path.relpath(src_path, project_base_dir)
            dst_path = os.path.dirname(rel_path)
            collected_files.append((rel_path, dst_path))
    return collected_files


# Get all data files
datas = []
datas.extend(collect_data_files(overlays_dir, base_dir))
datas.extend(collect_data_files(interface_dir, base_dir))
datas.extend(collect_data_files(common_dir, base_dir))

block_cipher = None

# Get the path to app.py
app_path = os.path.join(base_dir, 'app.py')
if not os.path.exists(app_path):
    print(f"Warning: {app_path} does not exist!")
    app_path = 'app.py'  # Fallback to relative path

# Set the icon path for the executable
ico_path = os.path.join(base_dir, 'interface', 'static', 'images', 'app_icon.ico')
if not os.path.exists(ico_path):
    print(f"Warning: Icon file {ico_path} does not exist!")
    # Try to run the icon creation script
    try:
        print("Attempting to create icon file...")
        create_ico_script = os.path.join(base_dir, 'create_ico.py')
        if os.path.exists(create_ico_script):
            import subprocess
            subprocess.run([sys.executable, create_ico_script])
            if os.path.exists(ico_path):
                print(f"Successfully created icon file: {ico_path}")
            else:
                print("Icon creation script ran but icon file was not created.")
                ico_path = None
        else:
            print(f"Icon creation script not found: {create_ico_script}")
            ico_path = None
    except Exception as e:
        print(f"Error running icon creation script: {e}")
        ico_path = None
else:
    print(f"Using existing icon file: {ico_path}")

# Add additional hidden imports for Windows
hidden_imports = [
    # Import all eventlet hub types
    'eventlet.hubs.epolls',
    'eventlet.hubs.kqueue',
    'eventlet.hubs.selects',
    'eventlet.hubs.selectors',
    'eventlet.hubs.poll',
    'eventlet.hubs.hub',
    'eventlet.hubs.impl_select',
    'eventlet.hubs.impl_poll',
    'eventlet.hubs.timer',
    # Other eventlet modules
    'eventlet.greenio',
    'eventlet.greenthread',
    'eventlet.queue',
    'eventlet.patcher',
    'eventlet.corolocal',
    'eventlet.semaphore',
    'eventlet.websocket',
    'eventlet.event',
    'eventlet.green',
    'eventlet.support',
    # Other dependencies
    'selectors',
    'select',
    'socket',
    'dns',
    'dns.dnssec',
    'dns.e164',
    'dns.hash',
    'dns.namedict',
    'dns.tsigkeyring',
    'dns.update',
    'dns.version',
    'dns.zone',
    'dns.versioned',
    'dns.resolver',
    'dns.message',
    'dns.name',
    'dns.tokenizer',
    'dns.rdatatype',
    'dns.rdataclass',
    'dns.rdtypes',
    'dns.exception',
    'dns.wiredata',
    'dns.flags',
    'engineio.async_drivers.eventlet',
    'engineio.async_drivers.threading',
    'irsdk',
    'flask',
    'flask_socketio',
    'threading',
    'multiprocessing',
    'socketio',
    'socketio.client',
    'eventlet.green.subprocess',
    'eventlet.green.os',
    'eventlet.green.select',
    'eventlet.green.socket',
    'eventlet.green.thread',
    'eventlet.green.threading',
    'eventlet.green.time',
    '_thread',
    'queue',
]

# Windows-specific additional hidden imports
if platform.system() == 'Windows':
    hidden_imports.extend([
        'eventlet.hubs.hub',
        'engineio.async_drivers',
        'dns.rdtypes.ANY',
        'dns.rdtypes.IN',
        'winsock',
        'win32pipe',
        'win32file',
        'win32api',
        'win32con',
    ])
    
# Add datas to ensure eventlet modules are included
eventlet_path = os.path.dirname(os.path.abspath(eventlet.__file__))
datas.append((eventlet_path, 'eventlet'))

# Add runtime hooks to ensure eventlet is properly initialized
runtime_hooks = []

a = Analysis(
    [app_path],
    pathex=[base_dir],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=runtime_hooks,
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='RAH_Telemetry_Overlay',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ico_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='RAH_Telemetry_Overlay',
)
