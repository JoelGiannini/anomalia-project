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
                slug VARCHAR(100) UNIQUE,
                display_name VARCHAR(150),
                type VARCHAR(50) DEFAULT 'metrics',
                account_id INTEGER,
                project_id INTEGER,
                environment VARCHAR(50),
                port INTEGER DEFAULT 8427,
                description TEXT,
                instance_id INTEGER,
                vmalert_node_id INTEGER,
                vmalert_port INTEGER,
                has_alerts BOOLEAN DEFAULT FALSE,
                placement_mode VARCHAR(10) DEFAULT 'manual' CHECK (placement_mode IN ('manual','auto')),
                status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('provisioning','active','deleting','error','deleted_cleanup')),
                org_id_upper VARCHAR(100) UNIQUE,
                is_audit BOOLEAN DEFAULT FALSE,
                is_internal BOOLEAN DEFAULT FALSE,
                deleted_at TIMESTAMP,
                deletion_confirmed_at TIMESTAMP,
                deletion_confirmed_by INTEGER,
                deletion_challenge_id VARCHAR(64),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tenant_datasources (
                tenant_id INTEGER PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
                kind VARCHAR(50) NOT NULL,
                read_url TEXT NOT NULL,
                scoping VARCHAR(20) NOT NULL DEFAULT 'header',
                account_id INTEGER,
                project_id INTEGER,
                org_id VARCHAR(255),
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Sequences for auto-generating account_id and project_id
        cursor.execute("CREATE SEQUENCE IF NOT EXISTS tenant_account_id_seq START 1000;")
        cursor.execute("CREATE SEQUENCE IF NOT EXISTS tenant_project_id_seq START 1000;")

        cursor.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_tenants_account_project_active ON tenants(account_id, project_id) WHERE status='active' AND deleted_at IS NULL;""")

        # Tickets de un solo uso que authorizes el montaje de una consola de
        # telemetria (specs/010). tenant_id es NULL para el scope
        # 'alertmanager_global', la unica consola sin tenant (specs/011 5.7).
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ui_tickets (
                id SERIAL PRIMARY KEY,
                ticket VARCHAR(128) UNIQUE NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
                scope VARCHAR(32) NOT NULL DEFAULT 'metrics',
                expires_at TIMESTAMP NOT NULL,
                consumed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tenant_vmalert_instances (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER UNIQUE NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                instance_id INTEGER NOT NULL,
                port INTEGER NOT NULL,
                service VARCHAR(20) DEFAULT 'vmalert',
                unit_name VARCHAR(150) NOT NULL,
                rules_path VARCHAR(255) NOT NULL,
                rules_yaml TEXT,
                status VARCHAR(20) DEFAULT 'deployed' CHECK (status IN ('creating','deploying','deployed','error','stopped','undeployed')),
                health VARCHAR(10) DEFAULT 'unknown' CHECK (health IN ('ok','degraded','down','unknown')),
                last_deployed_at TIMESTAMP,
                enabled BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_tvi_instance_port UNIQUE (instance_id, port)
            );
        """)

        # Migración idempotente para BD preexistentes (spec 011/012): la regla de
        # alerta por tenant vive en la BD como fuente de verdad (rules_yaml).
        cursor.execute(
            "ALTER TABLE tenant_vmalert_instances ADD COLUMN IF NOT EXISTS rules_yaml TEXT"
        )
        # spec 011 §4.7: tenants de control interno (METRICS/TRACES/PROFILES/AUDIT_LOGS)
        # con reglas canónicas inmutables por API.
        cursor.execute(
            "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS is_internal BOOLEAN DEFAULT FALSE"
        )

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS port_mapping (
                id SERIAL PRIMARY KEY,
                instance_id INTEGER NOT NULL,
                tenant_id INTEGER REFERENCES tenants(id) ON DELETE SET NULL,
                service VARCHAR(20),
                host_port INTEGER NOT NULL,
                container_port INTEGER,
                proto VARCHAR(5) DEFAULT 'tcp',
                purpose VARCHAR(50),
                expires_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_deletions (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
                actor INTEGER REFERENCES users(id) ON DELETE SET NULL,
                reason TEXT,
                ip VARCHAR(45),
                user_agent VARCHAR(255),
                challenge_id VARCHAR(64) NOT NULL UNIQUE,
                confirm_step1_at TIMESTAMP,
                confirm_step2_at TIMESTAMP,
                outcome VARCHAR(15) DEFAULT 'pending' CHECK (outcome IN ('pending','completed','expired','cancelled')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS job_state (
                id VARCHAR(36) PRIMARY KEY,
                type VARCHAR(30),
                ref_id INTEGER,
                status VARCHAR(12) DEFAULT 'queued' CHECK (status IN ('queued','running','succeeded','failed','cancelled')),
                phase VARCHAR(30),
                progress_pct INTEGER DEFAULT 0,
                logs_ref VARCHAR(255),
                error_code VARCHAR(50),
                result JSONB,
                created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                started_at TIMESTAMP,
                finished_at TIMESTAMP,
                timeout_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_job_state_type_status ON job_state(type, status);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_job_state_ref_id ON job_state(ref_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_job_state_created_at ON job_state(created_at);")

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
            CREATE TABLE IF NOT EXISTS ai_settings (
                id SERIAL PRIMARY KEY,
                selected_provider VARCHAR(100) DEFAULT 'anomalia_ollama',
                zen_api_key TEXT DEFAULT '',
                gemini_api_key TEXT DEFAULT '',
                gemini_model VARCHAR(100) DEFAULT 'gemini-3.5-flash-lite',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cursor.execute("SELECT COUNT(*) FROM ai_settings;")
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO ai_settings (selected_provider) VALUES ('anomalia_ollama');")
        
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
                roles VARCHAR(255),
                ports_pool JSONB,
                capacity_slots INTEGER DEFAULT 10,
                tenants_count_active INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Claves foráneas diferidas (spec 011). Los REFERENCES en línea no son
        # posibles: tenants se crea antes que users y las tablas del ciclo de
        # vida de vmalert antes que infrastructure_nodes. Idempotente.
        cursor.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tenants_instance_id') THEN
                    ALTER TABLE tenants ADD CONSTRAINT fk_tenants_instance_id
                        FOREIGN KEY (instance_id) REFERENCES infrastructure_nodes(id) ON DELETE SET NULL;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tenants_vmalert_node_id') THEN
                    ALTER TABLE tenants ADD CONSTRAINT fk_tenants_vmalert_node_id
                        FOREIGN KEY (vmalert_node_id) REFERENCES infrastructure_nodes(id) ON DELETE SET NULL;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tenants_deletion_confirmed_by') THEN
                    ALTER TABLE tenants ADD CONSTRAINT fk_tenants_deletion_confirmed_by
                        FOREIGN KEY (deletion_confirmed_by) REFERENCES users(id) ON DELETE SET NULL;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tvi_instance_id') THEN
                    ALTER TABLE tenant_vmalert_instances ADD CONSTRAINT fk_tvi_instance_id
                        FOREIGN KEY (instance_id) REFERENCES infrastructure_nodes(id) ON DELETE RESTRICT;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_portmap_instance_id') THEN
                    ALTER TABLE port_mapping ADD CONSTRAINT fk_portmap_instance_id
                        FOREIGN KEY (instance_id) REFERENCES infrastructure_nodes(id) ON DELETE RESTRICT;
                END IF;
            END $$;
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
                INSERT INTO tenants (name, type, account_id, project_id, environment, port, description, has_alerts, is_internal, placement_mode) VALUES 
                ('METRICS', 'metrics', 0, 0, 'default', 8400, 'Tenant para métricas de infraestructura (VictoriaMetrics - vminsert)', TRUE, TRUE, 'auto'),
                ('TRACES', 'traces', 0, 1, 'default', 8490, 'Tenant para trazas distribuidas OTLP (VictoriaTraces - vtinsert)', TRUE, TRUE, 'auto'),
                ('PROFILES', 'profiles', 0, 2, 'default', 4040, 'Tenant de perfilado continuo vía Pyroscope', TRUE, TRUE, 'auto'),
                ('AUDIT_LOGS', 'logs', 0, 3, 'default', 8480, 'Tenant para logs de auditoría (VictoriaLogs - vlinsert)', TRUE, TRUE, 'auto')
                ON CONFLICT (name) DO NOTHING;
            """)

        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error inicializando base de datos: {e}")
    finally:
        cursor.close()
        conn.close()
