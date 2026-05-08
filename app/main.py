from fastapi import FastAPI, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from app.database import Base, SessionLocal, engine
from app import models
from app.models import Asistencia
from app.routers import asistencias, auth, comisiones, inventario, inventarioTelefonos, traspasos, kardex, usuarios, ventas, nomina
from app.routers import dashboard, direccion
from . import schemas
from fastapi.middleware.cors import CORSMiddleware

Base.metadata.create_all(bind=engine)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://atosistema.vercel.app",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ALLOWED_ORIGINS = [
    "https://atosistema.vercel.app",
    "http://localhost:3000",
]

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    origin = request.headers.get("origin", "")
    headers = {}
    if origin in ALLOWED_ORIGINS:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
        headers=headers,
    )

# Incluir los routers
app.include_router(auth.router, prefix="/auth", tags=["Autenticación"])
app.include_router(usuarios.router, prefix="/registro", tags=["Usuarios"])
app.include_router(asistencias.router, prefix="/asistencias", tags=["Asistencias"])
app.include_router(ventas.router, prefix="/ventas", tags=["Ventas"])
app.include_router(comisiones.router, prefix="/comisiones", tags=["Comisiones"])
app.include_router(traspasos.router, prefix="/traspasos", tags=["Traspasos"])
app.include_router(inventario.router, prefix="/inventario", tags=["Inventario"])
app.include_router(inventarioTelefonos.router, prefix="/inventario_telefonos", tags=["Inventario Telefonos"])
app.include_router(nomina.router, prefix="/nomina", tags=["Nomina"])
app.include_router(kardex.router, prefix="/kardex", tags=["Kardex"])
app.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])
app.include_router(direccion.router, prefix="/direccion", tags=["Dirección"])






