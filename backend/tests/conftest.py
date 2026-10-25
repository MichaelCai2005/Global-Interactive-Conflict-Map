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
# Tests screen GDELT with the word rules, and hand in a model where they test one.
os.environ["GDELT_HEADLINE_MODEL"] = "false"

from app.db import get_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def engine():
    engine = create_engine(TEST_DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(
            text(
                "DROP TABLE IF EXISTS saved_searches, user_sessions, users, board_images, board_links, board_nodes, boards, observations, risk_scores, risk_countries, cell_month_features, country_indicators, analyst_tasks, watch_items, rejected_records, event_sources, gdelt_ids, event_links, events, ingest_runs, alembic_version CASCADE"
            )
        )
        conn.execute(
            text("DROP FUNCTION IF EXISTS board_place_key(text), board_actor_key(text) CASCADE")
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
                "TRUNCATE saved_searches, user_sessions, users, board_images, board_links, board_nodes, boards, observations, risk_scores, risk_countries, cell_month_features, country_indicators, analyst_tasks, watch_items, rejected_records, event_links, events, ingest_runs RESTART IDENTITY CASCADE"
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
