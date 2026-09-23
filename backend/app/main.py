import os
import time
import json
import psutil
import pyroscope
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST

from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource

from .database import init_db
from .auth import hash_password
from .oidc import router as oidc_router
from .routers import auth_router, admin_router, infra_router

app = FastAPI(title="Backend ABM - Alert Management")

# Directorios base para archivos estáticos y plantillas basados en la ubicación del script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.abspath(os.path.join(BASE_DIR, "../frontend"))
MEDIA_DIR = os.getenv("MEDIA_DIR", os.path.abspath(os.path.join(BASE_DIR, "../media")))

# Montaje de archivos estáticos y multimedia con rutas absolutas seguras
app.mount("/js", StaticFiles(directory=os.path.join(FRONTEND_DIR, "js")), name="js")
app.mount("/css", StaticFiles(directory=os.path.join(FRONTEND_DIR, "css")), name="css")

# Asegurar que el directorio media exista en el host/contenedor
os.makedirs(MEDIA_DIR, exist_ok=True)
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")

SERVICE_NAME = "anomalia_system"
AUDIT_LOGS_ENDPOINT = os.getenv("AUDIT_LOGS_ENDPOINT")
PYROSCOPE_SERVER_ADDRESS = os.getenv("PYROSCOPE_SERVER_ADDRESS", "http://localhost:4040")

# 1. Configuración de Pyroscope para Profiling Continuo
try:
    pyroscope.configure(
        application_name=SERVICE_NAME,
        server_address=PYROSCOPE_SERVER_ADDRESS,
        tags={"env": os.getenv("ENVIRONMENT", "production")},
    )
except Exception as e:
    print(f"Aviso: No se pudo iniciar el cliente de Pyroscope: {e}")

# 2. Inicializar base de datos pasando la función de hash
init_db(hash_password)

# 3. Instrumentar FastAPI automáticamente con OpenTelemetry
FastAPIInstrumentor.instrument_app(app)

# 4. Incluir routers de la API
app.include_router(oidc_router)
app.include_router(auth_router.router)
app.include_router(admin_router.router)
app.include_router(infra_router.router)

# Ruta puente para solucionar el error 404 detectado en /api/v1/tenants/my-tenants
@app.get("/api/v1/tenants/my-tenants")
def get_my_tenants_alias(request: Request):
    # Redirige internamente o reutiliza la lógica del admin_router para listar tenants
    from .database import SessionLocal
    from sqlalchemy import text
    db = SessionLocal()
    try:
        # Intenta consultar la tabla tenants si existe, o retorna lista vacía/estructura estándar
        result = db.execute(text("SELECT id, name, type, environment, port, description FROM tenants")).fetchall()
        tenants_list = [{"id": r[0], "name": r[1], "type": r[2], "environment": r[3], "port": r[4], "description": r[5]} for r in result]
        return {"tenants": tenants_list}
    except Exception:
        return {"tenants": []}
    finally:
        db.close()

# 5. Configuración de plantillas Jinja2 apuntando a la carpeta frontend externa
templates = Jinja2Templates(directory=FRONTEND_DIR)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body": str(exc.body)},
    )

@app.get("/metrics")
def metrics_endpoint_prometheus():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get("/healthz")
def healthcheck():
    return {"status": "healthy", "service": SERVICE_NAME}

@app.get("/", response_class=HTMLResponse)
def serve_index(request: Request):
    return templates.TemplateResponse(request, "index.html")

@app.get("/login", response_class=HTMLResponse)
def serve_login(request: Request):
    return templates.TemplateResponse(request, "login.html")

@app.get("/admin", response_class=HTMLResponse)
def serve_admin(request: Request):
    return templates.TemplateResponse(request, "admin.html")
