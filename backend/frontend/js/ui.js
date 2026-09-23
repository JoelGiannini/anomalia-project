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
    },

    switchAdminTab(adminTabName) {
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

    renderTenants(tenants) {
        const logsContainer = document.getElementById('logs-tenants-container');
        const metricsContainer = document.getElementById('metrics-tenants-container');

        if (!logsContainer || !metricsContainer) return;

        const logsTenants = tenants.filter(t => (t.type || '').toLowerCase().includes('log') || t.logs_url);
        const metricsTenants = tenants.filter(t => (t.type || '').toLowerCase().includes('metric') || t.metrics_url || !t.type);

        logsContainer.innerHTML = logsTenants.length ? logsTenants.map(t => `
            <div class="dynamic-card border rounded-2xl p-6 shadow-xl flex flex-col justify-between">
                <div>
                    <div class="flex justify-between items-start mb-4">
                        <span class="p-3 dynamic-accent rounded-xl"><i class="fa-solid fa-file-lines text-lg"></i></span>
                        <span class="text-xs dynamic-card px-2 py-1 rounded border">Puerto: <span class="font-mono">${t.port}</span></span>
                    </div>
                    <h3 class="text-lg font-bold mb-2">${t.name}</h3>
                    <p class="text-xs opacity-75 mb-4">${t.description || 'Tenant de Logs'}</p>
                </div>
                <a href="#" class="w-full dynamic-accent text-center py-2.5 rounded-xl font-medium text-sm transition">Abrir VictoriaLogs</a>
            </div>
        `).join('') : `<p class="text-xs opacity-75 col-span-3">No hay tenants de logs autorizados para esta sesión.</p>`;

        metricsContainer.innerHTML = metricsTenants.length ? metricsTenants.map(t => `
            <div class="dynamic-card border rounded-2xl p-6 shadow-xl flex flex-col justify-between">
                <div>
                    <div class="flex justify-between items-start mb-4">
                        <span class="p-3 dynamic-accent rounded-xl"><i class="fa-solid fa-chart-pie text-lg"></i></span>
                        <span class="text-xs dynamic-card px-2 py-1 rounded border">Puerto: <span class="font-mono">${t.port}</span></span>
                    </div>
                    <h3 class="text-lg font-bold mb-2">${t.name}</h3>
                    <p class="text-xs opacity-75 mb-4">${t.description || 'Tenant de Métricas'}</p>
                </div>
                <a href="#" class="w-full dynamic-accent text-center py-2.5 rounded-xl font-medium text-sm transition">Abrir VictoriaMetrics</a>
            </div>
        `).join('') : `<p class="text-xs opacity-75 col-span-3">No hay tenants de métricas autorizados para esta sesión.</p>`;
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
    }
};
