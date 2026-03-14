from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

# Import models so Alembic can detect them
from app.models.models import Customer, Invoice, Payment, SyncLog  # noqa: F401
from app.db.session import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    """
    Use DATABASE_URL_SYNC from .env if available.
    Falls back to alembic.ini sqlalchemy.url.
    DATABASE_URL_SYNC uses psycopg2 (sync driver) — required for Alembic.
    DATABASE_URL uses asyncpg (async driver) — used by the app at runtime.
    """
    try:
        from app.core.config import settings
        url = settings.DATABASE_URL_SYNC
        if url and "YOUR_POSTGRES_PASSWORD" not in url:
            return url
    except Exception:
        pass
    return config.get_main_option("sqlalchemy.url")


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Convert asyncpg URL to psycopg2 for Alembic (sync driver required)
    url = get_url()
    url = url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    url = url.replace("postgresql+aasyncpg://", "postgresql+psycopg2://")

    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = url

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
