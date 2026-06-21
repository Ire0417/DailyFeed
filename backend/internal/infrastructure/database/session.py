from contextlib import contextmanager
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from internal.config.settings import settings
from internal.infrastructure.monitoring.logger import get_logger

logger = get_logger("db_session")

_engine = None
SessionLocal = None
_using_sqlite_fallback = False


def _try_connect(engine, test_sql: str = "SELECT 1") -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text(test_sql))
        return True
    except Exception:
        return False


def _init_engine():
    global _engine, SessionLocal, _using_sqlite_fallback
    if _engine is not None:
        return

    # 先尝试用户配置的数据库
    url = settings.database_url
    # 若无 psycopg2，直接走 SQLite
    if "postgresql" in url:
        try:
            import psycopg2  # noqa: F401
        except ImportError:
            logger.info("psycopg2 not installed; skipping PostgreSQL, using SQLite fallback")
            url = None

    if url is not None:
        try:
            engine = create_engine(
                url,
                pool_size=getattr(settings, "database_pool_size", 20),
                max_overflow=getattr(settings, "database_max_overflow", 40),
                pool_pre_ping=True,
                pool_recycle=3600,
                echo=settings.debug,
            )
            if _try_connect(engine):
                _engine = engine
                SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
                logger.info("connected to database at %s", url)
                return
        except Exception as exc:
            logger.warning("primary database connect failed exc=%s", exc)

    # 失败 → 回退到 SQLite
    sqlite_url = "sqlite:///./dailyfeed.db"
    logger.info("falling back to SQLite at %s", sqlite_url)
    sqlite_engine = create_engine(
        sqlite_url,
        connect_args={"check_same_thread": False},
        echo=settings.debug,
    )
    _engine = sqlite_engine
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    _using_sqlite_fallback = True


def get_engine():
    _init_engine()
    return _engine


def is_using_sqlite() -> bool:
    _init_engine()
    return _using_sqlite_fallback


@contextmanager
def get_session() -> Session:
    _init_engine()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_db():
    _init_engine()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from internal.infrastructure.database.models import Base
    _init_engine()
    # SQLite 下要显式创建表
    Base.metadata.create_all(bind=_engine)
    logger.info("database tables initialized")
