
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv
import os


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

ldotenv_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=ldotenv_path)

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("No se encontró la variable DATABASE_URL en el .env")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

print(f"DATABASE_URL: {DATABASE_URL}")