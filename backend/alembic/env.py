from logging.config import fileConfig
import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import DATABASE_URL
from app.db.base import Base
from app.modules.agreements import models as agreement_models
from app.modules.extraction import models as extraction_models
from app.modules.obligations import models as obligation_models
from app.modules.review import models as review_models
from app.modules.monitoring import models as monitoring_models
from app.modules.amendments import models as amendments_models
from app.modules.audit import models as audit_models

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
database_url = os.getenv("DATABASE_URL", DATABASE_URL)
if database_url:
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    try:
        with connectable.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
