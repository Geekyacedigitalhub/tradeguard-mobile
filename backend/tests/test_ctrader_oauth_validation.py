import unittest

from app.ctrader_oauth_validation import validate_token_response


class CTraderOAuthTokenValidationTests(unittest.TestCase):
    def test_accepts_valid_tokens_and_default_lifetime(self):
        access, refresh, lifetime = validate_token_response({
            "accessToken": "access-value",
            "refreshToken": "refresh-value",
        })
        self.assertEqual(access, "access-value")
        self.assertEqual(refresh, "refresh-value")
        self.assertEqual(lifetime, 2628000)

    def test_strips_surrounding_token_whitespace(self):
        self.assertEqual(
            validate_token_response({
                "accessToken": "  access-value\n",
                "refreshToken": "\trefresh-value  ",
                "expiresIn": 3600,
            }),
            ("access-value", "refresh-value", 3600),
        )

    def test_accepts_positive_integer_lifetime(self):
        self.assertEqual(
            validate_token_response({
                "accessToken": "access",
                "refreshToken": "refresh",
                "expiresIn": 3600,
            }),
            ("access", "refresh", 3600),
        )

    def test_rejects_non_object_response(self):
        for value in (None, [], "token"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "invalid response"):
                validate_token_response(value)

    def test_rejects_missing_or_blank_tokens(self):
        invalid = [
            {},
            {"accessToken": "access"},
            {"accessToken": " ", "refreshToken": "refresh"},
            {"accessToken": "access", "refreshToken": ""},
            {"accessToken": 123, "refreshToken": "refresh"},
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "incomplete tokens"):
                validate_token_response(value)

    def test_rejects_invalid_lifetime(self):
        for lifetime in (0, -1, True, False, "3600", 3.5, None):
            with self.subTest(lifetime=lifetime), self.assertRaisesRegex(ValueError, "invalid token lifetime"):
                validate_token_response({
                    "accessToken": "access",
                    "refreshToken": "refresh",
                    "expiresIn": lifetime,
                })



class CTraderAccessTokenFreshnessTests(unittest.TestCase):
    def setUp(self):
        from datetime import datetime, timezone
        self.now = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)

    def test_token_with_more_than_five_minutes_remaining_is_reused(self):
        from datetime import timedelta
        from app.ctrader_tokens import _access_token_is_fresh
        self.assertTrue(_access_token_is_fresh(self.now + timedelta(hours=2), now=self.now))

    def test_token_inside_five_minute_margin_is_refreshed(self):
        from datetime import timedelta
        from app.ctrader_tokens import _access_token_is_fresh
        self.assertFalse(_access_token_is_fresh(self.now + timedelta(minutes=4), now=self.now))

    def test_expired_or_missing_expiry_requires_refresh(self):
        from datetime import timedelta
        from app.ctrader_tokens import _access_token_is_fresh
        self.assertFalse(_access_token_is_fresh(None, now=self.now))
        self.assertFalse(_access_token_is_fresh(self.now - timedelta(seconds=1), now=self.now))

    def test_naive_database_timestamp_is_treated_as_utc(self):
        from datetime import timedelta
        from app.ctrader_tokens import _access_token_is_fresh
        self.assertTrue(_access_token_is_fresh(self.now.replace(tzinfo=None) + timedelta(hours=1), now=self.now))


if __name__ == "__main__":
    unittest.main()
