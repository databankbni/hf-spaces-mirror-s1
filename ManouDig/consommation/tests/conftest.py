import pytest

from app.database import Base, engine


@pytest.fixture(scope="session", autouse=True)
def prepare_database():
    """
    Vérifie que les tables existent.
    Ne les supprime jamais.
    """
    Base.metadata.create_all(bind=engine)
    yield