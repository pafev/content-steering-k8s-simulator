import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from logs import parse_access_log_datagram


class AccessLogTests(unittest.TestCase):
    def test_parses_nginx_syslog_datagram(self):
        raw = (
            b'<190>Sep  1 12:00:00 cdn: {"pathway":"cdn-1",'
            b'"cache_status":"HIT"}'
        )

        self.assertEqual(
            parse_access_log_datagram(raw),
            {"pathway": "cdn-1", "cache_status": "HIT"},
        )

    def test_rejects_datagram_without_json(self):
        with self.assertRaises(json.JSONDecodeError):
            parse_access_log_datagram(b"not a structured log")


if __name__ == "__main__":
    unittest.main()
