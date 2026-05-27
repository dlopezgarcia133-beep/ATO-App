from fastapi import FastAPI, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from app.database import Base, SessionLocal, engine
from app import models
from app.routers import asistencias, asistencia, auth, comisiones, inventario, inventarioTelefonos, traspasos, kardex, usuarios, ventas, nomina
from app.routers import dashboard, direccion, sueldos, caja_chica, estadisticas, admin_nomina
from fastapi.middleware.cors import CORSMiddleware
Base.metadata.create_all(bind=engine)
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def health_check():
    return {"status": "ok"}

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    origin = request.headers.get("origin", "")
    headers = {}
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
app.include_router(asistencia.router)
app.include_router(asistencia.modulos_router)
app.include_router(asistencia.promotores_router)
app.include_router(ventas.router, prefix="/ventas", tags=["Ventas"])
app.include_router(comisiones.router, prefix="/comisiones", tags=["Comisiones"])
app.include_router(traspasos.router, prefix="/traspasos", tags=["Traspasos"])
app.include_router(inventario.router, prefix="/inventario", tags=["Inventario"])
app.include_router(inventarioTelefonos.router, prefix="/inventario_telefonos", tags=["Inventario Telefonos"])
app.include_router(nomina.router, prefix="/nomina", tags=["Nomina"])
app.include_router(kardex.router, prefix="/kardex", tags=["Kardex"])
app.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])
app.include_router(direccion.router, prefix="/direccion", tags=["Dirección"])
app.include_router(sueldos.router, prefix="/sueldos", tags=["Sueldos"])
app.include_router(caja_chica.router, tags=["Caja Chica"])
app.include_router(estadisticas.router, prefix="/estadisticas", tags=["Estadísticas"])
app.include_router(admin_nomina.router, prefix="/admin", tags=["Admin"])
