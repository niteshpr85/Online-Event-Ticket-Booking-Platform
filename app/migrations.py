from sqlalchemy.engine import Engine


def run_migrations(engine: Engine) -> None:
    with engine.begin() as conn:
        users_exists = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
        ).fetchone()
        if not users_exists:
            return

        columns = conn.exec_driver_sql("PRAGMA table_info(users)").fetchall()
        column_names = {row[1] for row in columns}
        if "password_hash" not in column_names:
            conn.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN password_hash VARCHAR(255) NOT NULL DEFAULT ''"
            )
