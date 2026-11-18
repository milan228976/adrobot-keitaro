import os

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import create_engine, pool

from app.storage import Base


load_dotenv()
database_url = os.getenv("DATABASE_URL", "sqlite:///./adrobot.db")

if context.is_offline_mode():
    context.configure(url=database_url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(database_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
