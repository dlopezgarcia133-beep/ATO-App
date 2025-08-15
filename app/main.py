from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from app.database import Base, SessionLocal, engine
from app import models
from app.models import Asistencia
from app.routers import asistencias, auth, comisiones, inventario, inventarioTelefonos, traspasos, usuarios, ventas
from . import schemas
from fastapi.middleware.cors import CORSMiddleware

Base.metadata.create_all(bind=engine)

app = FastAPI()

# Incluir los routers
app.include_router(auth.router, prefix="/auth", tags=["Autenticación"])
app.include_router(usuarios.router, prefix="/registro", tags=["Usuarios"])
app.include_router(asistencias.router, prefix="/asistencias", tags=["Asistencias"])
app.include_router(ventas.router, prefix="/ventas", tags=["Ventas"])
app.include_router(comisiones.router, prefix="/comisiones", tags=["Comisiones"])
app.include_router(traspasos.router, prefix="/traspasos", tags=["Traspasos"])
app.include_router(inventario.router, prefix="/inventario", tags=["Inventario"])
app.include_router(inventarioTelefonos.router, prefix="/inventario_telefonos", tags=["Inventario Telefonos"])


app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://atosistema.vercel.app"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)






