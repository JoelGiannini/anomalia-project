import os
import time
import json
import psutil
import pyroscope
import httpx
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

# --- CONFIGURACIÓN DE AUDITORÍA A VICTORIALOGS (LOKI API) ---
def send_audit_log(username: str, action: str, details: str, ip_address: str, status: str = "SUCCESS"):
    """Envía un evento de auditoría estructurado y legible a VictoriaLogs."""
    if not AUDIT_LOGS_ENDPOINT:
        return  
    
    timestamp_ns = str(int(time.time() * 1e9))
    human_readable_msg = f"Usuario [{username or 'anonymous'}] ejecutó [{action}] - Detalle: {details} - IP: {ip_address} - Estado: {status}"
    
    log_payload = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "_msg": human_readable_msg,
        "username": username or "anonymous",
        "action": action,
        "details": details,
        "ip_address": ip_address,
        "status": status
    }
    
    loki_body = {
        "streams": [
            {
                "stream": {
                    "service": SERVICE_NAME,
                    "type": "AUDIT",
                    "username": username or "anonymous",
                    "action": action,
                    "status": status
                },
                "values": [
                    [timestamp_ns, json.dumps(log_payload)]
                ]
            }
        ]
    }
    
    try:
        headers = {"Content-Type": "application/json"}
        httpx.post(AUDIT_LOGS_ENDPOINT, json=loki_body, headers=headers, timeout=1.0)
    except Exception as e:
        print(f"Error al enviar log de auditoría a Loki: {e}")

# --- MIDDLEWARE DE AUDITORÍA AUTOMÁTICA DE ACTIVIDAD DE USUARIOS ---
@app.middleware("http")
async def audit_middleware(request: Request, call_next):
    start_time = time.time()
    client_ip = request.client.host if request.client else "unknown"
    
    username = "anonymous"
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        try:
            token = auth_header.split(" ")[1]
            import jwt
            decoded = jwt.decode(token, options={"verify_signature": False})
            username = decoded.get("sub", "unknown")
        except Exception:
            pass

    response = await call_next(request)
    duration_ms = round((time.time() - start_time) * 1000, 2)
    
    path = request.url.path
    method = request.method
    status_code = response.status_code

    try:
        current_span = trace.get_current_span()
        if current_span:
            current_span.set_attribute("enduser.id", username)
            current_span.set_attribute("http.client_ip", client_ip)
            current_span.set_attribute("app.action", f"{method} {path}")
    except Exception:
        pass

    if path.startswith("/api/v1/"):
        action = f"{method} {path}"
        details = f"Status: {status_code} | Duration: {duration_ms}ms"
        
        if "login" in path and status_code == 200:
            action = "USER_LOGIN"
            details = f"Inicio de sesión exitoso desde IP {client_ip}"
            
        send_audit_log(
            username=username,
            action=action,
            details=details,
            ip_address=client_ip,
            status="SUCCESS" if status_code < 400 else "ERROR"
        )
        
    return response

# 1. Configuración de Pyroscope para Profiling Continuo (CPU + Memoria)
try:
    pyroscope.configure(
        application_name=os.getenv("PYROSCOPE_APPLICATION_NAME", SERVICE_NAME),
        server_address=PYROSCOPE_SERVER_ADDRESS,
        tags={"environment": os.getenv("ENVIRONMENT", "production")},
        cpu_enabled=True,
        mem_enabled=True,
    )
    print(f"Pyroscope configurado correctamente (CPU + Memoria) para: {SERVICE_NAME}")
except Exception as e:
    print(f"Aviso: No se pudo iniciar el cliente de Pyroscope: {e}")

# --- CONFIGURACIÓN DE OPENTELEMETRY (TRACES & METRICS) ---
resource = Resource.create(attributes={"service.name": os.getenv("PYROSCOPE_APPLICATION_NAME", SERVICE_NAME)})

try:
    traces_endpoint = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    if traces_endpoint:
        tracer_provider = TracerProvider(resource=resource)
        span_processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=traces_endpoint))
        tracer_provider.add_span_processor(span_processor)
        trace.set_tracer_provider(tracer_provider)
except Exception as e:
    print(f"Advertencia: Error al configurar OpenTelemetry Traces: {e}")

try:
    metrics_endpoint = os.getenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT")
    if metrics_endpoint:
        metric_exporter = OTLPMetricExporter(endpoint=metrics_endpoint)
        metric_reader = PeriodicExportingMetricReader(metric_exporter, export_interval_millis=15000)
        meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
        metrics.set_meter_provider(meter_provider)
except Exception as e:
    print(f"Advertencia: Error al configurar OpenTelemetry Metrics: {e}")

# 2. Inicializar base de datos pasando la función de hash
init_db(hash_password)

# 3. Instrumentar FastAPI automáticamente con OpenTelemetry
try:
    FastAPIInstrumentor.instrument_app(app)
except Exception as e:
    print(f"Advertencia: No se pudo instrumentar FastAPI con OpenTelemetry: {e}")

# 4. Incluir routers de la API
app.include_router(oidc_router)
app.include_router(auth_router.router)
app.include_router(admin_router.router)
app.include_router(infra_router.router)

# Ruta puente para solucionar el error 404 detectado en /api/v1/tenants/my-tenants
@app.get("/api/v1/tenants/my-tenants")
def get_my_tenants_alias(request: Request):
    from .database import SessionLocal
    from sqlalchemy import text
    db = SessionLocal()
    try:
        result = db.execute(text("SELECT id, name, type, environment, port, description FROM tenants")).fetchall()
        tenants_list = [{"id": r[0], "name": r[1], "type": r[2], "environment": r[3], "port": r[4], "description": r[5]} for r in result]
        return {"tenants": tenants_list}
    except Exception:
        return {"tenants": []}
    finally:
        db.close()

# --- MÉTRICAS DE SISTEMA (ANOMALIA) ---
CPU_USAGE_GAUGE = Gauge('anomalia_system_cpu_usage_percent', 'Uso actual de CPU del sistema')
RAM_USAGE_GAUGE = Gauge('anomalia_system_ram_usage_percent', 'Uso actual de RAM del sistema')
HEALTH_STATUS_GAUGE = Gauge('anomalia_health_status', 'Estado de salud del servicio (1 = OK, 0 = Error)')

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
    try:
        CPU_USAGE_GAUGE.set(psutil.cpu_percent(interval=None))
        RAM_USAGE_GAUGE.set(psutil.virtual_memory().percent)
        HEALTH_STATUS_GAUGE.set(1)
    except Exception:
        HEALTH_STATUS_GAUGE.set(0)
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
