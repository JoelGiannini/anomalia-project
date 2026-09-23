export const api = {
    getToken() {
        return localStorage.getItem("access_token") || sessionStorage.getItem("access_token");
    },

    async fetchUserData() {
        const token = this.getToken();
        const response = await fetch('/api/v1/auth/user', {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        if (response.ok) return await response.json();
        throw new Error("No se pudo obtener el usuario");
    },

    async fetchCatalogs() {
        const token = this.getToken();
        const [rolesRes, tenantsRes, profilesRes] = await Promise.all([
            fetch('/api/v1/admin/roles', { headers: { 'Authorization': `Bearer ${token}` } }),
            fetch('/api/v1/admin/tenants', { headers: { 'Authorization': `Bearer ${token}` } }),
            fetch('/api/v1/admin/profiles', { headers: { 'Authorization': `Bearer ${token}` } })
        ]);
        return {
            roles: rolesRes.ok ? (await rolesRes.json()).roles || [] : [],
            tenants: tenantsRes.ok ? (await tenantsRes.json()).tenants || [] : [],
            profiles: profilesRes.ok ? (await profilesRes.json()).profiles || [] : []
        };
    },

    async fetchUserTenants() {
        const token = this.getToken();
        const res = await fetch('/api/v1/tenants/my-tenants', {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        if (res.ok) {
            const data = await res.json();
            return Array.isArray(data) ? data : (data.tenants || []);
        }
        return [];
    },

    async updateThemeAndPass(theme, password) {
        const token = this.getToken();
        return await fetch('/api/v1/auth/theme', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            body: JSON.stringify({ theme, password: password || undefined })
        });
    }
};
