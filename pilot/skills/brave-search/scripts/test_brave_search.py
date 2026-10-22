"""Offline regression tests: python3 -S -m unittest discover -s scripts."""
import contextlib
import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import brave_search as brave


class FetchTests(unittest.TestCase):
    def test_success(self):
        with patch.object(brave, "urlopen", return_value=io.BytesIO(b'{"results": []}')):
            self.assertEqual(brave.fetch("news/search", "test", {"q": "news"}), {"results": []})

    def test_errors_are_explicit(self):
        cases = [
            {"return_value": io.BytesIO(b"invalid")},
            {"return_value": io.BytesIO(b"[]")},
            {"side_effect": URLError("offline")},
            {"side_effect": HTTPError("https://example.com", 429, "limit", {}, io.BytesIO(b"limit"))},
        ]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs), patch.object(brave, "urlopen", **kwargs):
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    with self.assertRaises(SystemExit) as error:
                        brave.fetch("news/search", "test", {})
                self.assertEqual(error.exception.code, 1)
                payload = json.loads(output.getvalue())
                self.assertFalse(payload["ok"])
                self.assertTrue(payload["error"])


if __name__ == "__main__":
    unittest.main()
