"""验证一键启动时的端口清理和失败中止。"""

import errno
import io
import signal
import subprocess
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import Mock, patch

from backend import dev


class DevPortTests(unittest.TestCase):
    def setUp(self):
        self.output = io.StringIO()
        self.enterContext(redirect_stdout(self.output))
        self.enterContext(redirect_stderr(self.output))

    def test_free_port_does_not_query_or_stop_processes(self):
        with (
            patch.object(dev, '_port_available', return_value=True),
            patch.object(dev, '_listener_pids') as listeners,
            patch.object(dev.os, 'kill') as kill,
        ):
            dev._release_port(18765)
        listeners.assert_not_called()
        kill.assert_not_called()

    def test_busy_port_stops_each_listener_gracefully(self):
        with (
            patch.object(dev, '_port_available', return_value=False),
            patch.object(dev, '_listener_pids', return_value={12345, 12346}),
            patch.object(dev, '_wait_for_port', return_value=True),
            patch.object(dev.os, 'getpid', return_value=99999),
            patch.object(dev.os, 'kill') as kill,
        ):
            dev._release_port(18765)
        self.assertEqual(kill.call_args_list, [
            unittest.mock.call(12345, signal.SIGTERM),
            unittest.mock.call(12346, signal.SIGTERM),
        ])

    def test_timeout_only_force_stops_original_listener(self):
        with (
            patch.object(dev, '_port_available', return_value=False),
            patch.object(dev, '_listener_pids', side_effect=[{12345}, {12345, 12346}]),
            patch.object(dev, '_wait_for_port', side_effect=[False, True]),
            patch.object(dev.os, 'getpid', return_value=99999),
            patch.object(dev.os, 'kill') as kill,
        ):
            dev._release_port(18765)
        self.assertEqual(kill.call_args_list, [
            unittest.mock.call(12345, signal.SIGTERM),
            unittest.mock.call(12345, signal.SIGKILL),
        ])

    def test_listener_exiting_before_signal_is_harmless(self):
        with (
            patch.object(dev, '_port_available', return_value=False),
            patch.object(dev, '_listener_pids', return_value={12345}),
            patch.object(dev, '_wait_for_port', return_value=True),
            patch.object(dev.os, 'getpid', return_value=99999),
            patch.object(dev.os, 'kill', side_effect=ProcessLookupError),
        ):
            dev._release_port(18765)

    def test_port_still_busy_raises_after_force_stop(self):
        with (
            patch.object(dev, '_port_available', return_value=False),
            patch.object(dev, '_listener_pids', return_value={12345}),
            patch.object(dev, '_wait_for_port', return_value=False),
            patch.object(dev.os, 'getpid', return_value=99999),
            patch.object(dev.os, 'kill'),
        ):
            with self.assertRaisesRegex(RuntimeError, '仍被占用'):
                dev._release_port(18765)

    def test_current_launcher_is_never_stopped(self):
        with (
            patch.object(dev, '_port_available', return_value=False),
            patch.object(dev, '_listener_pids', return_value={12345}),
            patch.object(dev.os, 'getpid', return_value=12345),
            patch.object(dev.os, 'kill') as kill,
        ):
            with self.assertRaisesRegex(RuntimeError, '无法自动停止自身'):
                dev._release_port(18765)
        kill.assert_not_called()

    def test_listener_lookup_uses_only_tcp_listeners_and_deduplicates_pids(self):
        result = subprocess.CompletedProcess([], 0, '12345\n12345\n12346\n', '')
        with (
            patch.object(dev.shutil, 'which', return_value='/usr/sbin/lsof'),
            patch.object(dev.subprocess, 'run', return_value=result) as run,
        ):
            self.assertEqual(dev._listener_pids(18765), {12345, 12346})
        run.assert_called_once_with(
            ['/usr/sbin/lsof', '-nP', '-t', '-iTCP:18765', '-sTCP:LISTEN'],
            capture_output=True, text=True, timeout=5,
        )

    def test_missing_lsof_reports_error(self):
        with patch.object(dev.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(RuntimeError, '未找到 lsof'):
                dev._listener_pids(18765)

    def test_bind_permission_error_is_not_treated_as_port_conflict(self):
        probe = Mock()
        probe.bind.side_effect = PermissionError(errno.EACCES, 'denied')
        with patch.object(dev.socket, 'socket') as socket:
            socket.return_value.__enter__.return_value = probe
            with self.assertRaises(PermissionError):
                dev._port_available(18765)

    def test_cleanup_failure_prevents_starting_project(self):
        with (
            patch.object(dev.shutil, 'which', return_value='/usr/bin/npm'),
            patch.object(dev.Path, 'exists', return_value=True),
            patch.object(dev, '_release_port', side_effect=PermissionError('denied')),
            patch.object(dev.subprocess, 'Popen') as start,
        ):
            self.assertEqual(dev.main(), 1)
        start.assert_not_called()
        self.assertIn('清理启动端口失败', self.output.getvalue())


if __name__ == '__main__':
    unittest.main()
