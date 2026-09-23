import os
import time
import urllib.parse as urlparse
import psycopg2
from sqlalchemy.ext.declarative import declarative_base

# Declaración única de Base para SQLAlchemy
Base = declarative_base()

def get_db_connection():
    database_url = os.getenv("DATABASE_URL")
    retries = 5
    while retries > 0:
        try:
            if database_url:
                parsed_url = urlparse.urlparse(database_url)
                return psycopg2.connect(
                    dbname=parsed_url.path[1:],
                    user=parsed_url.username,
                    password=parsed_url.password,
                    host=parsed_url.hostname,
                    port=parsed_url.port
                )
            return psycopg2.connect(
                host=os.getenv("DB_HOST", "postgres"),
                database=os.getenv("DB_NAME", "anomal_db"),
                user=os.getenv("DB_USER", "anomal_user"),
                password=os.getenv("DB_PASSWORD", "anomal_password")
            )
        except psycopg2.OperationalError as e:
            retries -= 1
            if retries == 0:
                raise e
            time.sleep(2)

def get_db():
    """Dependencia de FastAPI para obtener una sesión/conexión de base de datos."""
    conn = get_db_connection()
    try:
        yield conn
    finally:
        conn.close()

def init_db(hash_password_func):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(150) UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                theme VARCHAR(50) DEFAULT 'theme-enterprise-blue',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS roles (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) UNIQUE NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                id SERIAL PRIMARY KEY,
                code VARCHAR(100) UNIQUE NOT NULL,
                name VARCHAR(100) NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tenants (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) UNIQUE NOT NULL,
                type VARCHAR(50) DEFAULT 'metrics',
                account_id INTEGER NOT NULL,
                project_id INTEGER NOT NULL,
                environment VARCHAR(50),
                port INTEGER DEFAULT 8427,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_roles (
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                role_id INTEGER REFERENCES roles(id) ON DELETE CASCADE,
                PRIMARY KEY (user_id, role_id)
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS role_profiles (
                role_id INTEGER REFERENCES roles(id) ON DELETE CASCADE,
                profile_id INTEGER REFERENCES profiles(id) ON DELETE CASCADE,
                PRIMARY KEY (role_id, profile_id)
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_tenants (
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
                PRIMARY KEY (user_id, tenant_id)
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS role_tenants (
                role_id INTEGER REFERENCES roles(id) ON DELETE CASCADE,
                tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
                PRIMARY KEY (role_id, tenant_id)
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS oidc_providers (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) UNIQUE NOT NULL,
                issuer_url TEXT NOT NULL,
                client_id VARCHAR(255) NOT NULL,
                client_secret TEXT,
                redirect_uri TEXT,
                is_active BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS infrastructure_nodes (
                id SERIAL PRIMARY KEY,
                hostname VARCHAR(150) UNIQUE NOT NULL,
                ip_address VARCHAR(50) NOT NULL,
                service_ip VARCHAR(50),
                component_type VARCHAR(50) DEFAULT 'auth',
                port INTEGER DEFAULT 8427,
                status VARCHAR(50) DEFAULT 'operational',
                description TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cursor.execute("SELECT COUNT(*) FROM users;")
        if cursor.fetchone()[0] == 0:
            default_pass = hash_password_func("admin123")
            cursor.execute("""
                INSERT INTO users (username, password_hash, is_active, theme)
                VALUES (%s, %s, TRUE, 'theme-enterprise-blue')
            """, ("admin@anomalia", default_pass))

        cursor.execute("""
            INSERT INTO roles (name, description) VALUES 
            ('admin', 'Administrador Global'),
            ('viewer', 'Visualizador de Alertas'),
            ('auditor', 'Auditor de Seguridad'),
            ('tenant_manager', 'Gestor de Tenants'),
            ('infra_manager', 'Gestor de Infraestructura'),
            ('user_manager', 'Gestor de Usuarios'),
            ('role_manager', 'Gestor de Roles')
            ON CONFLICT (name) DO NOTHING;
        """)

        cursor.execute("""
            INSERT INTO profiles (code, name, description) VALUES 
            ('admin', 'Admin Profile', 'Control absoluto del sistema'),
            ('users_manager', 'Users Manager Profile', 'Gestión de cuentas y usuarios'),
            ('roles_manager', 'Roles Manager Profile', 'Gestión de roles de seguridad'),
            ('profile_manager', 'Profile Manager Profile', 'Gestión de perfiles de acceso'),
            ('access_metrics', 'Metrics Profile', 'Perfil para recolección y consulta de métricas'),
            ('access_logs', 'Logs Profile', 'Perfil para auditoría y logs centralizados'),
            ('access_traces', 'Traces Profile', 'Perfil para trazabilidad distribuida'),
            ('access_Continuous_Profiling', 'Profiling Profile', 'Perfil para profiling continuo'),
            ('access_alerts', 'Alerts Profile', 'Perfil de visualización de alertas'),
            ('tenants_manager', 'Tenants Manager Profile', 'Gestión de tenants y namespaces'),
            ('infra_manager', 'Infra Management Profile', 'Gestión de nodos de infraestructura y ruteadores')
            ON CONFLICT (code) DO NOTHING;
        """)

        cursor.execute("SELECT COUNT(*) FROM user_roles;")
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO user_roles (user_id, role_id) SELECT 1, id FROM roles WHERE name = 'admin' ON CONFLICT DO NOTHING;")

        cursor.execute("SELECT COUNT(*) FROM tenants;")
        if cursor.fetchone()[0] == 0:
            cursor.execute("""
                INSERT INTO tenants (name, type, account_id, project_id, environment, port, description) VALUES 
                ('METRICS', 'metrics', 0, 0, 'default', 8400, 'Tenant para métricas de infraestructura (VictoriaMetrics - vminsert)'),
                ('TRACES', 'traces', 0, 1, 'default', 8490, 'Tenant para trazas distribuidas OTLP (VictoriaTraces - vtinsert)'),
                ('PROFILES', 'profiles', 0, 2, 'default', 4040, 'Tenant de perfilado continuo vía Pyroscope'),
                ('AUDIT_LOGS', 'logs', 0, 3, 'default', 8480, 'Tenant para logs de auditoría (VictoriaLogs - vlinsert)')
                ON CONFLICT (name) DO NOTHING;
            """)

        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error inicializando base de datos: {e}")
    finally:
        cursor.close()
        conn.close()
