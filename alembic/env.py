import sys
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# 1. Add your project root to the system path so Alembic can find the 'app' folder
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# 2. Import your FastAPI settings and your Database Base
from app.core.config import settings
from app.db.models import Base

# this is the Alembic Config object
config = context.config

# 3. Force Alembic to use the DATABASE_URL from your .env file!
config.set_main_option("sqlalchemy.url", settings.database_url)

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 4. Point target_metadata to your models
target_metadata = Base.metadata

# ... (Leave the rest of the run_migrations_offline and run_migrations_online functions exactly as they are)
