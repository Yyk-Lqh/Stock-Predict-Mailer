import json
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from stock_predict_mailer.core import Config
from stock_predict_mailer.upload_server import make_server


class UploadServerTests(unittest.TestCase):
    def test_upload_process_publish_and_request_boundaries(self):
        with tempfile.TemporaryDirectory() as folder:
            server = make_server(Config(Path(folder)), 0)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            root = f"http://127.0.0.1:{server.server_port}"
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            try:
                page = opener.open(root).read().decode()
                token = re.search('name="upload-session" content="([^"]+)"', page).group(1)
                for path in ("/app.js", "/style.css"):
                    self.assertEqual(opener.open(root + path).status, 200)
                with self.assertRaises(urllib.error.HTTPError) as error:
                    opener.open(root + "/api/uploads")
                self.assertEqual(error.exception.code, 403)
                headers = {"X-Upload-Token": token, "Origin": root}
                raw = b'date,code,open,high,low,close,volume\n2026-10-23,sh.603278,10,11,9,10,100\n'
                req = urllib.request.Request(root + "/api/upload?name=test.csv", data=raw, headers=headers)
                uploaded = json.load(opener.open(req))
                self.assertEqual(uploaded["status"], "needs_attention")
                values = {"upload_id": uploaded["upload_id"], "options": {"source": "fixture", "price_basis": "unadjusted", "volume_unit": "shares", "available_at": "2026-10-24T08:00:00+08:00"}}
                req = urllib.request.Request(root + "/api/process", data=json.dumps(values).encode(), headers=headers)
                processed = json.load(opener.open(req))
                self.assertEqual(processed["status"], "ready")
                req = urllib.request.Request(root + "/api/publish", data=json.dumps({"upload_id": uploaded["upload_id"], "table_index": 0}).encode(), headers=headers)
                published = json.load(opener.open(req))
                self.assertEqual(published["row_count"], 1)
                bad = {**headers, "Origin": "https://evil.example"}
                with self.assertRaises(urllib.error.HTTPError) as error:
                    opener.open(urllib.request.Request(root + "/api/scan", data=b"{}", headers=bad))
                self.assertEqual(error.exception.code, 403)
                with self.assertRaises(urllib.error.HTTPError) as error:
                    opener.open(urllib.request.Request(root, headers={"Host": "evil.example"}))
                self.assertEqual(error.exception.code, 403)
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
