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


if __name__ == "__main__":
    unittest.main()
