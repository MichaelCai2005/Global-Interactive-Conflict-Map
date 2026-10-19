import os

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from alembic import command

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://conflict:conflict@localhost:5432/conflict_test"
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from app.db import get_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def engine():
    engine = create_engine(TEST_DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(
            text(
                "DROP TABLE IF EXISTS rejected_records, event_links, events, ingest_runs, alembic_version CASCADE"
            )
        )
    config = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    config.set_main_option(
        "script_location", os.path.join(os.path.dirname(__file__), "..", "alembic")
    )
    config.attributes["database_url"] = TEST_DATABASE_URL
    command.upgrade(config, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine):
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE rejected_records, event_links, events, ingest_runs RESTART IDENTITY CASCADE"
            )
        )
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        yield session


@pytest.fixture
def client(session):
    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
