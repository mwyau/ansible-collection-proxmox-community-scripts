import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "module_utils"))
from core import ProxmoxAPI, ProxmoxError, wait_for_task


class MockResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def read(self):
        return b'{"data":{"cores":4}}'


class TestApi(unittest.TestCase):
    @patch("core.urlopen")
    def test_authenticated_https_request(self, mocked):
        mocked.return_value = MockResponse()
        api = ProxmoxAPI("pve.example.internal", "ansible@pve!managed", "secret", True)
        self.assertEqual(api.request("GET", "/nodes/pve1/lxc/120/config"), {"cores": 4})
        req = mocked.call_args.args[0]
        self.assertEqual(req.full_url, "https://pve.example.internal:8006/api2/json/nodes/pve1/lxc/120/config")
        self.assertIn("PVEAPIToken=", req.get_header("Authorization"))

    def test_invalid_api_path(self):
        api = ProxmoxAPI("pve.example.internal", "token", "secret")
        with self.assertRaises(ProxmoxError):
            api.request("GET", "/../secret")


class TestProxmoxTasks(unittest.TestCase):
    def test_completed_task(self):
        from unittest.mock import Mock
        api = Mock()
        api.request.side_effect = [
            {"status": "running"}, {"status": "stopped", "exitstatus": "OK"}
        ]
        with patch("core.time.sleep", return_value=None):
            result = wait_for_task(
                api, "pve1", "UPID:pve1:000001:000002:000003:resize:120:root@pam:"
            )
        self.assertEqual(result["exitstatus"], "OK")
        self.assertEqual(api.request.call_count, 2)

    def test_failed_task(self):
        from unittest.mock import Mock
        api = Mock()
        api.request.return_value = {"status": "stopped", "exitstatus": "TASK ERROR"}
        with self.assertRaisesRegex(ProxmoxError, "failed"):
            wait_for_task(api, "pve1", "UPID:pve1:1:2:3:resize:120:root@pam:")

    def test_synchronous_response(self):
        self.assertIsNone(wait_for_task(None, "pve1", None))



if __name__ == "__main__":
    unittest.main()
