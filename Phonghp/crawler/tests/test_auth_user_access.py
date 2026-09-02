import importlib
import os
import sys
import unittest

from routes.auth import _get_user_value


class DummyUser:
    def __init__(self, **values):
        self._values = values

    def __getitem__(self, key):
        return self._values[key]

    def get(self, key, default=None):
        return self._values.get(key, default)


class AttributeUser:
    def __init__(self, **values):
        for key, value in values.items():
            setattr(self, key, value)


class AuthUserAccessTests(unittest.TestCase):
    def test_get_user_value_supports_dict_like_objects(self):
        user = DummyUser(email="test@example.com", password_hash="hash", name="Test")

        self.assertEqual(_get_user_value(user, "email"), "test@example.com")
        self.assertEqual(_get_user_value(user, "password_hash"), "hash")
        self.assertEqual(_get_user_value(user, "name"), "Test")
        self.assertEqual(_get_user_value(user, "missing", "fallback"), "fallback")

    def test_get_user_value_supports_attribute_based_objects(self):
        user = AttributeUser(email="attr@example.com", password_hash="attr-hash", name="Attr")

        self.assertEqual(_get_user_value(user, "email"), "attr@example.com")
        self.assertEqual(_get_user_value(user, "password_hash"), "attr-hash")
        self.assertEqual(_get_user_value(user, "name"), "Attr")

    def test_auth_requires_explicit_secret_in_production(self):
        original_env = os.environ.copy()
        try:
            for key in ("APP_ENV", "APP_SECRET", "JWT_SECRET", "JWT_ALGO"):
                os.environ.pop(key, None)
            os.environ["APP_ENV"] = "production"
            os.environ["DATABASE_URL"] = "postgresql://user:pass@localhost:5432/test"
            sys.modules.pop("auth", None)

            with self.assertRaisesRegex(RuntimeError, "APP_SECRET|JWT_SECRET"):
                importlib.import_module("auth")
        finally:
            os.environ.clear()
            os.environ.update(original_env)
            sys.modules.pop("auth", None)


if __name__ == "__main__":
    unittest.main()
