"""Link-analysis boards, recorded live observations, and name keys for matching articles.

A board holds nodes (an article, the places and groups it names, events, fires, flights)
and links between them. Every link stores the rule that suggested it, the evidence and a
confidence, and waits for a person to accept or reject it. See app.boards.

Live feeds such as military flights only show the present, so app.live records them into
`observations` to give boards a history of them.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-20
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

# Keep these two functions in step with place_key() and actor_key() in app/boards/names.py.
#
# UCDP writes the kind of place after its name in lower case ("Saraqib town", "Damascus
# city"), GDELT writes "Gaza, Israel (general), Israel". The suffix match is case-sensitive
# so names such as "Mexico City" keep their own last word.
PLACE_KEY = r"""
    CREATE FUNCTION board_place_key(name text) RETURNS text
    LANGUAGE sql IMMUTABLE PARALLEL SAFE RETURNS NULL ON NULL INPUT AS $$
        SELECT lower(btrim(regexp_replace(
            split_part(name, ',', 1),
            '\s+(town|city|village|governorate|province|district|area|region|camp|county|municipality|oblast|state|prefecture|subdistrict|neighbourhood|neighborhood)$',
            ''
        )))
    $$
"""
# ACLED and UCDP put a period of years after state actors: "Military Forces of Russia (2000-)".
ACTOR_KEY = r"""
    CREATE FUNCTION board_actor_key(name text) RETURNS text
    LANGUAGE sql IMMUTABLE PARALLEL SAFE RETURNS NULL ON NULL INPUT AS $$
        SELECT lower(btrim(regexp_replace(name, '\s*\([^)]*\)', '', 'g')))
    $$
"""


def upgrade() -> None:
    op.execute(PLACE_KEY)
    op.execute(ACTOR_KEY)
    op.execute("CREATE INDEX ix_events_place_key ON events (board_place_key(location_name))")
    op.execute("CREATE INDEX ix_events_actor1_key ON events (board_actor_key(actor1))")
    op.execute("CREATE INDEX ix_events_actor2_key ON events (board_actor_key(actor2))")
    op.execute("CREATE INDEX ix_events_source_url ON events (source_url)")

    op.execute("""
        CREATE TABLE observations (
            id bigserial PRIMARY KEY,
            source varchar(32) NOT NULL,
            kind varchar(16) NOT NULL CHECK (kind IN ('flight', 'fire', 'vessel')),
            external_id varchar(64) NOT NULL,
            observed_at timestamptz NOT NULL,
            latitude double precision NOT NULL CHECK (latitude BETWEEN -90 AND 90),
            longitude double precision NOT NULL CHECK (longitude BETWEEN -180 AND 180),
            label text,
            attributes jsonb NOT NULL DEFAULT '{}',
            geog geography(Point, 4326) GENERATED ALWAYS AS
                (ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography) STORED,
            recorded_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (source, external_id, observed_at)
        )
    """)
    op.execute("CREATE INDEX ix_observations_geog ON observations USING gist (geog)")
    op.execute("CREATE INDEX ix_observations_time ON observations (kind, observed_at)")

    op.execute("""
        CREATE TABLE boards (
            id serial PRIMARY KEY,
            title varchar(300) NOT NULL,
            -- What the board was started from: a pasted article, a topic, or nothing.
            origin varchar(16) NOT NULL CHECK (origin IN ('article', 'topic', 'manual')),
            prompt text NOT NULL DEFAULT '',
            source_url text,
            -- The day the story is about; rules look back from it.
            anchor_date date,
            extractor varchar(32),
            notes text NOT NULL DEFAULT '',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE board_nodes (
            id bigserial PRIMARY KEY,
            board_id integer NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
            -- Stable identity within a board, e.g. 'event:123', 'place:ukr:kherson'.
            key varchar(255) NOT NULL,
            kind varchar(16) NOT NULL CHECK (kind IN
                ('article', 'place', 'actor', 'claim', 'event', 'flight', 'fire', 'vessel', 'note')),
            label text NOT NULL,
            detail text NOT NULL DEFAULT '',
            event_id bigint REFERENCES events(id) ON DELETE SET NULL,
            latitude double precision CHECK (latitude BETWEEN -90 AND 90),
            longitude double precision CHECK (longitude BETWEEN -180 AND 180),
            -- GeoJSON geometry when the node is more than a point, e.g. a flight track.
            geometry jsonb,
            -- 'exact' when the source gives coordinates, 'derived' when the board placed it.
            geo_basis varchar(16),
            time_start timestamptz,
            time_end timestamptz,
            source_name text,
            source_url text,
            retrieved_at timestamptz,
            quote text,
            status varchar(16) NOT NULL DEFAULT 'suggested'
                CHECK (status IN ('suggested', 'accepted', 'rejected')),
            created_by varchar(16) NOT NULL CHECK (created_by IN ('user', 'rule', 'ai')),
            attributes jsonb NOT NULL DEFAULT '{}',
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (board_id, key)
        )
    """)
    op.execute("""
        CREATE TABLE board_links (
            id bigserial PRIMARY KEY,
            board_id integer NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
            from_node_id bigint NOT NULL REFERENCES board_nodes(id) ON DELETE CASCADE,
            to_node_id bigint NOT NULL REFERENCES board_nodes(id) ON DELETE CASCADE,
            rule varchar(32) NOT NULL,
            reason text NOT NULL,
            evidence jsonb NOT NULL DEFAULT '{}',
            confidence double precision NOT NULL CHECK (confidence BETWEEN 0 AND 1),
            status varchar(16) NOT NULL DEFAULT 'suggested'
                CHECK (status IN ('suggested', 'accepted', 'rejected')),
            created_by varchar(16) NOT NULL CHECK (created_by IN ('user', 'rule', 'ai')),
            created_at timestamptz NOT NULL DEFAULT now(),
            CHECK (from_node_id <> to_node_id),
            UNIQUE (board_id, from_node_id, to_node_id, rule)
        )
    """)
    op.execute("CREATE INDEX ix_board_nodes_board ON board_nodes (board_id)")
    op.execute("CREATE INDEX ix_board_links_board ON board_links (board_id)")


def downgrade() -> None:
    op.execute("DROP TABLE board_links, board_nodes, boards, observations")
    op.execute("DROP INDEX ix_events_place_key, ix_events_actor1_key, ix_events_actor2_key")
    op.execute("DROP INDEX ix_events_source_url")
    op.execute("DROP FUNCTION board_place_key(text), board_actor_key(text)")
