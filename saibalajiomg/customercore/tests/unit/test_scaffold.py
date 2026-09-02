import os

def test_environment_vars():
    assert os.environ.get("APP_ENV") == "test"

def test_imports_work():
    import fastapi
    assert fastapi.__version__ is not None
