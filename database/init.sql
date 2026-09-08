-- Crear tabla de roles primero por la clave foránea
CREATE TABLE IF NOT EXISTS roles (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Crear tabla de perfiles de acceso
CREATE TABLE IF NOT EXISTS profiles (
    id SERIAL PRIMARY KEY,
    code VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabla intermedia para la relación N a M entre roles y perfiles
CREATE TABLE IF NOT EXISTS role_profiles (
    role_id INTEGER REFERENCES roles(id) ON DELETE CASCADE,
    profile_id INTEGER REFERENCES profiles(id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, profile_id)
);

-- Crear tabla de tenants (entornos, proyectos o cuentas de VictoriaMetrics/VictoriaLogs)
CREATE TABLE IF NOT EXISTS tenants (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,      -- Ej: 'S1-WORK', 'client-a-logs'
    account_id INTEGER NOT NULL,            -- AccountID para VictoriaMetrics/Logs
    project_id INTEGER NOT NULL,            -- ProjectID para VictoriaMetrics/Logs
    environment VARCHAR(50),                -- Ej: 'work', 'live', 'play'
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabla intermedia para asociar roles a múltiples tenants (Relación N a M)
CREATE TABLE IF NOT EXISTS role_tenants (
    role_id INTEGER REFERENCES roles(id) ON DELETE CASCADE,
    tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, tenant_id)
);

-- Crear tabla de usuarios
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabla intermedia para permitir múltiples roles por usuario (N a M)
CREATE TABLE IF NOT EXISTS user_roles (
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    role_id INTEGER REFERENCES roles(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, role_id)
);

-- Insertar roles base del sistema
INSERT INTO roles (name, description) VALUES 
('admin', 'Control total del sistema, OIDC, IA y ABM'),
('operator', 'Monitoreo de alertas y uso de pasarela OIDC'),
('auditor', 'Acceso de solo lectura al historial y logs'),
('tenant_manager', 'Gestión y aprovisionamiento de tenants en VictoriaMetrics y VictoriaLogs')
ON CONFLICT (name) DO NOTHING;

-- Insertar perfiles base iniciales
INSERT INTO profiles (code, name, description) VALUES 
('access_admin', 'Acceso a Administración', 'Permite acceder al panel de configuración general, OIDC y ABM'),
('access_alerts', 'Acceso a Alertas', 'Permite visualizar y gestionar el flujo de alertas y diagnósticos de IA'),
('access_metrics', 'Acceso a Métricas', 'Permite ver dashboards y métricas de infraestructura (Time Series)'),
('access_logs', 'Acceso a Logs', 'Permite consultar y analizar los registros de eventos y trazas'),
('manage_tenants', 'Gestión de Tenants', 'Permite dar de alta y administrar AccountID y ProjectID')
ON CONFLICT (code) DO NOTHING;

-- Asignar perfiles por defecto a los roles
INSERT INTO role_profiles (role_id, profile_id)
SELECT r.id, p.id FROM roles r, profiles p WHERE r.name = 'admin'
ON CONFLICT DO NOTHING;

INSERT INTO role_profiles (role_id, profile_id)
SELECT r.id, p.id FROM roles r, profiles p WHERE r.name = 'operator' AND p.code IN ('access_alerts', 'access_metrics', 'access_logs')
ON CONFLICT DO NOTHING;

INSERT INTO role_profiles (role_id, profile_id)
SELECT r.id, p.id FROM roles r, profiles p WHERE r.name = 'auditor' AND p.code IN ('access_alerts', 'access_logs')
ON CONFLICT DO NOTHING;

INSERT INTO role_profiles (role_id, profile_id)
SELECT r.id, p.id FROM roles r, profiles p WHERE r.name = 'tenant_manager' AND p.code IN ('manage_tenants', 'access_metrics', 'access_logs')
ON CONFLICT DO NOTHING;

-- Insertar tenants de ejemplo base
INSERT INTO tenants (name, account_id, project_id, environment, description) VALUES 
('S1-WORK', 0, 0, 'work', 'Entorno de trabajo principal para métricas y logs'),
('S1-LIVE', 0, 1, 'live', 'Entorno de producción principal'),
('S1-PLAY', 0, 2, 'play', 'Entorno de pruebas y desarrollo')
ON CONFLICT (name) DO NOTHING;

-- Asignar acceso a todos los tenants al rol 'admin' por defecto
INSERT INTO role_tenants (role_id, tenant_id)
SELECT r.id, t.id FROM roles r, tenants t WHERE r.name = 'admin'
ON CONFLICT DO NOTHING;

-- Insertar usuario administrador por defecto
INSERT INTO users (username, password_hash, is_active) VALUES 
('admin@anomalia', 'admin123_hashed', true)
ON CONFLICT (username) 
DO UPDATE SET password_hash = 'admin123_hashed', is_active = true;

-- Asignar el rol 'admin' al usuario administrador por defecto mediante la tabla puente
INSERT INTO user_roles (user_id, role_id)
SELECT u.id, r.id FROM users u, roles r WHERE u.username = 'admin@anomalia' AND r.name = 'admin'
ON CONFLICT DO NOTHING;

-- Crear tabla para la configuración dinámica de Proveedores de Identidad (IdP / OIDC)
CREATE TABLE IF NOT EXISTS oidc_providers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,        -- Ej: 'Keycloak Corporativo', 'Authelia'
    client_id VARCHAR(255) NOT NULL,
    client_secret TEXT DEFAULT '',            -- Ajustado a TEXT y opcional por defecto
    issuer_url TEXT NOT NULL,                 -- URL base del IdP (ej: http://keycloak:8080/realms/aiops)
    redirect_uri TEXT DEFAULT '',             -- Ajustado a opcional por defecto
    is_active BOOLEAN DEFAULT FALSE,          -- Permite activar o desactivar el IdP desde el panel de administración
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insertar un proveedor OIDC de ejemplo base
INSERT INTO oidc_providers (name, client_id, client_secret, issuer_url, redirect_uri, is_active) VALUES
('Keycloak AIOps', 'anomalia-client-id', 'change-me-secret', 'http://keycloak:8080/realms/aiops', 'https://anomalia.local/api/v1/auth/callback', true)
ON CONFLICT (name) DO NOTHING;

-- Tabla para almacenar el historial de alertas y los análisis generados por la IA
CREATE TABLE IF NOT EXISTS alert_history (
    id SERIAL PRIMARY KEY,
    alertname VARCHAR(255) NOT NULL,
    severity VARCHAR(50),
    summary TEXT,
    description TEXT,
    ai_analysis TEXT,
    status VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabla para registrar los dispositivos móviles (APK / Android) y asociarlos a un usuario
CREATE TABLE IF NOT EXISTS user_devices (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    fcm_token TEXT UNIQUE NOT NULL,
    platform VARCHAR(50) DEFAULT 'android',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
