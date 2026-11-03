"""Build RAH iRacing Overlay into a Windows executable.

Usage (or just double-click build.bat):
    python build_exe.py              # tests + build + zip
    python build_exe.py --skip-tests # build + zip only
    python build_exe.py --no-zip     # skip release archive

Everything is installed into an isolated .venv-build folder, so your global
Python is never modified and the bundle only contains the pinned dependencies.
Output: dist/RAH_Telemetry_Overlay/RAH_Telemetry_Overlay.exe and release/*.zip
"""

import argparse
import datetime
import hashlib
import os
import platform
import shutil
import struct
import subprocess
import sys
import venv

ROOT = os.path.dirname(os.path.abspath(__file__))
VENV_DIR = os.path.join(ROOT, '.venv-build')
VENV_PYTHON = os.path.join(VENV_DIR, 'Scripts', 'python.exe')
REQUIREMENTS = [os.path.join(ROOT, 'requirements.txt'), os.path.join(ROOT, 'requirements-build.txt')]
STAMP = os.path.join(VENV_DIR, '.requirements.sha256')
SPEC = os.path.join(ROOT, 'src', 'RAH_Telemetry_Overlay.spec')
APP_NAME = 'RAH_Telemetry_Overlay'
DIST_DIR = os.path.join(ROOT, 'dist')
WORK_DIR = os.path.join(ROOT, 'build')
RELEASE_DIR = os.path.join(ROOT, 'release')
SUPPORTED = ((3, 10), (3, 13))  # pythonnet 3.0.5 / pywebview 4.4.1 range


def fail(message):
    print(f"\nERROR: {message}")
    sys.exit(1)


def step(message):
    print(f"\n==> {message}")


def run(args, **kwargs):
    print('   ', ' '.join(args))
    result = subprocess.run(args, cwd=ROOT, **kwargs)
    if result.returncode != 0:
        fail(f"command failed with exit code {result.returncode}")


def check_host():
    if platform.system() != 'Windows':
        fail("the executable can only be built on Windows (iRacing SDK and WebView2 are Windows-only).")
    version = sys.version_info[:2]
    if not SUPPORTED[0] <= version <= SUPPORTED[1]:
        fail(f"Python {version[0]}.{version[1]} is not supported. Install 64-bit Python "
             f"{SUPPORTED[0][0]}.{SUPPORTED[0][1]}-{SUPPORTED[1][0]}.{SUPPORTED[1][1]} from https://www.python.org/downloads/windows/")
    if struct.calcsize('P') * 8 != 64:
        fail("64-bit Python is required.")
    print(f"Python {platform.python_version()} (64-bit) on {platform.system()} {platform.release()}")


def requirements_hash():
    digest = hashlib.sha256(sys.version.encode())
    for path in REQUIREMENTS:
        with open(path, 'rb') as handle:
            digest.update(handle.read())
    return digest.hexdigest()


def ensure_build_env():
    expected = requirements_hash()
    if os.path.exists(VENV_PYTHON) and os.path.exists(STAMP):
        with open(STAMP, encoding='ascii') as handle:
            if handle.read().strip() == expected:
                step("Build environment up to date (.venv-build)")
                return
    step("Preparing isolated build environment (.venv-build)")
    if not os.path.exists(VENV_PYTHON):
        venv.create(VENV_DIR, with_pip=True)
    run([VENV_PYTHON, '-m', 'pip', 'install', '--disable-pip-version-check', '--upgrade', 'pip'])
    run([VENV_PYTHON, '-m', 'pip', 'install', '--disable-pip-version-check', '-r', REQUIREMENTS[1]])
    with open(STAMP, 'w', encoding='ascii') as handle:
        handle.write(expected)


def run_tests():
    step("Running Python test suite")
    env = dict(os.environ, FORCE_THREADING_MODE='true', PYTHONDONTWRITEBYTECODE='1')
    run([VENV_PYTHON, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py'], env=env)


def ensure_app_closed():
    result = subprocess.run(['tasklist', '/FI', f'IMAGENAME eq {APP_NAME}.exe', '/NH'],
                            capture_output=True, text=True)
    if f'{APP_NAME}.exe' in result.stdout:
        fail(f"{APP_NAME}.exe is running. Close it and run the build again.")


def build():
    step("Building executable with PyInstaller")
    ensure_app_closed()
    for path in (WORK_DIR, os.path.join(DIST_DIR, APP_NAME)):
        if not os.path.exists(path):
            continue
        try:
            shutil.rmtree(path)
        except PermissionError as error:
            fail(f"cannot remove {path}: {error}. Close any program using it and retry.")
    run([VENV_PYTHON, '-m', 'PyInstaller', SPEC, '--noconfirm', '--clean',
         '--distpath', DIST_DIR, '--workpath', WORK_DIR])
    exe = os.path.join(DIST_DIR, APP_NAME, f'{APP_NAME}.exe')
    if not os.path.exists(exe):
        fail("PyInstaller finished but the executable was not produced.")
    return exe


def make_zip():
    step("Creating release archive")
    try:
        revision = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=ROOT,
                                  capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        revision = 'local'
    os.makedirs(RELEASE_DIR, exist_ok=True)
    name = f"{APP_NAME}-{datetime.date.today():%Y%m%d}-{revision}"
    return shutil.make_archive(os.path.join(RELEASE_DIR, name), 'zip', DIST_DIR, APP_NAME)


def main():
    parser = argparse.ArgumentParser(description="Build the RAH iRacing Overlay executable.")
    parser.add_argument('--skip-tests', action='store_true', help="do not run the Python test suite first")
    parser.add_argument('--no-zip', action='store_true', help="do not create the release .zip")
    options = parser.parse_args()

    print("========== Building RAH iRacing Overlay ==========")
    check_host()
    ensure_build_env()
    if not options.skip_tests:
        run_tests()
    exe = build()
    archive = None if options.no_zip else make_zip()

    print("\n============ BUILD COMPLETED ============")
    print(f"Executable: {exe}")
    if archive:
        print(f"Release zip: {archive}")


if __name__ == '__main__':
    main()
