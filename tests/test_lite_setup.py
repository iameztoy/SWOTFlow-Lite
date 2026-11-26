"""Exercise the Windows installer without network calls or project mutations."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from swotflow.paths import APP_ROOT


@unittest.skipUnless(os.name == 'nt' and shutil.which('powershell'), 'Windows PowerShell required')
class LiteSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix='Lite setup with spaces ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.script = self.root/'Setup_SWOTFlow_Lite.ps1'
        shutil.copy2(APP_ROOT/self.script.name, self.script)

    def run_setup(self, *arguments: str, env: dict | None = None) -> subprocess.CompletedProcess:
        """Run the real PowerShell entry point from an unrelated directory."""
        return subprocess.run(['powershell', '-NoProfile', '-File', str(self.script), '-CheckOnly', *arguments],
                              cwd=APP_ROOT, env=env, text=True, capture_output=True, timeout=60)

    def test_explicit_python_in_path_with_spaces_checks_without_creating_environment(self) -> None:
        result = self.run_setup('-PythonPath', sys.executable)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('compatibility check passed', result.stdout)
        self.assertFalse((self.root/'.venv').exists())

    def test_invalid_explicit_path_does_not_fall_back_or_create_environment(self) -> None:
        result = self.run_setup('-PythonPath', str(self.root/'missing.exe'))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('supplied -PythonPath', result.stderr)
        self.assertFalse((self.root/'.venv').exists())

    def test_incomplete_environment_is_preserved(self) -> None:
        (self.root/'.venv').mkdir()
        evidence = self.root/'.venv/keep.txt'; evidence.write_text('keep', encoding='utf-8')
        result = self.run_setup('-PythonPath', sys.executable)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('incomplete .venv', result.stderr)
        self.assertEqual(evidence.read_text(encoding='utf-8'), 'keep')

    def test_existing_environment_and_project_files_are_not_replaced(self) -> None:
        subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(self.root/'.venv')], check=True, timeout=60)
        config = self.root/'.venv/pyvenv.cfg'; before = config.read_bytes()
        project = self.root/'project.yaml'; project.write_text('keep: history', encoding='utf-8')
        result = self.run_setup()
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('Reusing the existing', result.stdout)
        self.assertEqual(config.read_bytes(), before)
        self.assertEqual(project.read_text(encoding='utf-8'), 'keep: history')


if __name__ == '__main__':
    unittest.main()
