import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('apple_desk_install', Path(__file__).resolve().parents[1] / 'scripts/install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'repo'
        self.destination = Path(self.temp.name) / 'bin'
        for name in installer.NAMES:
            path = self.root / 'cli' / name / 'bin' / name
            path.parent.mkdir(parents=True)
            path.write_text('# fixture command\n')
        helper = self.root / 'native/dist/apple-desk-calendar'
        helper.parent.mkdir(parents=True)
        helper.write_text('fixture native helper')

    def install(self):
        with patch.object(installer, 'ROOT', self.root), patch('sys.argv', ['install.py', '--bin-dir', str(self.destination)]), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return installer.main()

    def test_all_links_are_stable_on_reinstall(self):
        self.assertEqual(self.install(), 0)
        self.assertEqual(self.install(), 0)
        for name in installer.NAMES:
            self.assertEqual((self.destination / name).resolve(), (self.root / 'cli' / name / 'bin' / name).resolve())

    def test_unrelated_command_refused_before_any_links_change(self):
        self.destination.mkdir()
        protected = self.destination / 'grok-calendar'
        protected.write_text('existing user command')
        with self.assertRaises(SystemExit) as result:
            self.install()
        self.assertEqual(result.exception.code, 2)
        self.assertEqual(protected.read_text(), 'existing user command')
        self.assertEqual(list(self.destination.iterdir()), [protected])
