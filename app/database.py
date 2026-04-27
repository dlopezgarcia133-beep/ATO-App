from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv
import os

# Cargar dotenv primero
dotenv_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=dotenv_path)

# Obtener la URL
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("No se encontró la variable DATABASE_URL en el .env")

# Crear engine y session
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,          # <-- IMPORTANTE
    pool_size=15,
    max_overflow=20
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Ahora SÍ define get_db()
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
