import os
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

# Retrieve Database URL from environment
DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    # Default fallback to a local PostgreSQL instance for development
    DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/attendance"
    print("WARNING: DATABASE_URL environment variable is not set. Falling back to local development database.")

# Standardize prefix for SQLAlchemy 1.4+ compatibility (Supabase/Heroku compatibility)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Connection pooling optimization for cloud-hosted Postgres (Supabase)
# Prevents exhausting database connection limits while avoiding stale connections
engine = create_engine(
    DATABASE_URL,
    pool_size=10,            # Keep up to 10 persistent connections in the pool
    max_overflow=20,         # Allow up to 20 additional concurrent connections under load
    pool_recycle=1800,       # Recycle connections every 30 minutes to prevent stale sockets
    pool_timeout=30,         # Wait 30 seconds before throwing connection timeout errors
    pool_pre_ping=True       # Ping database to verify connection health before queries
)

# Session factory for generating db sessions
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

def get_db() -> Generator[Session, None, None]:
    """
    Dependency helper to acquire a database session and guarantee its cleanup.
    Suitable for use with FastAPI Depends.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
