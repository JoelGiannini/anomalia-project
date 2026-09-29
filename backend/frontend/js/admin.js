import { api } from './api.js';
import { state } from './state.js';
import { ui } from './ui.js';

export const admin = {
    async loadAll() {
        await Promise.all([
            this.loadUsers(),
            this.loadTenantsAdmin(),
            this.loadRolesAdmin(),
            this.loadProfilesAdmin(),
            this.loadInfraNodes()
        ]);
    },

    async loadUsers() {
        const token = api.getToken();
        const tbody = document.getElementById("users-table-body");
        if (!tbody) return;
        tbody.innerHTML = `<tr><td colspan="6" class="py-4 text-center opacity-75">Actualizando usuarios...</td></tr>`;
        try {
            const res = await fetch('/api/v1/admin/users', { headers: { 'Authorization': `Bearer ${token}` } });
            if (res.ok) {
                const data = await res.json();
                const users = data.users || [];
                tbody.innerHTML = users.length ? users.map(u => {
                    const safeUserJson = JSON.stringify(u).replace(/"/g, '&quot;');
                    return `
                    <tr class="border-b dynamic-border hover:opacity-90">
                        <td class="py-3 px-4 font-mono">${u.id}</td>
                        <td class="py-3 px-4 font-semibold">${u.username}</td>
                        <td class="py-3 px-4"><span class="px-2 py-1 rounded text-xs font-mono dynamic-accent">${(u.roles || []).join(', ') || 'ninguno'}</span></td>
                        <td class="py-3 px-4"><span class="text-xs opacity-75">${(u.tenants || []).join(', ') || 'ninguno'}</span></td>
                        <td class="py-3 px-4"><span class="text-xs ${u.is_active ? 'text-emerald-400' : 'text-amber-400'} font-mono">${u.is_active ? '🟢 Activo' : '🔴 Inactivo'}</span></td>
                        <td class="py-3 px-4 text-right space-x-2">
                            <button data-edit-user='${safeUserJson}' class="btn-edit-user text-xs dynamic-card border px-2 py-1 rounded">Editar</button>
                            <button data-delete-user="${u.id}" class="btn-delete-user text-xs bg-red-500/20 text-red-400 border border-red-500/30 px-2 py-1 rounded">Eliminar</button>
                        </td>
                    </tr>
                `;
                }).join('') : `<tr><td colspan="6" class="py-4 text-center opacity-75">No hay usuarios registrados.</td></tr>`;
            } else {
                tbody.innerHTML = `<tr><td colspan="6" class="py-4 text-center text-red-400 text-xs">Error al obtener usuarios del servidor.</td></tr>`;
            }
        } catch (err) {
            console.error(err);
            tbody.innerHTML = `<tr><td colspan="6" class="py-4 text-center text-red-400 text-xs">Error de red cargando usuarios.</td></tr>`;
        }
    },

    async openUserModal(user = null) {
        const catalogs = await api.fetchCatalogs();
        state.globalRolesCache = catalogs.roles || [];
        state.globalTenantsCache = catalogs.tenants || [];

        const userIdEl = document.getElementById('user-id');
        if (userIdEl) userIdEl.value = user ? user.id : '';
        const usernameEl = document.getElementById('user-input-username');
        if (usernameEl) usernameEl.value = user ? user.username : '';
        const passwordEl = document.getElementById('user-input-password');
        if (passwordEl) passwordEl.value = '';
        const passwordConfirmEl = document.getElementById('user-input-password-confirm');
        if (passwordConfirmEl) passwordConfirmEl.value = '';
        const activeEl = document.getElementById('user-input-active');
        if (activeEl) activeEl.checked = user ? user.is_active : true;
        const modalTitleEl = document.getElementById('modal-user-title');
        if (modalTitleEl) modalTitleEl.innerText = user ? 'Editar Usuario' : 'Crear Usuario';

        const assignedRoles = user && user.roles ? user.roles : [];
        const rolesContainer = document.getElementById('user-roles-checkboxes');
        if (rolesContainer) {
            rolesContainer.innerHTML = state.globalRolesCache.map(r => `
                <label class="flex items-center space-x-2 text-sm cursor-pointer py-1 px-2 hover:bg-black/10 rounded">
                    <input type="checkbox" name="user_roles_cb" value="${r.name}" ${assignedRoles.includes(r.name) ? 'checked' : ''} class="rounded dynamic-input">
                    <span>${r.name} <span class="text-xs opacity-60">(${r.description || ''})</span></span>
                </label>
            `).join('');
        }

        const assignedTenants = user && user.tenants ? user.tenants : [];
        const tenantsContainer = document.getElementById('user-tenants-checkboxes');
        if (tenantsContainer) {
            tenantsContainer.innerHTML = state.globalTenantsCache.map(t => `
                <label class="flex items-center space-x-2 text-sm cursor-pointer py-1 px-2 hover:bg-black/10 rounded">
                    <input type="checkbox" name="user_tenants_cb" value="${t.name}" ${assignedTenants.includes(t.name) ? 'checked' : ''} class="rounded dynamic-input">
                    <span>${t.name} <span class="text-xs opacity-60">(${t.type})</span></span>
                </label>
            `).join('');
        }

        ui.toggleModal('modal-user', true);
    },

    async saveUser() {
        const id = document.getElementById('user-id')?.value;
        const username = document.getElementById('user-input-username')?.value;
        const password = document.getElementById('user-input-password')?.value;
        const passwordConfirm = document.getElementById('user-input-password-confirm')?.value;

        if (password || passwordConfirm) {
            if (password !== passwordConfirm) {
                alert("Error: Las contraseñas no coinciden.");
                return;
            }
        }

        const roles = Array.from(document.querySelectorAll('input[name="user_roles_cb"]:checked')).map(cb => cb.value);
        const tenants = Array.from(document.querySelectorAll('input[name="user_tenants_cb"]:checked')).map(cb => cb.value);
        const is_active = document.getElementById('user-input-active')?.checked ?? true;
        const token = api.getToken();

        const method = id ? 'PUT' : 'POST';
        const url = id ? `/api/v1/admin/users/${id}` : '/api/v1/admin/users';
        const payload = { username, roles, tenants, is_active };
        if (password) payload.password = password;

        try {
            const res = await fetch(url, {
                method,
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                body: JSON.stringify(payload)
            });

            if (res.ok) {
                ui.toggleModal('modal-user', false);
                this.loadUsers();
            } else {
                const err = await res.json();
                alert("Error: " + (err.detail || "No se pudo guardar el usuario."));
            }
        } catch (e) {
            console.error(e);
            alert("Error de red al intentar guardar el usuario.");
        }
    },

    async deleteUser(id) {
        if (!confirm("¿Estás seguro de eliminar este usuario?")) return;
        const token = api.getToken();
        try {
            const res = await fetch(`/api/v1/admin/users/${id}`, { method: 'DELETE', headers: { 'Authorization': `Bearer ${token}` } });
            if (res.ok) this.loadUsers();
            else alert("Error al eliminar usuario.");
        } catch (e) {
            console.error(e);
            alert("Error de red al eliminar usuario.");
        }
    },

    async loadTenantsAdmin() {
        const token = api.getToken();
        const container = document.getElementById("admin-tenants-container");
        if (!container) return;
        container.innerHTML = `<p class="text-xs opacity-75 col-span-2">Actualizando tenants...</p>`;
        try {
            const res = await fetch('/api/v1/admin/tenants', { headers: { 'Authorization': `Bearer ${token}` } });
            if (res.ok) {
                const data = await res.json();
                const tenants = data.tenants || [];
                container.innerHTML = tenants.length ? tenants.map(t => {
                    const safeTenantJson = JSON.stringify(t).replace(/"/g, '&quot;');
                    return `
                    <div class="dynamic-card border rounded-xl p-4 flex justify-between items-center">
                        <div>
                            <h4 class="font-bold text-sm">${t.name} <span class="text-emerald-400 text-xs font-mono ml-2">🟢 Operativo</span></h4>
                            <p class="text-xs opacity-75">Tipo: ${t.type} | Entorno: ${t.environment} | Puerto: ${t.port}</p>
                            <p class="text-xs opacity-60 mt-1">${t.description || 'Sin descripción'}</p>
                        </div>
                        <div class="flex items-center space-x-2">
                            <span class="text-xs dynamic-card px-2 py-1 rounded border font-mono">ID: ${t.id}</span>
                            <button data-edit-tenant='${safeTenantJson}' class="btn-edit-tenant text-xs dynamic-card border px-2 py-1 rounded">Editar</button>
                            <button data-delete-tenant="${t.id}" class="btn-delete-tenant text-xs bg-red-500/20 text-red-400 border border-red-500/30 px-2 py-1 rounded">Eliminar</button>
                        </div>
                    </div>
                `;
                }).join('') : `<p class="text-xs opacity-75 col-span-2">No hay tenants en la base de datos.</p>`;
            } else {
                container.innerHTML = `<p class="text-xs text-red-400 col-span-2">Error al obtener tenants del servidor.</p>`;
            }
        } catch (err) {
            console.error(err);
            container.innerHTML = `<p class="text-xs text-red-400 col-span-2">Error cargando tenants.</p>`;
        }
    },

    openTenantModal(t = null) {
        const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };
        setVal('tenant-id', t ? t.id : '');
        setVal('tenant-input-name', t ? t.name : '');
        setVal('tenant-input-type', t ? t.type : 'metrics');
        setVal('tenant-input-env', t ? t.environment : 'default');
        setVal('tenant-input-account', t ? t.account_id : 0);
        setVal('tenant-input-project', t ? t.project_id : 0);
        setVal('tenant-input-port', t ? t.port : 8400);
        setVal('tenant-input-desc', t && t.description ? t.description : '');
        const titleEl = document.getElementById('modal-tenant-title');
        if (titleEl) titleEl.innerText = t ? 'Editar Tenant' : 'Crear Tenant';
        ui.toggleModal('modal-tenant', true);
    },

    async saveTenant() {
        const id = document.getElementById('tenant-id')?.value;
        const name = document.getElementById('tenant-input-name')?.value;
        const type = document.getElementById('tenant-input-type')?.value;
        const environment = document.getElementById('tenant-input-env')?.value;
        const account_id = parseInt(document.getElementById('tenant-input-account')?.value || 0);
        const project_id = parseInt(document.getElementById('tenant-input-project')?.value || 0);
        const port = parseInt(document.getElementById('tenant-input-port')?.value || 8400);
        const description = document.getElementById('tenant-input-desc')?.value;
        const token = api.getToken();

        const method = id ? 'PUT' : 'POST';
        const url = id ? `/api/v1/admin/tenants/${id}` : '/api/v1/admin/tenants';

        try {
            const res = await fetch(url, {
                method,
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                body: JSON.stringify({ name, type, account_id, project_id, environment, port, description })
            });

            if (res.ok) {
                ui.toggleModal('modal-tenant', false);
                this.loadTenantsAdmin();
            } else {
                const err = await res.json();
                alert("Error: " + (err.detail || "No se pudo guardar el tenant."));
            }
        } catch (e) {
            console.error(e);
            alert("Error de red al guardar tenant.");
        }
    },

    async deleteTenant(id) {
        if (!confirm("¿Estás seguro de eliminar este tenant?")) return;
        const token = api.getToken();
        try {
            const res = await fetch(`/api/v1/admin/tenants/${id}`, { method: 'DELETE', headers: { 'Authorization': `Bearer ${token}` } });
            if (res.ok) this.loadTenantsAdmin();
            else alert("Error al eliminar tenant.");
        } catch (e) {
            console.error(e);
            alert("Error de red al eliminar tenant.");
        }
    },

    async loadRolesAdmin() {
        const token = api.getToken();
        const tbody = document.getElementById("roles-table-body");
        if (!tbody) return;
        tbody.innerHTML = `<tr><td colspan="5" class="py-4 text-center opacity-75">Actualizando roles...</td></tr>`;
        try {
            const res = await fetch('/api/v1/admin/roles', { headers: { 'Authorization': `Bearer ${token}` } });
            if (res.ok) {
                const data = await res.json();
                const roles = data.roles || [];
                tbody.innerHTML = roles.length ? roles.map(r => {
                    const safeRoleJson = JSON.stringify(r).replace(/"/g, '&quot;');
                    return `
                    <tr class="border-b dynamic-border">
                        <td class="py-3 px-4 font-mono">${r.id}</td>
                        <td class="py-3 px-4 font-semibold">${r.name}</td>
                        <td class="py-3 px-4 opacity-75">${r.description || 'Sin descripción'}</td>
                        <td class="py-3 px-4">
                            <div class="text-xs space-y-1">
                                <div><strong>Tenants:</strong> ${(r.tenants || []).join(', ') || 'ninguno'}</div>
                                <div><strong>Perfiles:</strong> <span class="bg-indigo-500/20 text-indigo-300 px-2 py-0.5 rounded">${(r.profiles || []).join(', ') || 'ninguno'}</span></div>
                            </div>
                        </td>
                        <td class="py-3 px-4 text-right space-x-2">
                            <button data-edit-role='${safeRoleJson}' class="btn-edit-role text-xs dynamic-card border px-2 py-1 rounded">Editar</button>
                            <button data-delete-role="${r.id}" class="btn-delete-role text-xs bg-red-500/20 text-red-400 border border-red-500/30 px-2 py-1 rounded">Eliminar</button>
                        </td>
                    </tr>
                `;
                }).join('') : `<tr><td colspan="5" class="py-4 text-center opacity-75">No hay roles registrados.</td></tr>`;
            } else {
                tbody.innerHTML = `<tr><td colspan="5" class="py-4 text-center text-red-400 text-xs">Error al obtener roles del servidor.</td></tr>`;
            }
        } catch (err) {
            console.error(err);
            tbody.innerHTML = `<tr><td colspan="5" class="py-4 text-center text-red-400 text-xs">Error cargando roles.</td></tr>`;
        }
    },

    async openRoleModal(r = null) {
        const catalogs = await api.fetchCatalogs();
        state.globalTenantsCache = catalogs.tenants || [];
        state.globalProfilesCache = catalogs.profiles || [];

        const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };
        setVal('role-id', r ? r.id : '');
        setVal('role-input-name', r ? r.name : '');
        setVal('role-input-desc', r && r.description ? r.description : '');
        const titleEl = document.getElementById('modal-role-title');
        if (titleEl) titleEl.innerText = r ? 'Editar Rol' : 'Crear Rol';

        const assignedTenants = r && r.tenants ? r.tenants : [];
        const tenantsContainer = document.getElementById('role-tenants-checkboxes');
        if (tenantsContainer) {
            tenantsContainer.innerHTML = state.globalTenantsCache.map(t => `
                <label class="flex items-center space-x-2 text-sm cursor-pointer py-1 px-2 hover:bg-black/10 rounded">
                    <input type="checkbox" name="role_tenants_cb" value="${t.name}" ${assignedTenants.includes(t.name) ? 'checked' : ''} class="rounded dynamic-input">
                    <span>${t.name} <span class="text-xs opacity-60">(${t.type})</span></span>
                </label>
            `).join('');
        }

        const assignedProfiles = r && r.profiles ? r.profiles.map(p => typeof p === 'object' ? (p.code || p.name) : p) : [];
        const profilesContainer = document.getElementById('role-profiles-checkboxes');
        if (profilesContainer) {
            profilesContainer.innerHTML = state.globalProfilesCache.map(p => {
                const pValue = p.code || p.name;
                const isChecked = assignedProfiles.some(ap => 
                    String(ap).toLowerCase() === String(pValue).toLowerCase() ||
                    String(ap).toLowerCase() === String(p.name).toLowerCase()
                );

                return `
                <label class="flex items-center space-x-2 text-sm cursor-pointer py-1 px-2 hover:bg-black/10 rounded">
                    <input type="checkbox" name="role_profiles_cb" value="${pValue}" ${isChecked ? 'checked' : ''} class="rounded dynamic-input">
                    <span>${p.name} <span class="text-xs opacity-60">(${p.description || ''})</span></span>
                </label>
            `;
            }).join('');
        }

        ui.toggleModal('modal-role', true);
    },

    async saveRole() {
        const id = document.getElementById('role-id')?.value;
        const name = document.getElementById('role-input-name')?.value;
        const description = document.getElementById('role-input-desc')?.value;
        const tenants = Array.from(document.querySelectorAll('input[name="role_tenants_cb"]:checked')).map(cb => cb.value);
        const profiles = Array.from(document.querySelectorAll('input[name="role_profiles_cb"]:checked')).map(cb => cb.value);
        const token = api.getToken();

        const method = id ? 'PUT' : 'POST';
        const url = id ? `/api/v1/admin/roles/${id}` : '/api/v1/admin/roles';

        try {
            const res = await fetch(url, {
                method,
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                body: JSON.stringify({ name, description, tenants, profiles })
            });

            if (res.ok) {
                ui.toggleModal('modal-role', false);
                this.loadRolesAdmin();
            } else {
                const err = await res.json();
                alert("Error: " + (err.detail || "No se pudo guardar el rol."));
            }
        } catch (e) {
            console.error(e);
            alert("Error de red al guardar el rol.");
        }
    },

    async deleteRole(id) {
        if (!confirm("¿Estás seguro de eliminar este rol?")) return;
        const token = api.getToken();
        try {
            const res = await fetch(`/api/v1/admin/roles/${id}`, { method: 'DELETE', headers: { 'Authorization': `Bearer ${token}` } });
            if (res.ok) this.loadRolesAdmin();
            else alert("Error al eliminar rol.");
        } catch (e) {
            console.error(e);
            alert("Error de red al eliminar rol.");
        }
    },

    async loadProfilesAdmin() {
        const token = api.getToken();
        const container = document.getElementById("admin-profiles-container");
        if (!container) return;
        container.innerHTML = `<p class="text-xs opacity-75 col-span-3">Actualizando perfiles...</p>`;
        try {
            const res = await fetch('/api/v1/admin/profiles', { headers: { 'Authorization': `Bearer ${token}` } });
            if (res.ok) {
                const data = await res.json();
                const profiles = data.profiles || [];
                container.innerHTML = profiles.length ? profiles.map(p => {
                    const safeProfileJson = JSON.stringify(p).replace(/"/g, '&quot;');
                    return `
                    <div class="dynamic-card border rounded-2xl p-5 flex flex-col justify-between shadow-lg">
                        <div>
                            <div class="flex justify-between items-start mb-2">
                                <h4 class="font-bold text-base">${p.name}</h4>
                                <span class="text-xs dynamic-card px-2 py-0.5 rounded border font-mono">ID: ${p.id}</span>
                            </div>
                            <div class="mb-3">
                                <span class="text-xs dynamic-accent px-2 py-0.5 rounded font-mono">CODE: ${p.code}</span>
                            </div>
                            <p class="text-xs opacity-75 mb-4">${p.description || 'Sin descripción'}</p>
                        </div>
                        <div class="flex justify-end space-x-2 pt-3 border-t dynamic-border">
                            <button data-edit-profile='${safeProfileJson}' class="btn-edit-profile text-xs dynamic-card border px-3 py-1 rounded">Editar</button>
                            <button data-delete-profile="${p.id}" class="btn-delete-profile text-xs bg-red-500/20 text-red-400 border border-red-500/30 px-3 py-1 rounded">Eliminar</button>
                        </div>
                    </div>
                `;
                }).join('') : `<p class="text-xs opacity-75 col-span-3">No hay perfiles registrados.</p>`;
            } else {
                container.innerHTML = `<p class="text-xs text-red-400 col-span-3">Error al obtener perfiles del servidor.</p>`;
            }
        } catch (err) {
            console.error(err);
            container.innerHTML = `<p class="text-xs text-red-400 col-span-3">Error cargando perfiles.</p>`;
        }
    },

    openProfileModal(p = null) {
        const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };
        setVal('profile-id', p ? p.id : '');
        setVal('profile-input-name', p ? p.name : '');
        setVal('profile-input-code', p ? p.code : '');
        setVal('profile-input-desc', p && p.description ? p.description : '');
        const titleEl = document.getElementById('modal-profile-title');
        if (titleEl) titleEl.innerText = p ? 'Editar Perfil' : 'Crear Perfil';
        ui.toggleModal('modal-profile', true);
    },

    async saveProfile() {
        const id = document.getElementById('profile-id')?.value;
        const name = document.getElementById('profile-input-name')?.value;
        const code = document.getElementById('profile-input-code')?.value;
        const description = document.getElementById('profile-input-desc')?.value;
        const token = api.getToken();

        const method = id ? 'PUT' : 'POST';
        const url = id ? `/api/v1/admin/profiles/${id}` : '/api/v1/admin/profiles';

        try {
            const res = await fetch(url, {
                method,
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                body: JSON.stringify({ code, name, description })
            });

            if (res.ok) {
                ui.toggleModal('modal-profile', false);
                this.loadProfilesAdmin();
            } else {
                const err = await res.json();
                alert("Error: " + (err.detail || "No se pudo guardar el perfil."));
            }
        } catch (e) {
            console.error(e);
            alert("Error de red al guardar el perfil.");
        }
    },

    async deleteProfile(id) {
        if (!confirm("¿Estás seguro de eliminar este perfil?")) return;
        const token = api.getToken();
        try {
            const res = await fetch(`/api/v1/admin/profiles/${id}`, { method: 'DELETE', headers: { 'Authorization': `Bearer ${token}` } });
            if (res.ok) this.loadProfilesAdmin();
            else alert("Error al eliminar perfil.");
        } catch (e) {
            console.error(e);
            alert("Error de red al eliminar perfil.");
        }
    },

    async loadInfraNodes() {
        const token = api.getToken();
        const container = document.getElementById("infra-nodes-container");
        if (!container) return;
        container.innerHTML = `<p class="text-xs opacity-75 col-span-2">Cargando servidores...</p>`;
        try {
            const res = await fetch('/api/v1/admin/infra', { headers: { 'Authorization': `Bearer ${token}` } });
            if (res.ok) {
                const data = await res.json();
                const nodes = data.nodes || [];
                container.innerHTML = nodes.length ? nodes.map(n => {
                    const safeNodeJson = JSON.stringify(n).replace(/"/g, '&quot;');
                    const hostName = n.hostname || n.host || n.name || 'Sin Host';
                    const ipAddress = n.ip_address || '--';
                    const serviceIp = n.service_ip || '--';
                    const nodeType = n.component_type || n.type || '--';
                    return `
                    <div class="dynamic-card border rounded-xl p-4 flex justify-between items-center" id="infra-node-card-${n.id}">
                        <div>
                            <h4 class="font-bold text-sm">${hostName} <span class="text-emerald-400 text-xs font-mono ml-2">🟢 ${n.status || 'Online'}</span></h4>
                            <p class="text-xs opacity-75">${ipAddress} | ${serviceIp} | ${nodeType}</p>
                        </div>
                        <div class="flex items-center space-x-2" id="infra-actions-${n.id}">
                            <button data-edit-infra='${safeNodeJson}' class="btn-edit-infra text-xs dynamic-card border px-2 py-1 rounded">Editar</button>
                            <button data-update-infra='${n.id}' class="btn-update-infra text-xs dynamic-accent px-2 py-1 rounded">Update</button>
                            <button data-delete-infra="${n.id}" class="btn-delete-infra text-xs bg-red-500/20 text-red-400 border border-red-500/30 px-2 py-1 rounded">Eliminar</button>
                        </div>
                    </div>
                `;
                }).join('') : `<p class="text-xs opacity-75 col-span-2">No hay nodos de infraestructura.</p>`;
            } else {
                container.innerHTML = `<p class="text-xs text-red-400 col-span-2">Error al obtener nodos.</p>`;
            }
        } catch (e) {
            console.error(e);
            container.innerHTML = `<p class="text-xs text-red-400 col-span-2">Error de red cargando infraestructura.</p>`;
        }
    },

    async openInfraModal(n = null) {
        const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };
        setVal('infra-id', n ? n.id : '');
        setVal('infra-input-name', n ? (n.hostname || n.host || n.name || '') : '');
        setVal('infra-input-ip', n ? n.ip_address : '');
        setVal('infra-input-service-ip', n ? n.service_ip : '');
        setVal('infra-input-type', n ? (n.component_type || n.type || '') : '');

        try {
            const res = await fetch('/api/v1/admin/infra/component-types', {
                headers: { 'Authorization': `Bearer ${api.getToken()}` }
            });
            if (res.ok) {
                const data = await res.json();
                const select = document.getElementById('infra-input-type');
                select.innerHTML = '<option value="">Seleccionar...</option>' +
                    data.component_types.map(t => `<option value="${t.value}">${t.label}</option>`).join('');
                if (n && n.component_type) {
                    select.value = n.component_type;
                }
            }
        } catch (e) {
            console.error(e);
        }

        ui.toggleModal('modal-infra', true);
    },

    async saveInfraNode() {
        const id = document.getElementById('infra-id')?.value;
        const hostname = document.getElementById('infra-input-name')?.value;
        const ip_address = document.getElementById('infra-input-ip')?.value;
        const service_ip = document.getElementById('infra-input-service-ip')?.value;
        const component_type = document.getElementById('infra-input-type')?.value;
        const token = api.getToken();

        if (!id) {
            alert("Error: no se identificó el nodo a editar.");
            return;
        }
        if (!hostname || !ip_address || !component_type) {
            alert("Error: Hostname, IP y Tipo son obligatorios.");
            return;
        }

        const body = { hostname, ip_address, service_ip, component_type };

        try {
            const res = await fetch(`/api/v1/admin/infra/${id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                body: JSON.stringify(body)
            });

            if (res.ok) {
                ui.toggleModal('modal-infra', false);
                this.loadInfraNodes();
            } else {
                const err = await res.json();
                alert(err.detail || "No se pudo guardar el nodo.");
            }
        } catch (e) {
            console.error(e);
            alert("Error de red al guardar nodo.");
        }
    },

    async updateInfraNodeStatus(id) {
        const token = api.getToken();
        const actionsContainer = document.getElementById(`infra-actions-${id}`);
        if (!actionsContainer) return;

        // Reemplazar botones por barra de progreso animada
        actionsContainer.innerHTML = `
            <div class="flex items-center space-x-2 w-48">
                <div class="w-full bg-gray-700 rounded-full h-2.5 overflow-hidden">
                    <div id="progress-bar-${id}" class="bg-blue-500 h-2.5 rounded-full transition-all duration-500" style="width: 15%"></div>
                </div>
                <span id="progress-text-${id}" class="text-xs font-mono">15%</span>
            </div>
        `;

        let progress = 15;
        const interval = setInterval(() => {
            if (progress < 85) {
                progress += 10;
                const bar = document.getElementById(`progress-bar-${id}`);
                const txt = document.getElementById(`progress-text-${id}`);
                if (bar) bar.style.width = `${progress}%`;
                if (txt) txt.innerText = `${progress}%`;
            }
        }, 400);

        try {
            const res = await fetch(`/api/v1/admin/infra/${id}/update`, { method: 'POST', headers: { 'Authorization': `Bearer ${token}` } });
            clearInterval(interval);
            
            const bar = document.getElementById(`progress-bar-${id}`);
            const txt = document.getElementById(`progress-text-${id}`);
            if (bar) bar.style.width = '100%';
            if (txt) txt.innerText = '100%';

            setTimeout(() => {
                if (res.ok) {
                    alert("Playbook ejecutado y nodo actualizado correctamente.");
                } else {
                    alert("Actualización finalizada con observaciones.");
                }
                this.loadInfraNodes();
            }, 500);

        } catch (e) {
            clearInterval(interval);
            console.error(e);
            alert("Error de red o timeout al ejecutar la actualización del nodo.");
            this.loadInfraNodes();
        }
    },

    async deleteInfraNode(id) {
        if (!confirm("¿Estás seguro de eliminar este nodo?")) return;
        const token = api.getToken();
        try {
            const res = await fetch(`/api/v1/admin/infra/${id}`, { method: 'DELETE', headers: { 'Authorization': `Bearer ${token}` } });
            if (res.ok) this.loadInfraNodes();
            else alert("Error al eliminar nodo.");
        } catch (e) {
            console.error(e);
            alert("Error de red al eliminar nodo.");
        }
    }
};
