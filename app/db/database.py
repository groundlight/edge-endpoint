import logging
from logging.handlers import RotatingFileHandler

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.file_paths import DATABASE_ORM_LOG_FILE, DATABASE_ORM_LOG_FILE_SIZE

logger = logging.getLogger(__name__)
Base = declarative_base()

SQLALCHEMY_DATABASE_URL = "sqlite:///./sql_app.db"
# SQLALCHEMY_DATABASE_URL = "postgresql://user:password@postgresserver/db"

# TODO: use Alembic for migrations
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_database_engine():
    """Get the database engine. Easily mocked for testing."""
    db_url = f"sqlite:///{DATABASE_FILEPATH}"
    return create_engine(db_url)


def get_db():
    """Dependency injection of db sessions"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _setup_logging(level) -> None:
    """
    Configures logging for SQLAlchemy. This is just so we can declutter the logs.
    Logs from the database will be written to the file specified by `DATABASE_ORM_LOG_FILE`.
    :param level: The logging level.
    """
    # configure SQLAlchemy logging
    sqlalchemy_logger = logging.getLogger("sqlalchemy.engine")
    sqlalchemy_logger.setLevel(level)

    file_handler = RotatingFileHandler(DATABASE_ORM_LOG_FILE, maxBytes=DATABASE_ORM_LOG_FILE_SIZE, backupCount=1)
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    file_handler.setFormatter(formatter)
    sqlalchemy_logger.addHandler(file_handler)

    # Ensure that other handlers do not propagate here
    sqlalchemy_logger.propagate = False


_setup_logging(logging.INFO)
