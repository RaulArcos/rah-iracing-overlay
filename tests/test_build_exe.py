import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_exe


class TestBuildProcessCheck(unittest.TestCase):
    def test_localized_tasklist_output_does_not_require_utf8_decoding(self):
        output = b'INFORMACI\xe0N: no hay tareas coincidentes.\r\n'

        def tasklist_result(args, **options):
            if options.get('text'):
                output.decode('utf-8')
            return subprocess.CompletedProcess(args, 0, stdout=output, stderr=b'')

        with patch('build_exe.subprocess.run', side_effect=tasklist_result):
            build_exe.ensure_app_closed()

    def test_running_overlay_stops_build_before_output_is_removed(self):
        result = subprocess.CompletedProcess([], 0,
            stdout=b'RAH_Telemetry_Overlay.exe 1234 Console 1\r\n', stderr=b'')
        with patch('build_exe.subprocess.run', return_value=result):
            with self.assertRaises(SystemExit) as stopped:
                build_exe.ensure_app_closed()
        self.assertEqual(stopped.exception.code, 1)
