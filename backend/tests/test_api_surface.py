import os
import unittest

os.environ.setdefault("JWT_SECRET", "unit-test-only-not-a-real-secret")

from fastapi.testclient import TestClient

from app.auth import create_token
from app.main import app


class ApiSurfaceTests(unittest.TestCase):
    """Guards the HTTP surface the mobile client connects to.

    ``TestClient`` is used without its context manager on purpose: these checks
    must hold before any database exists, so the application lifespan (which
    creates the schema and starts workers) is never entered.
    """

    def setUp(self):
        self.client = TestClient(app)

    def test_health_requires_no_authentication(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["service"], "tradeguard-api")

    def test_unknown_path_is_not_reported_as_a_valid_api_response(self):
        self.assertEqual(self.client.get("/v1/does-not-exist").status_code, 404)

    def test_protected_routes_reject_anonymous_callers(self):
        for path in (
            "/v1/account",
            "/v1/bot",
            "/v1/ctrader/oauth/status",
            "/v1/ctrader/account",
            "/v1/journal",
            "/v1/notifications/status",
            "/v1/markets",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()["detail"], "Authentication required")

    def test_tampered_token_signature_is_rejected_without_reading_the_database(self):
        token = create_token("00000000-0000-0000-0000-000000000000")
        header, payload, signature = token.split(".")
        tampered = ".".join((header, payload, signature[:-2] + "aa"))
        response = self.client.get("/v1/account", headers={"Authorization": f"Bearer {tampered}"})
        self.assertEqual(response.status_code, 401)
        self.assertIn("Invalid or expired", response.json()["detail"])

    def test_non_bearer_authorization_is_rejected(self):
        response = self.client.get("/v1/account", headers={"Authorization": "Basic abc"})
        self.assertEqual(response.status_code, 401)

    def test_cors_preflight_allows_browser_and_expo_web_clients(self):
        response = self.client.options(
            "/v1/account",
            headers={
                "Origin": "https://tradeguard.example",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("access-control-allow-origin"), "*")
        self.assertIn("authorization", response.headers.get("access-control-allow-headers", "").lower())

    def test_cors_headers_are_present_on_actual_responses(self):
        response = self.client.get("/health", headers={"Origin": "https://tradeguard.example"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("access-control-allow-origin"), "*")

    def test_market_stream_websocket_route_is_registered(self):
        paths = {getattr(route, "path", "") for route in app.routes}
        self.assertIn("/v1/ctrader/market-stream", paths)

    def test_oauth_callback_page_links_back_into_the_app(self):
        from app.ctrader_oauth_api import oauth_callback_page

        html = oauth_callback_page()
        self.assertIn("tradeguard://", html)
        self.assertIn("OPEN TRADEGUARD", html)
        # The redirect lands in a phone browser; it must never look like a
        # successful trade or imply that automated execution is enabled.
        self.assertNotIn("execution enabled", html.lower())
