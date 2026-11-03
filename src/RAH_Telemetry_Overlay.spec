# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for RAH iRacing Overlay. Run through build.bat / build_exe.py.

import os

import eventlet
from PyInstaller.utils.hooks import collect_submodules

base_dir = SPECPATH  # directory containing this spec (src/)


def collect_data_files(folder):
    """Bundle every file under src/<folder>, keeping relative paths, skipping caches."""
    files = []
    for root, dirs, names in os.walk(os.path.join(base_dir, folder)):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for name in names:
            if name.endswith(('.pyc', '.pyo')):
                continue
            files.append((os.path.join(root, name), os.path.relpath(root, base_dir)))
    return files


datas = []
for folder in ('overlays', 'interface', 'common'):
    datas.extend(collect_data_files(folder))

# eventlet patches modules dynamically; ship the package as files so its hubs resolve.
datas.append((os.path.dirname(eventlet.__file__), 'eventlet'))

hidden_imports = [
    'engineio.async_drivers.threading',
    'engineio.async_drivers.eventlet',
    'irsdk',
    'yaml',
    'flask_socketio',
    'simple_websocket',
    *collect_submodules('eventlet.hubs'),
    *collect_submodules('eventlet.green'),
    *collect_submodules('dns'),
]

a = Analysis(
    [os.path.join(base_dir, 'app.py')],
    pathex=[base_dir],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'numpy', 'PIL', 'pytest', 'playwright'],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='RAH_Telemetry_Overlay',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=os.path.join(base_dir, 'interface', 'static', 'images', 'app_icon.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='RAH_Telemetry_Overlay',
)
