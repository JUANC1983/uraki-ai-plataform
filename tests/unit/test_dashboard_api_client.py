import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[2] / "dashboard" / "services" / "api_client.py"
SPEC = importlib.util.spec_from_file_location("uraki_dashboard_api_client", MODULE_PATH)
api_client = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(api_client)


class DashboardAPIClientTests(unittest.TestCase):
    def setUp(self):
        self.original_base = api_client.API_BASE
        api_client.API_BASE = "http://api:8000"

    def tearDown(self):
        api_client.API_BASE = self.original_base

    def test_health_and_readiness_bypass_api_prefix(self):
        client = api_client.APIClient()

        self.assertEqual(client._url("/health"), "http://api:8000/health")
        self.assertEqual(client._url("/ready"), "http://api:8000/ready")
        self.assertEqual(client._url("/cases"), "http://api:8000/api/v1/cases")

    def test_unconfigured_backend_blocks_without_fabricating_data(self):
        api_client.API_BASE = ""
        client = api_client.APIClient()

        with patch.object(api_client.requests, "request") as request:
            result = client.get("/cases")

        self.assertFalse(result.ok)
        self.assertIsNone(result.data)
        self.assertEqual(result.status_code, 503)
        self.assertIn("URAKI_API_URL", result.error)
        request.assert_not_called()

    def test_post_is_not_retried_on_transient_response(self):
        response = SimpleNamespace(status_code=503)
        client = api_client.APIClient()

        with patch.object(api_client.requests, "request", return_value=response) as request:
            result = client._request_with_retry("POST", client._url("/cases"), json={})

        self.assertIs(result, response)
        self.assertEqual(request.call_count, 1)

    def test_get_retries_transient_response(self):
        unavailable = SimpleNamespace(status_code=503)
        available = SimpleNamespace(status_code=200)
        client = api_client.APIClient()

        with patch.object(
            api_client.requests,
            "request",
            side_effect=[unavailable, available],
        ) as request, patch.object(api_client.time, "sleep"):
            result = client._request_with_retry("GET", client._url("/health"))

        self.assertIs(result, available)
        self.assertEqual(request.call_count, 2)


if __name__ == "__main__":
    unittest.main()
