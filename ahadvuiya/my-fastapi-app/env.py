from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context

# প্রজেক্টের সেটিংস এবং মডেলের Base ইমপোর্ট করা
from app.config.settings import settings
from app.models.user import Base  # সব মডেল এই Base থেকে ইনহেরিট করেছে

# Alembic কনফিগ অবজেক্ট
config = context.config

# ডাটাবেজ URL settings.py থেকে ডায়নামিকভাবে সেট করা
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# মাইগ্রেশনের জন্য মডেলের মেটাডেটা যুক্ত করা
target_metadata = Base.metadata

def run_migrations_offline() -> None:
    """অফলাইন মোডে মাইগ্রেশন চালানোর ফাংশন"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    """অনলাইন মোডে (লাইভ ডাটাবেজ কানেকশন সহ) মাইগ্রেশন চালানোর ফাংশন"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with context.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
