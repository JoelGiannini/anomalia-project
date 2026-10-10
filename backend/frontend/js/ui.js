import { api } from './api.js';
import { state, pollJob } from './state.js';

// Consolas de telemetría accesibles desde el panel principal.
//
// Cada entrada indica el contenedor donde se pinta, el perfil que la habilita
// y como se seleccionan los tenants. `scope` viaja al backend y es el que
// determina que perfil se exige para emitir el ticket (UI_SCOPE_PROFILE), de
// modo que METRICS puede abrir la vista de métricas sin tener la de dashboards.
//
// `title` es el nombre de producto que se muestra en el <h3> de la tarjeta;
// cuando no existe (Logs, Auditoría) se usa el nombre del tenant.
// `tab` es la pestaña del panel principal que gobierna esta consola: una pestaña
// solo se muestra si el usuario tiene el perfil Y al menos un tenant que haga
// match, así que no hay que ocultarlas a mano una por una.
const CONSOLES = [
    {
        scope: 'metrics', profile: 'access_metrics', container: 'metrics-tenants-container',
        tab: 'metrics',
        icon: 'fa-chart-pie', title: 'Anomalia-Metrics', button: 'Abrir VictoriaMetrics',
        description: 'Tenant de Métricas',
        empty: 'No hay tenants de métricas autorizados para esta sesión.',
        match: t => (t.type || '').toLowerCase().includes('metric') || t.metrics_url || !t.type
    },
    {
        scope: 'logs', profile: 'access_logs', container: 'logs-tenants-container',
        tab: 'logs',
        icon: 'fa-file-lines', button: 'Abrir VictoriaLogs',
        description: 'Tenant de Logs',
        empty: 'No hay tenants de logs autorizados para esta sesión.',
        // is_audit separa el tenant de auditoría, que también es de tipo LOGS:
        // sin esto aparecía duplicado en la pestaña Logs.
        match: t => !t.is_audit && ((t.type || '').toLowerCase().includes('log') || t.logs_url)
    },
    {
        scope: 'traces', profile: 'access_traces', container: 'traces-container',
        tab: 'traces',
        icon: 'fa-route', title: 'Anomalia-Traces', button: 'Abrir VictoriaTraces',
        description: 'Tenant de Trazas',
        empty: 'No hay tenants de trazas autorizados para esta sesión.',
        match: t => (t.type || '').toLowerCase() === 'traces'
    },
    {
        scope: 'profiling', profile: 'access_Continuous_Profiling', container: 'profiling-container',
        tab: 'profiling',
        icon: 'fa-microchip', title: 'Anomalia-Profiles', button: 'Abrir Pyroscope',
        description: 'Tenant de Perfilado Continuo',
        empty: 'No hay tenants de perfilado autorizados para esta sesión.',
        match: t => (t.type || '').toLowerCase() === 'profiles'
    },
    {
        scope: 'dashboards', profile: 'access_dasboards', container: 'dashboards-container',
        tab: 'dashboards',
        icon: 'fa-chart-line', title: 'Anomalia-Parses', button: 'Abrir Parses',
        description: 'Dashboards de observabilidad (Parses)',
        empty: 'No hay tenants de dashboards autorizados para esta sesión.',
        match: t => (t.type || '').toLowerCase().includes('metric') || t.metrics_url || !t.type
    },
    {
        // Auditoría es una pestaña del panel de administración, no del panel
        // principal: no lleva `tab` y su tarjeta conserva el nombre del tenant.
        scope: 'audit', profile: 'audit', container: 'audit-logs-container',
        icon: 'fa-clock-rotate-left', button: 'Abrir VictoriaLogs',
        description: 'Registros de auditoría del tenant',
        empty: 'No hay tenants de auditoría autorizados para esta sesión.',
        match: t => !!t.is_audit
    }
];

// Pestañas del panel principal que gobierna CONSOLES. `alerts` no está porque no
// es una consola de tenants: su contenido es estático y no depende de asignaciones.
const MANAGED_TABS = new Set(CONSOLES.map(cfg => cfg.tab).filter(Boolean));

// Auto-refresh del listado de consolas de alertas (spec 011 §5.4): tras un
// Controladores AbortController para las esperas únicas de la lista de alertas.
const alertsConfigControllers = {};

function cancelAlertsConfigWait(key) {
    if (alertsConfigControllers[key]) {
        alertsConfigControllers[key].abort();
        delete alertsConfigControllers[key];
    }
}

async function startAlertsConfigWait(key, mine, renderFn) {
    cancelAlertsConfigWait(key);
    const controller = new AbortController();
    alertsConfigControllers[key] = controller;
    try {
        await api.fetchAlertsTenants({ mine, waitDeployed: true, signal: controller.signal });
        renderFn();
    } catch (err) {
        if (err.name !== 'AbortError') {
            console.error('Error en espera de despliegue de alertas:', err);
        }
    } finally {
        if (alertsConfigControllers[key] === controller) {
            delete alertsConfigControllers[key];
        }
    }
}

// Etiqueta del job vmalert más reciente del tenant (deploy/redeploy/undeploy).
// Devuelve null si no hay job o si ya está en estado terminal.
function alertsTenantJobLabel(tenant) {
    const status = tenant.vmalert_job_status;
    if (status === 'queued') return 'En cola de despliegue';
    if (status === 'running') {
        const parts = [];
        if (tenant.vmalert_job_phase) parts.push(tenant.vmalert_job_phase);
        if (typeof tenant.vmalert_job_progress === 'number') {
            parts.push(`${tenant.vmalert_job_progress}%`);
        }
        return parts.length ? `Desplegando… ${parts.join(' · ')}` : 'Desplegando…';
    }
    return null;
}

function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, c => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
}

export const ui = {
    applyTheme(themeName) {
        document.documentElement.className = themeName;
    },

    toggleModal(modalId, show = null) {
        const modal = document.getElementById(modalId);
        if (!modal) return;
        const isHidden = modal.classList.contains('hidden');
        const shouldShow = show !== null ? show : isHidden;
        if (shouldShow) {
            modal.classList.remove('hidden');
            modal.classList.add('flex');
        } else {
            modal.classList.add('hidden');
            modal.classList.remove('flex');
        }
    },

    toggleAdminSidebar() {
        document.getElementById("admin-sidebar")?.classList.toggle("hidden");
    },

    returnToMainView() {
        document.getElementById('admin-views-container')?.classList.add('hidden');
        document.getElementById('main-tabs-container')?.classList.remove('hidden');
        this.switchTab('metrics');
    },

    switchTab(tabName) {
        // Al cambiar de pestaña se cancela cualquier espera pendiente de la lista de
        // alertas; si se entra a `alerts`, su render la reinicia si hace falta.
        cancelAlertsConfigWait('alerts');

        // Si la pestaña pedida está gestionada por CONSOLES y quedó oculta (no hay
        // perfil o no hay tenant), se cae a la primera visible en lugar de dejar la
        // pantalla en blanco.
        if (MANAGED_TABS.has(tabName) && this.visibleTabs && !this.visibleTabs.has(tabName)) {
            const first = this.visibleTabs.values().next().value;
            if (first) tabName = first;
        }

        document.querySelectorAll('.tab-view').forEach(el => el.classList.add('hidden'));
        document.getElementById('admin-views-container')?.classList.add('hidden');
        document.getElementById('main-tabs-container')?.classList.remove('hidden');
        
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.classList.remove('border-current', 'dynamic-text-accent');
            btn.classList.add('border-transparent', 'opacity-70');
        });

        const targetView = document.getElementById(`view-${tabName}`);
        if (targetView) targetView.classList.remove('hidden');
        
        const activeBtn = document.querySelector(`.tab-btn[data-tab="${tabName}"]`);
        if (activeBtn) {
            activeBtn.classList.remove('border-transparent', 'opacity-70');
            activeBtn.classList.add('border-current', 'dynamic-text-accent');
        }

        // Emit tab-changed event for AI assistant context switching
        window.dispatchEvent(new CustomEvent('tab-changed', { detail: { tab: tabName } }));

        // La tarjeta de consolas de alertas se pide solo al abrir su pestaña, para
        // no gastar una llamada a /admin/tenants en cada carga del panel.
        if (tabName === 'alerts') this.renderAlertsConfig();
    },

    switchAdminTab(adminTabName) {
        cancelAlertsConfigWait('admin-alerts');
        document.querySelectorAll('.tab-view').forEach(el => el.classList.add('hidden'));
        document.getElementById('main-tabs-container')?.classList.add('hidden');
        
        document.getElementById('admin-views-container')?.classList.remove('hidden');
        document.querySelectorAll('.admin-tab-view').forEach(el => el.classList.add('hidden'));
        
        document.querySelectorAll('.admin-tab-btn').forEach(btn => {
            btn.classList.remove('dynamic-card', 'border-current');
            btn.classList.add('border-transparent');
        });

        const targetView = document.getElementById(`admin-view-${adminTabName}`);
        if (targetView) targetView.classList.remove('hidden');
        
        const activeBtn = document.getElementById(`admin-tab-btn-${adminTabName}`);
        if (activeBtn) activeBtn.classList.add('dynamic-card', 'border-current');
    },

    hasProfile(profile, roles = [], profiles = []) {
        return roles.includes('admin') || roles.includes(profile) || profiles.includes(profile);
    },

    renderLoading() {
        CONSOLES.forEach(cfg => {
            const container = document.getElementById(cfg.container);
            if (container) container.innerHTML = '<p class="text-xs opacity-75">Cargando consolas...</p>';
        });
    },

    renderTenants(tenants = [], roles = [], profiles = []) {
        const visibleTabs = new Set();

        CONSOLES.forEach(cfg => {
            const container = document.getElementById(cfg.container);
            if (!container) return;

            const allowed = this.hasProfile(cfg.profile, roles, profiles);
            const matches = allowed ? tenants.filter(cfg.match) : [];

            // Regla única de visibilidad: perfil Y al menos un tenant.
            if (cfg.tab && allowed && matches.length) visibleTabs.add(cfg.tab);

            if (!allowed) {
                container.innerHTML =
                    `<p class="text-xs opacity-75">Requiere el perfil «${esc(cfg.profile)}».</p>`;
                return;
            }

            if (!matches.length) {
                container.innerHTML = `<p class="text-xs opacity-75">${esc(cfg.empty)}</p>`;
                return;
            }

            container.innerHTML = matches.map(t => `
                <div class="dynamic-card border rounded-2xl p-6 shadow-xl flex flex-col justify-between">
                    <div>
                        <div class="flex justify-between items-start mb-4">
                            <span class="p-3 dynamic-accent rounded-xl"><i class="fa-solid ${esc(cfg.icon)} text-lg"></i></span>
                            <span class="text-xs dynamic-card px-2 py-1 rounded border font-mono">${esc(t.name)}</span>
                        </div>
                        <h3 class="text-lg font-bold mb-2">${esc(cfg.title || t.name)}</h3>
                        <p class="text-xs opacity-75 mb-4">${esc(cfg.description)}</p>
                    </div>
                    <button type="button" class="btn-open-console w-full dynamic-accent text-center py-2.5 rounded-xl font-medium text-sm transition"
                            data-tenant-id="${esc(t.id)}" data-scope="${esc(cfg.scope)}" data-label="${esc(cfg.button)}">
                        ${esc(cfg.button)}
                    </button>
                </div>
            `).join('');
        });

        this.applyTabVisibility(visibleTabs);
    },

    applyTabVisibility(visibleTabs) {
        this.visibleTabs = visibleTabs;

        // La pestaña activa se lee ANTES de tocar nada: es la referencia para
        // decidir que seccion se deja abierta.
        const activeTab = document.querySelector('#main-tabs-container .tab-btn.border-current')
            ?.getAttribute('data-tab') || 'metrics';

        MANAGED_TABS.forEach(tab => {
            const show = visibleTabs.has(tab);
            document.getElementById(`tab-btn-${tab}`)?.classList.toggle('hidden', !show);
            // Disponibilidad y activacion son dos cosas distintas: sin la segunda
            // condicion renderTenants le quitaba `hidden` a todas las secciones
            // disponibles y se veian todas las tarjetas a la vez.
            document.getElementById(`view-${tab}`)
                ?.classList.toggle('hidden', !show || tab !== activeTab);
        });

        // Si la pestaña que estaba activa quedó oculta, se salta a la primera
        // visible para no dejar el área principal vacía.
        if (MANAGED_TABS.has(activeTab) && !visibleTabs.has(activeTab)) {
            const first = visibleTabs.values().next().value;
            if (first) this.switchTab(first);
        }
    },

    buildAdminSidebarMenu(roles, profiles = []) {
        const menuContainer = document.getElementById("admin-sidebar-menu");
        let html = '';
        
        const isAdmin = roles.includes('admin');
        const hasProfile = (prof) => isAdmin || profiles.includes(prof) || roles.includes(prof);

        if (hasProfile('users_manager')) {
            html += `<button data-admintab="users" id="admin-tab-btn-users" class="admin-tab-btn w-full text-left px-3 py-2.5 rounded-xl text-sm font-medium flex items-center space-x-3 transition dynamic-card border border-transparent"><i class="fa-solid fa-users w-5 dynamic-text-accent"></i><span>Usuarios (Abm)</span></button>`;
        }
        if (hasProfile('tenants_manager')) {
            html += `<button data-admintab="tenants" id="admin-tab-btn-tenants" class="admin-tab-btn w-full text-left px-3 py-2.5 rounded-xl text-sm font-medium flex items-center space-x-3 transition dynamic-card border border-transparent"><i class="fa-solid fa-network-wired w-5 dynamic-text-accent"></i><span>Tenants (Abm)</span></button>`;
        }
        if (hasProfile('roles_manager')) {
            html += `<button data-admintab="roles" id="admin-tab-btn-roles" class="admin-tab-btn w-full text-left px-3 py-2.5 rounded-xl text-sm font-medium flex items-center space-x-3 transition dynamic-card border border-transparent"><i class="fa-solid fa-shield-halved w-5 dynamic-text-accent"></i><span>Roles (Abm)</span></button>`;
        }
        if (hasProfile('profile_manager')) {
            html += `<button data-admintab="profiles" id="admin-tab-btn-profiles" class="admin-tab-btn w-full text-left px-3 py-2.5 rounded-xl text-sm font-medium flex items-center space-x-3 transition dynamic-card border border-transparent"><i class="fa-solid fa-id-card w-5 dynamic-text-accent"></i><span>Perfiles (Abm)</span></button>`;
        }
        if (hasProfile('infra_manager')) {
            html += `<button data-admintab="infra" id="admin-tab-btn-infra" class="admin-tab-btn w-full text-left px-3 py-2.5 rounded-xl text-sm font-medium flex items-center space-x-3 transition dynamic-card border border-transparent"><i class="fa-solid fa-server w-5 dynamic-text-accent"></i><span>Infraestructura</span></button>`;
        }
        if (hasProfile('alerts_manager')) {
            html += `<button data-admintab="alerts" id="admin-tab-btn-alerts" class="admin-tab-btn w-full text-left px-3 py-2.5 rounded-xl text-sm font-medium flex items-center space-x-3 transition dynamic-card border border-transparent"><i class="fa-solid fa-gear w-5 dynamic-text-accent"></i><span>Alerts (conf)</span></button>`;
        }
        if (hasProfile('admin')) {
            html += `<button data-admintab="sso" id="admin-tab-btn-sso" class="admin-tab-btn w-full text-left px-3 py-2.5 rounded-xl text-sm font-medium flex items-center space-x-3 transition dynamic-card border border-transparent"><i class="fa-solid fa-key w-5 dynamic-text-accent"></i><span>SSO (OIDC)</span></button>`;
            html += `<button data-admintab="ai" id="admin-tab-btn-ai" class="admin-tab-btn w-full text-left px-3 py-2.5 rounded-xl text-sm font-medium flex items-center space-x-3 transition dynamic-card border border-transparent"><i class="fa-solid fa-brain w-5 dynamic-text-accent"></i><span>Proveedor IA</span></button>`;
        }
        if (hasProfile('approvers')) {
            html += `<button data-admintab="approvals" id="admin-tab-btn-approvals" class="admin-tab-btn w-full text-left px-3 py-2.5 rounded-xl text-sm font-medium flex items-center space-x-3 transition dynamic-card border border-transparent"><i class="fa-solid fa-clipboard-check w-5 dynamic-text-accent"></i><span>Aprobaciones</span></button>`;
        }
        if (hasProfile('audit')) {
            html += `<button data-admintab="audit" id="admin-tab-btn-audit" class="admin-tab-btn w-full text-left px-3 py-2.5 rounded-xl text-sm font-medium flex items-center space-x-3 transition dynamic-card border border-transparent"><i class="fa-solid fa-clock-rotate-left w-5 dynamic-text-accent"></i><span>Auditoria</span></button>`;
        }

        if (menuContainer) {
            menuContainer.innerHTML = html;
        }
    },

    // Consolas de administración de alertas: vmalert por tenant y Alertmanager
    // global. Ambas exigen el perfil 'alerts_manager' (specs/011 §5.7), que el
    // backend vuelve a comprobar al emitir el ticket y en cada request del proxy.
    async renderAlertsConfig(options = {}) {
        const autoWait = options.autoWait !== false;
        const container = document.getElementById('alerts-config-list');
        if (!container) return;

        cancelAlertsConfigWait('alerts');

        const profiles = state.currentUserProfiles || [];
        if (!profiles.includes('alerts_manager')) {
            container.innerHTML =
                '<p class="text-xs opacity-75">Requiere el perfil alerts_manager para administrar las consolas de alertas.</p>';
            return;
        }

        container.innerHTML = '<p class="text-xs opacity-75">Cargando consolas de alertas...</p>';

        let tenants = [];
        try {
            tenants = await api.fetchAlertsTenants();
        } catch (err) {
            console.error('Error al cargar tenants para Alerts (conf):', err);
            container.innerHTML =
                `<p class="text-xs text-red-400">No se pudo cargar el listado de tenants: ${esc(err.message || err)}</p>`;
            return;
        }

        const withInstance = tenants.filter((t) => t.status === 'active' && t.vmalert_deployed);
        const withRules = tenants.filter((t) => t.status !== 'deleted_cleanup');
        const needsWait = tenants.some(t => t.status === 'active' && t.has_alerts && !t.vmalert_deployed);

        let html = `
            <div class="dynamic-card border rounded-xl p-4 flex justify-between items-center">
                <div>
                    <h4 class="font-bold text-sm">Alertmanager (global)</h4>
                    <p class="text-xs opacity-75">Consola unica del stack, sin tenant</p>
                </div>
                <button id="btn-open-alertmanager-global" class="text-xs dynamic-card border px-2 py-1 rounded">
                    Abrir
                </button>
            </div>
        `;

        if (withInstance.length === 0 && !needsWait) {
            html += `
                <p class="text-xs opacity-75">
                    Ningun tenant tiene una instancia vmalert desplegada. Provisiona el tenant
                    para que aparezca aqui su consola.
                </p>
            `;
        }

        for (const t of withRules) {
            const deployed = t.status === 'active' && t.vmalert_deployed;
            const jobLabel = alertsTenantJobLabel(t);
            let statusLine = '';
            if (!deployed) {
                const desc = jobLabel ? `${jobLabel} — se habilitará automáticamente.` : 'Pendiente de reconciliación — se habilitará automáticamente.';
                statusLine = `
                    <p class="text-xs opacity-75 mt-1">${esc(desc)}</p>
                    <div class="w-full h-2 rounded-full overflow-hidden dynamic-card border mt-2">
                        <div class="h-full w-1/2 dynamic-accent rounded-full animate-pulse"></div>
                    </div>
                `;
            }
            html += `
                <div class="dynamic-card border rounded-xl p-4 flex justify-between items-center">
                    <div>
                        <h4 class="font-bold text-sm">${esc(t.name)}</h4>
                        <p class="text-xs opacity-75">
                            slug: ${esc(t.slug || '-')} | org: ${esc(t.org_id_upper || '-')} |
                            estado: ${esc(t.status || '-')} |
                            nodo: ${esc(t.instance_id || '-')} | puerto: ${esc(t.vmalert_port || '-')}
                        </p>
                        ${statusLine}
                    </div>
                    <div class="flex items-center space-x-2">
                        <button class="btn-vmalert-rules text-xs dynamic-card border px-2 py-1 rounded"
                                data-tenant-id="${esc(t.id)}" data-tenant-slug="${esc(t.slug || '')}"
                                data-tenant-internal="${esc(t.is_internal ? '1' : '0')}">
                            Reglas
                        </button>
                        <button class="btn-vmalert-reload text-xs dynamic-card border px-2 py-1 rounded"
                                data-tenant-id="${esc(t.id)}" ${deployed ? '' : 'disabled title="Sin instancia desplegada"'}>
                            Reload
                        </button>
                        <button class="btn-open-vmalert-tenant text-xs dynamic-card border px-2 py-1 rounded"
                                data-tenant-id="${esc(t.id)}" ${deployed ? '' : 'disabled title="Sin instancia desplegada"'}>
                            Abrir vmalert
                        </button>
                    </div>
                </div>
            `;
        }

        if (needsWait) {
            html += `
                <div class="flex justify-between items-center pt-2">
                    <p class="text-xs opacity-75"><i class="fa-solid fa-spinner fa-spin mr-1"></i> Esperando despliegue automático de instancias pendientes...</p>
                    <button id="btn-retry-alerts-wait" class="text-xs dynamic-card border px-3 py-1.5 rounded">Reintentar</button>
                </div>
            `;
        }

        container.innerHTML = html;

        if (needsWait && autoWait) {
            startAlertsConfigWait('alerts', false, () => this.renderAlertsConfig({ autoWait: false }));
        }

        document.getElementById('btn-retry-alerts-wait')?.addEventListener('click', () => {
            this.renderAlertsConfig({ autoWait: true });
        });

        document.getElementById('btn-open-alertmanager-global')?.addEventListener('click', async () => {
            try {
                const url = await api.createAlertmanagerGlobalUiTicket();
                window.open(url, '_blank');
            } catch (err) {
                console.error('Error abriendo la consola global de Alertmanager:', err);
                alert('No se pudo abrir Alertmanager: ' + (err.message || err));
            }
        });

        container.querySelectorAll('.btn-open-vmalert-tenant').forEach((btn) => {
            btn.addEventListener('click', async () => {
                const tenantId = btn.getAttribute('data-tenant-id');
                try {
                    const url = await api.createVmalertUiTicket(tenantId);
                    window.open(url, '_blank');
                } catch (err) {
                    console.error('Error abriendo la consola vmalert del tenant:', err);
                    alert('No se pudo abrir vmalert: ' + (err.message || err));
                }
            });
        });
    },

    async renderAdminAlertsConfig(options = {}) {
        const autoWait = options.autoWait !== false;
        const container = document.getElementById('admin-alerts-config-list');
        if (!container) return;

        cancelAlertsConfigWait('admin-alerts');

        const profiles = state.currentUserProfiles || [];
        if (!profiles.includes('alerts_manager')) {
            container.innerHTML =
                '<p class="text-xs opacity-75">Requiere el perfil alerts_manager para administrar las consolas de alertas.</p>';
            return;
        }

        container.innerHTML = '<p class="text-xs opacity-75">Cargando consolas de alertas...</p>';

        let tenants = [];
        try {
            tenants = await api.fetchAlertsTenants({ mine: true });
        } catch (err) {
            console.error('Error al cargar tenants para Admin Alerts (conf):', err);
            container.innerHTML =
                `<p class="text-xs text-red-400">No se pudo cargar el listado de tenants: ${esc(err.message || err)}</p>`;
            return;
        }

        const withInstance = tenants.filter((t) => t.status === 'active' && t.vmalert_deployed);
        const withRules = tenants.filter((t) => t.status !== 'deleted_cleanup');
        const needsWait = tenants.some(t => t.status === 'active' && t.has_alerts && !t.vmalert_deployed);

        let html = `
            <div class="dynamic-card border rounded-xl p-4 flex justify-between items-center">
                <div>
                    <h4 class="font-bold text-sm">Alertmanager (global)</h4>
                    <p class="text-xs opacity-75">Consola unica del stack, sin tenant</p>
                </div>
                <button id="btn-open-alertmanager-global-admin" class="text-xs dynamic-card border px-2 py-1 rounded">
                    Abrir
                </button>
            </div>
        `;

        if (withInstance.length === 0 && !needsWait) {
            html += `
                <p class="text-xs opacity-75">
                    Ningun tenant tiene una instancia vmalert desplegada. Provisiona el tenant
                    para que aparezca aqui su consola.
                </p>
            `;
        }

        for (const t of withRules) {
            const deployed = t.status === 'active' && t.vmalert_deployed;
            const jobLabel = alertsTenantJobLabel(t);
            let statusLine = '';
            if (!deployed) {
                const desc = jobLabel ? `${jobLabel} — se habilitará automáticamente.` : 'Pendiente de reconciliación — se habilitará automáticamente.';
                statusLine = `
                    <p class="text-xs opacity-75 mt-1">${esc(desc)}</p>
                    <div class="w-full h-2 rounded-full overflow-hidden dynamic-card border mt-2">
                        <div class="h-full w-1/2 dynamic-accent rounded-full animate-pulse"></div>
                    </div>
                `;
            }
            html += `
                <div class="dynamic-card border rounded-xl p-4 flex justify-between items-center">
                    <div>
                        <h4 class="font-bold text-sm">${esc(t.name)}</h4>
                        <p class="text-xs opacity-75">
                            slug: ${esc(t.slug || '-')} | org: ${esc(t.org_id_upper || '-')} |
                            estado: ${esc(t.status || '-')} |
                            nodo: ${esc(t.instance_id || '-')} | puerto: ${esc(t.vmalert_port || '-')}
                        </p>
                        ${statusLine}
                    </div>
                    <div class="flex items-center space-x-2">
                        <button class="btn-vmalert-rules-admin text-xs dynamic-card border px-2 py-1 rounded"
                                data-tenant-id="${esc(t.id)}" data-tenant-slug="${esc(t.slug || '')}"
                                data-tenant-internal="${esc(t.is_internal ? '1' : '0')}">
                            Reglas
                        </button>
                        <button class="btn-vmalert-reload-admin text-xs dynamic-card border px-2 py-1 rounded"
                                data-tenant-id="${esc(t.id)}" ${deployed ? '' : 'disabled title="Sin instancia desplegada"'}>
                            Reload
                        </button>
                        <button class="btn-open-vmalert-tenant-admin text-xs dynamic-card border px-2 py-1 rounded"
                                data-tenant-id="${esc(t.id)}" ${deployed ? '' : 'disabled title="Sin instancia desplegada"'}>
                            Abrir vmalert
                        </button>
                    </div>
                </div>
            `;
        }

        if (needsWait) {
            html += `
                <div class="flex justify-between items-center pt-2">
                    <p class="text-xs opacity-75"><i class="fa-solid fa-spinner fa-spin mr-1"></i> Esperando despliegue automático de instancias pendientes...</p>
                    <button id="btn-retry-admin-alerts-wait" class="text-xs dynamic-card border px-3 py-1.5 rounded">Reintentar</button>
                </div>
            `;
        }

        container.innerHTML = html;

        if (needsWait && autoWait) {
            startAlertsConfigWait('admin-alerts', true, () => this.renderAdminAlertsConfig({ autoWait: false }));
        }

        document.getElementById('btn-retry-admin-alerts-wait')?.addEventListener('click', () => {
            this.renderAdminAlertsConfig({ autoWait: true });
        });

        document.getElementById('btn-open-alertmanager-global-admin')?.addEventListener('click', async () => {
            try {
                const url = await api.createAlertmanagerGlobalUiTicket();
                window.open(url, '_blank');
            } catch (err) {
                console.error('Error abriendo la consola global de Alertmanager:', err);
                alert('No se pudo abrir Alertmanager: ' + (err.message || err));
            }
        });

        container.querySelectorAll('.btn-open-vmalert-tenant-admin').forEach((btn) => {
            btn.addEventListener('click', async () => {
                const tenantId = btn.getAttribute('data-tenant-id');
                try {
                    const url = await api.createVmalertUiTicket(tenantId);
                    window.open(url, '_blank');
                } catch (err) {
                    console.error('Error abriendo la consola vmalert del tenant:', err);
                    alert('No se pudo abrir vmalert: ' + (err.message || err));
                }
            });
        });
    }
};
