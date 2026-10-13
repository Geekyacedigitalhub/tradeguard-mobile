import os
import unittest
from unittest.mock import Mock, patch

# Importing the router requires a signing secret; tests use a disposable value.
os.environ.setdefault("JWT_SECRET", "unit-test-only-not-a-real-secret")

from app.notifications_api import _push_to_token


class ExpoPushResponseTests(unittest.TestCase):
    def response(self, *, status_code=200, payload=None, text=""):
        response = Mock()
        response.status_code = status_code
        response.is_success = 200 <= status_code < 300
        response.text = text
        response.json.return_value = payload
        return response

    @patch("app.notifications_api.httpx.post")
    def test_acceptance_ticket_returns_provider_acceptance_not_device_delivery(self, post):
        post.return_value = self.response(
            payload={"data": {"status": "ok", "id": "ticket-123"}}
        )
        result = _push_to_token("ExponentPushToken[test]", "Title", "Body")
        self.assertEqual(result, {"ok": True, "status": "ok", "id": "ticket-123"})
        self.assertNotIn("delivery_confirmed", result)
        post.assert_called_once()

    @patch("app.notifications_api.httpx.post")
    def test_expo_ticket_error_is_reported_as_failure(self, post):
        post.return_value = self.response(
            payload={
                "data": {
                    "status": "error",
                    "message": "DeviceNotRegistered",
                    "details": {"error": "DeviceNotRegistered"},
                }
            }
        )
        result = _push_to_token("ExponentPushToken[test]", "Title", "Body")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "DeviceNotRegistered")

    @patch("app.notifications_api.httpx.post")
    def test_http_failure_is_reported(self, post):
        post.return_value = self.response(status_code=503, text="service unavailable")
        result = _push_to_token("ExponentPushToken[test]", "Title", "Body")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status_code"], 503)

    @patch("app.notifications_api.httpx.post")
    def test_non_json_success_response_is_rejected(self, post):
        response = self.response(payload=None)
        response.json.side_effect = ValueError("invalid JSON")
        post.return_value = response
        result = _push_to_token("ExponentPushToken[test]", "Title", "Body")
        self.assertFalse(result["ok"])
        self.assertIn("non-JSON", result["message"])

    @patch("app.notifications_api.httpx.post")
    def test_push_request_uses_expected_alert_channel(self, post):
        post.return_value = self.response(
            payload={"data": {"status": "ok", "id": "ticket-456"}}
        )
        _push_to_token("ExponentPushToken[test]", "Title", "Body", {"type": "test"})
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["json"]["channelId"], "tradeguard-alerts")
        self.assertEqual(kwargs["json"]["data"], {"type": "test"})
        self.assertEqual(kwargs["timeout"], 10)


if __name__ == "__main__":
    unittest.main()
