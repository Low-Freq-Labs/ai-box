import importlib.machinery
from pathlib import Path
import socket
import struct
import tempfile
import types
import unittest

worker = importlib.machinery.SourceFileLoader('container_worker', str(Path(__file__).resolve().parents[1] / 'assets/container-worker')).load_module()

class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.account = types.SimpleNamespace(pw_dir=self.temp.name, pw_name='fixture', pw_uid=123456)
        self.request = dict(v=1, tool='podman', argv=['version'], cwd=self.temp.name,
                            tty=False, rows=24, cols=80, term='xterm-256color')
    def tearDown(self):
        self.temp.cleanup()
    def test_valid_request(self):
        self.assertEqual(worker.validate(self.request, self.account), Path(self.temp.name))
    def test_closed_tool_set(self):
        for value in ('sh', '../bin/sh', '/usr/bin/podman'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                worker.validate(dict(self.request, tool=value), self.account)
    def test_no_extra_environment_or_schema_fields(self):
        with self.assertRaises(ValueError):
            worker.validate(dict(self.request, env={'LD_PRELOAD': '/tmp/evil'}), self.account)
    def test_structured_args_only(self):
        for argv in ('version; id', [None], ['\0'], ['x'] * 513):
            with self.subTest(argv=str(argv)[:30]), self.assertRaises(ValueError):
                worker.validate(dict(self.request, argv=argv), self.account)
    def test_path_prefix_is_not_containment(self):
        with tempfile.TemporaryDirectory(prefix=Path(self.temp.name).name + '-', dir=Path(self.temp.name).parent) as other:
            with self.assertRaises(ValueError):
                worker.validate(dict(self.request, cwd=other), self.account)
    def test_symlink_escape(self):
        (Path(self.temp.name) / 'escape').symlink_to('/etc', target_is_directory=True)
        with self.assertRaises(ValueError):
            worker.validate(dict(self.request, cwd=str(Path(self.temp.name) / 'escape')), self.account)
    def test_terminal_bounds(self):
        for field, value in [('tty', 1), ('rows', 0), ('cols', 1001), ('rows', True), ('term', 'xterm;id')]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                worker.validate(dict(self.request, **{field: value}), self.account)
    def test_frame_roundtrip(self):
        left, right = socket.socketpair()
        try:
            worker.send(left, b'I', b'quotes \"\x00 and binary\xff')
            self.assertEqual(worker.receive(right), (b'I', b'quotes \"\x00 and binary\xff'))
        finally:
            left.close(); right.close()
    def test_oversized_frame_rejected_before_body(self):
        left, right = socket.socketpair()
        try:
            left.sendall(struct.pack('!cI', b'J', worker.MAX_FRAME + 1))
            with self.assertRaises(ValueError):
                worker.receive(right)
        finally:
            left.close(); right.close()
    def test_peer_uid_is_mandatory(self):
        left, right = socket.socketpair()
        try:
            worker.execute(right, self.account)
            self.assertEqual(worker.receive(left)[0], b'R')
            self.assertEqual(worker.receive(left), (b'X', b'125'))
        finally:
            left.close(); right.close()

if __name__ == '__main__':
    unittest.main()
