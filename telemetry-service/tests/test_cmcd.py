import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cmcd import cmcd_value, extract_cmcd, parse_cmcd


class CmcdTests(unittest.TestCase):
    def test_parse_header_payload(self):
        self.assertEqual(
            parse_cmcd('bl=8000,bs,cid="eldorado",mtp=6200,sid="session-1"'),
            {
                "bl": 8000,
                "bs": True,
                "cid": "eldorado",
                "mtp": 6200,
                "sid": "session-1",
            },
        )

    def test_headers_take_precedence_over_query(self):
        log = {
            "request": {
                "uri": "/segment.m4s?CMCD=mtp%3D1%2Csid%3D%22wrong%22",
                "headers": {
                    "Cmcd-Request": ["mtp=9000"],
                    "Cmcd-Session": ['sid="right"'],
                },
            }
        }
        self.assertEqual(extract_cmcd(log), {"mtp": 9000, "sid": "right"})

    def test_extracts_cmcd_v2_unified_header_from_cdn_log(self):
        log = {
            "request": {
                "uri": "/video/segment.m4s",
                "headers": {
                    "CMCD": 'v=2,sid="session-1",ot=v,mtp=(12000;v 3000;a)'
                },
            }
        }

        cmcd = extract_cmcd(log)

        self.assertEqual(cmcd["sid"], "session-1")
        self.assertEqual(cmcd_value(cmcd, "mtp", "v"), 12000)

    def test_parse_v2_inner_lists(self):
        parsed = parse_cmcd(
            'bl=(0;v 2000;a),mtp=(15000;v 6000;a),sid="session-1",v=2'
        )
        self.assertEqual(cmcd_value(parsed, "bl", "v"), 0)
        self.assertEqual(cmcd_value(parsed, "bl", "a"), 2000)
        self.assertEqual(cmcd_value(parsed, "mtp", "v"), 15000)
        self.assertEqual(parsed["v"], 2)

    def test_parse_v2_event(self):
        parsed = parse_cmcd(
            'cid="video",e=rr,rc=200,sid="session-1",ts=123,ttfb=20,ttlb=90,v=2'
        )
        self.assertEqual(parsed["e"], "rr")
        self.assertEqual(parsed["ttlb"], 90)


if __name__ == "__main__":
    unittest.main()
