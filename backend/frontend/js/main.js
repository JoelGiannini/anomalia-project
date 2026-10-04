import { api } from './api.js';
import { ui } from './ui.js';
import { admin } from './admin.js';
import { state } from './state.js';

window.admin = admin;

document.addEventListener("DOMContentLoaded", async () => {
    const token = api.getToken();
    if (!token) {
        window.location.href = "/login";
        return;
    }

    let username = localStorage.getItem("username") || "Usuario";
    let role = localStorage.getItem("role") || "viewer";
    state.currentUserRoles = JSON.parse(localStorage.getItem("roles") || '["viewer"]');
    state.currentUserProfiles = JSON.parse(localStorage.getItem("profiles") || '[]');
    let userTheme = localStorage.getItem('user_theme') || 'theme-enterprise-blue';
    let userAvatarUrl = "/media/default.png";

    try {
        const userData = await api.fetchUserData();
        username = userData.username || username;
        role = userData.role || role;
        
        if (userData.roles) {
            state.currentUserRoles = userData.roles;
            localStorage.setItem('roles', JSON.stringify(state.currentUserRoles));
        }
        if (userData.profiles) {
            state.currentUserProfiles = userData.profiles;
            localStorage.setItem('profiles', JSON.stringify(state.currentUserProfiles));
        }
        if (userData.theme) {
            userTheme = userData.theme;
            localStorage.setItem('user_theme', userTheme);
        }
        if (userData.avatar_url) {
            userAvatarUrl = userData.avatar_url;
        }
    } catch (error) {
        console.error("Error sincronizando perfil:", error);
    }

    ui.applyTheme(userTheme);
    const themePref = document.getElementById('user-theme-preference');
    if (themePref) themePref.value = userTheme;
    
    const displayName = document.getElementById("user-display-name");
    if (displayName) displayName.innerText = username;
    
    const displayRole = document.getElementById("user-display-role");
    if (displayRole) displayRole.innerText = `Rol: ${role} (${state.currentUserRoles.join(', ')})`;
    
    const modalUsername = document.getElementById("modal-username");
    if (modalUsername) modalUsername.innerText = username;
    
    const modalRoles = document.getElementById("modal-user-inherited-roles");
    if (modalRoles) modalRoles.innerText = `Roles asignados: ${state.currentUserRoles.join(' | ')} | Perfiles: ${state.currentUserProfiles.join(' | ') || 'ninguno'}`;

    const headerAvatar = document.getElementById("user-avatar");
    const modalAvatar = document.getElementById("modal-avatar-preview");
    const defaultAvatar = "/media/default.png";

    const setupAvatarImg = (imgEl, url) => {
        if (!imgEl) return;
        imgEl.src = url;
        imgEl.onerror = () => {
            imgEl.src = defaultAvatar;
        };
    };

    setupAvatarImg(headerAvatar, userAvatarUrl);
    setupAvatarImg(modalAvatar, userAvatarUrl);

    const avatarInput = document.getElementById("input-user-avatar-file");
    if (avatarInput) {
        avatarInput.addEventListener("change", (e) => {
            const file = e.target.files[0];
            if (file) {
                const reader = new FileReader();
                reader.onload = (event) => {
                    if (headerAvatar) headerAvatar.src = event.target.result;
                    if (modalAvatar) modalAvatar.src = event.target.result;
                };
                reader.readAsDataURL(file);
            }
        });
    }

    const hasPrivilegedAccess = state.currentUserRoles.includes("admin") || 
        state.currentUserRoles.some(r => ["user_manager", "tenant_manager", "role_manager", "profile_manager", "infra_manager"].includes(r)) ||
        state.currentUserProfiles.some(p => ["users_manager", "tenants_manager", "roles_manager", "profile_manager", "infra_manager", "admin", "approvers", "audit"].includes(p));

    if (hasPrivilegedAccess) {
        const sidebarToggle = document.getElementById("admin-sidebar-toggle-container");
        if (sidebarToggle) sidebarToggle.classList.remove("hidden");
        ui.buildAdminSidebarMenu(state.currentUserRoles, state.currentUserProfiles);
        admin.loadAll();
    }

    try {
        ui.renderLoading();
        const tenants = await api.fetchUserTenants();
        ui.renderTenants(tenants, state.currentUserRoles, state.currentUserProfiles);
    } catch (err) {
        console.error("Error al cargar tenants del usuario:", err);
        alert("No se pudieron cargar los tenants autorizados: " + (err.message || err));
    }

    const profileBtn = document.getElementById('profile-menu-button');
    if (profileBtn) profileBtn.addEventListener('click', () => ui.toggleModal('profile-modal'));
    
    document.getElementById('btn-toggle-sidebar')?.addEventListener('click', () => ui.toggleAdminSidebar());
    document.getElementById('btn-close-sidebar')?.addEventListener('click', () => ui.toggleAdminSidebar());
    
    const returnMain = document.getElementById('btn-return-main');
    if (returnMain) returnMain.addEventListener('click', () => ui.returnToMainView());

    document.querySelectorAll('.close-modal-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const modalId = btn.getAttribute('data-modal');
            ui.toggleModal(modalId, false);
        });
    });

    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            ui.switchTab(btn.getAttribute('data-tab'));
        });
    });

    document.addEventListener('click', (e) => {
        const admBtn = e.target.closest('.admin-tab-btn');
        if (admBtn) {
            const tabName = admBtn.getAttribute('data-admintab');
            ui.switchAdminTab(tabName);
            if (tabName === 'users') admin.loadUsers();
            if (tabName === 'tenants') admin.loadTenantsAdmin();
            if (tabName === 'roles') admin.loadRolesAdmin();
            if (tabName === 'profiles') admin.loadProfilesAdmin();
            if (tabName === 'infra') admin.loadInfraNodes();
            if (tabName === 'ai') admin.loadAIConfig();
            if (tabName === 'approvals') admin.loadApprovals?.();
        }
    });

    document.addEventListener('click', async (e) => {
        const consoleBtn = e.target.closest('.btn-open-console');
        if (!consoleBtn || consoleBtn.disabled) return;

        const tenantId = Number(consoleBtn.dataset.tenantId);
        const scope = consoleBtn.dataset.scope;
        const label = consoleBtn.dataset.label || 'la consola';
        if (!tenantId || !scope) return;

        const original = consoleBtn.textContent;
        consoleBtn.disabled = true;
        consoleBtn.textContent = 'Abriendo...';
        try {
            // Se abre la pestana antes del await: el navegador solo permite
            // window.open() dentro del gesto del usuario, y un fetch la perderia.
            const tab = window.open('about:blank', '_blank');
            const url = await api.createUiTicket(tenantId, scope);
            if (tab) tab.location = url;
            else window.open(url, '_blank');
        } catch (err) {
            alert('No se pudo abrir ' + label + ': ' + (err.message || err));
        } finally {
            consoleBtn.disabled = false;
            consoleBtn.textContent = original;
        }
    });

    const saveProfileChanges = document.getElementById('btn-save-profile-changes');
    if (saveProfileChanges) {
        saveProfileChanges.addEventListener('click', async () => {
            const selectedTheme = document.getElementById('user-theme-preference').value;
            const newPassword = document.getElementById('input-new-password').value;
            const confirmPassword = document.getElementById('input-confirm-password').value;
            const avatarFile = document.getElementById('input-user-avatar-file')?.files[0];
            
            if (newPassword && newPassword !== confirmPassword) {
                alert("Las contraseñas no coinciden.");
                return;
            }

            localStorage.setItem('user_theme', selectedTheme);
            ui.applyTheme(selectedTheme);

            try {
                const formData = new FormData();
                formData.append('theme', selectedTheme);
                if (newPassword) formData.append('password', newPassword);
                if (avatarFile) formData.append('avatar', avatarFile);

                const token = api.getToken();
                const res = await fetch('/api/v1/auth/theme', {
                    method: 'PUT',
                    headers: { 'Authorization': `Bearer ${token}` },
                    body: formData
                });

                if (res.ok) {
                    const data = await res.json();
                    alert("¡Preferencias guardadas con éxito!");
                    
                    if (data.avatar_url) {
                        const timestamp = new Date().getTime();
                        if (headerAvatar) headerAvatar.src = `${data.avatar_url}?t=${timestamp}`;
                        if (modalAvatar) modalAvatar.src = `${data.avatar_url}?t=${timestamp}`;
                    }
                    ui.toggleModal('profile-modal', false);
                } else {
                    const err = await res.json();
                    alert("Error al actualizar perfil: " + (err.detail || "Error desconocido"));
                }
            } catch (error) {
                console.error(error);
                alert("Error de red al actualizar perfil.");
            }
        });
    }

    const logoutBtn = document.getElementById('btn-logout');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', () => {
            localStorage.clear();
            sessionStorage.clear();
            window.location.href = "/login";
        });
    }

    document.getElementById('btn-open-user-modal')?.addEventListener('click', () => admin.openUserModal());
    document.getElementById('btn-open-tenant-modal')?.addEventListener('click', () => admin.openTenantModal());
    document.getElementById('btn-open-role-modal')?.addEventListener('click', () => admin.openRoleModal());
    document.getElementById('btn-open-profile-modal')?.addEventListener('click', () => admin.openProfileModal());

    document.getElementById('btn-refresh-users')?.addEventListener('click', () => admin.loadUsers());
    document.getElementById('btn-refresh-tenants')?.addEventListener('click', () => admin.loadTenantsAdmin());
    document.getElementById('btn-refresh-roles')?.addEventListener('click', () => admin.loadRolesAdmin());
    document.getElementById('btn-refresh-profiles')?.addEventListener('click', () => admin.loadProfilesAdmin());
    document.getElementById('btn-refresh-infra')?.addEventListener('click', () => admin.loadInfraNodes());

    document.getElementById('btn-save-user')?.addEventListener('click', () => admin.saveUser());
    document.getElementById('btn-save-tenant')?.addEventListener('click', () => admin.saveTenant());
    document.getElementById('btn-save-role')?.addEventListener('click', () => admin.saveRole());
    document.getElementById('btn-save-profile')?.addEventListener('click', () => admin.saveProfile());
    document.getElementById('btn-save-infra')?.addEventListener('click', () => admin.saveInfraNode());
    document.getElementById('btn-save-ai')?.addEventListener('click', () => admin.saveAIConfig());
    document.getElementById('btn-test-ai')?.addEventListener('click', () => admin.testAIProvider());

    document.addEventListener('click', (e) => {
        if (e.target.closest('.btn-edit-user')) {
            const data = JSON.parse(e.target.closest('.btn-edit-user').getAttribute('data-edit-user'));
            admin.openUserModal(data);
        }
        if (e.target.closest('.btn-delete-user')) {
            admin.deleteUser(e.target.closest('.btn-delete-user').getAttribute('data-delete-user'));
        }
        if (e.target.closest('.btn-edit-tenant')) {
            const data = JSON.parse(e.target.closest('.btn-edit-tenant').getAttribute('data-edit-tenant'));
            admin.openTenantModal(data);
        }
        if (e.target.closest('.btn-delete-tenant')) {
            admin.deleteTenant(e.target.closest('.btn-delete-tenant').getAttribute('data-delete-tenant'));
        }
        if (e.target.closest('.btn-edit-role')) {
            const data = JSON.parse(e.target.closest('.btn-edit-role').getAttribute('data-edit-role'));
            admin.openRoleModal(data);
        }
        if (e.target.closest('.btn-delete-role')) {
            admin.deleteRole(e.target.closest('.btn-delete-role').getAttribute('data-delete-role'));
        }
        if (e.target.closest('.btn-edit-profile')) {
            const data = JSON.parse(e.target.closest('.btn-edit-profile').getAttribute('data-edit-profile'));
            admin.openProfileModal(data);
        }
        if (e.target.closest('.btn-delete-profile')) {
            admin.deleteProfile(e.target.closest('.btn-delete-profile').getAttribute('data-delete-profile'));
        }
        if (e.target.closest('.btn-edit-infra')) {
            const data = JSON.parse(e.target.closest('.btn-edit-infra').getAttribute('data-edit-infra'));
            admin.openInfraModal(data);
        }
        if (e.target.closest('.btn-update-infra')) {
            const btnEl = e.target.closest('.btn-update-infra');
            const infraId = btnEl.getAttribute('data-update-infra');
            if (infraId) {
                admin.updateInfraNodeStatus(infraId);
            }
        }
        if (e.target.closest('.btn-delete-infra')) {
            admin.deleteInfraNode(e.target.closest('.btn-delete-infra').getAttribute('data-delete-infra'));
        }
    });
});
