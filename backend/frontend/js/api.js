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

    async createUiTicket(tenantId, scope) {
        const token = this.getToken();
        const res = await fetch('/api/v1/ui/ticket', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            body: JSON.stringify({ tenant_id: tenantId, scope })
        });
        if (!res.ok) {
            let detail = '';
            try { detail = (await res.json()).detail || ''; } catch (_) { /* sin cuerpo */ }
            throw new Error(detail || 'No se pudo abrir la consola de telemetría');
        }
        const data = await res.json();
        if (!data.url) throw new Error('El backend no devolvió una URL de consola');
        return data.url;
    },

    async updateThemeAndPass(theme, password) {
        const token = this.getToken();
        return await fetch('/api/v1/auth/theme', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            body: JSON.stringify({ theme, password: password || undefined })
        });
    },

    async getAIProviders() {
        const token = this.getToken();
        const res = await fetch('/api/v1/ai/providers', {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        if (!res.ok) throw new Error('No se pudo obtener el catálogo de proveedores IA');
        return await res.json();
    },

    async getAIConfig() {
        const token = this.getToken();
        const res = await fetch('/api/v1/ai/config', {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        if (!res.ok) throw new Error('No se pudo obtener la configuración de IA');
        return await res.json();
    },

    async saveAIConfig(payload) {
        const token = this.getToken();
        const res = await fetch('/api/v1/ai/config', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            body: JSON.stringify(payload)
        });
        if (!res.ok) {
            let detail = '';
            try { detail = (await res.json()).detail || ''; } catch (_) { /* sin cuerpo */ }
            throw new Error(detail || 'No se pudo guardar la configuración de IA');
        }
        return await res.json();
    },

    async testAIProvider(provider) {
        const token = this.getToken();
        const res = await fetch('/api/v1/ai/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            body: JSON.stringify(provider ? { provider } : {})
        });
        if (!res.ok) {
            let detail = '';
            try { detail = (await res.json()).detail || ''; } catch (_) { /* sin cuerpo */ }
            throw new Error(detail || 'No se pudo probar el proveedor IA');
        }
        return await res.json();
    },

    async getGeminiModels() {
        const token = this.getToken();
        const res = await fetch('/api/v1/ai/gemini-models', {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        if (!res.ok) throw new Error('No se pudo obtener los modelos de Gemini');
        return await res.json();
    }
};
