import io
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import status_ui


class StatusViewTests(unittest.TestCase):
    def setUp(self):
        self.page = status_ui.Dashboard.load()
        self.report = {"generated_at": "2026-11-17T12:00:00Z", "projects": []}

    def boot_from(self, page):
        found = re.search(r'<script\b[^>]*\bid=["\']boot["\'][^>]*>(.*?)</script>', page, re.S)
        self.assertIsNotNone(found)
        return json.loads(found.group(1))

    def test_export_displays_project_text_without_treating_it_as_markup(self):
        literal = "A </script>\n<title>本机项目</title> {{STATUS_JS}} & B"
        self.report["projects"].append({"name": literal})
        html = self.page.render(self.report).decode()
        boot = self.boot_from(html)
        self.assertEqual(boot["snapshot"], self.report)
        self.assertEqual(boot["mode"], "snapshot")
        self.assertNotIn(literal, html)
        self.assertIn("connect-src 'none'", html)
        self.assertIn("connect-src 'self'", self.page.render(self.report, live=True).decode())

    def test_export_protects_existing_file_and_requests_file_verification(self):
        with tempfile.TemporaryDirectory() as raw, patch.object(status_ui, "build_snapshot", return_value=self.report) as read:
            root = Path(raw)
            dest = root / "status.html"
            status_ui.export_snapshot(dest, self.page, [root])
            read.assert_called_once_with([root], verify_files=True)
            baseline = dest.read_bytes()
            with self.assertRaises(FileExistsError):
                status_ui.export_snapshot(dest, self.page, [root])
            self.assertEqual(dest.read_bytes(), baseline)
            with self.assertRaises(ValueError):
                status_ui.export_snapshot(root / ".experience-strategy" / "status.html", self.page, [root])

    def test_poll_reads_ledger_and_manual_refresh_rechecks_files(self):
        with patch.object(status_ui, "build_snapshot", return_value=self.report) as read:
            feed = status_ui.StatusFeed([])
            self.assertEqual(feed.read(), self.report)
            feed.read()
            self.assertEqual(read.call_count, 1)
            self.assertEqual(read.call_args.kwargs, {"verify_files": False})
            feed.read(verify=True)
            self.assertEqual(read.call_args.kwargs, {"verify_files": True})


    def test_http_status_returns_a_snapshot_and_feed_failure_is_retryable(self):
        feed = Mock()
        feed.read.return_value = self.report
        handler = status_ui.handler_for(self.page, feed)

        def request(path, *, host="127.0.0.1:9822"):
            socket = Mock()
            socket.makefile.return_value = io.BytesIO(f"GET {path} HTTP/1.0\r\nHost: {host}\r\n\r\n".encode())
            written = io.BytesIO()
            socket.sendall.side_effect = written.write
            handler(socket, ("127.0.0.1", 9833), SimpleNamespace(server_address=("127.0.0.1", 9822)))
            return written.getvalue().split(b"\r\n\r\n", 1)

        headers, payload = request("/api/status?verify=1")
        self.assertIn(b"200 OK", headers)
        self.assertEqual(json.loads(payload), self.report)
        feed.read.assert_called_once_with(verify=True)
        self.assertIn(b"404", request("/other")[0])
        self.assertIn(b"403", request("/api/status", host="external.invalid")[0])
        self.assertEqual(feed.read.call_count, 1)
        feed.read.side_effect = OSError("local fixture")
        self.assertIn(b"503", request("/api/status")[0])
