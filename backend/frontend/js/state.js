import { api } from './api.js';

export const state = {
    globalRolesCache: [],
    globalTenantsCache: [],
    globalProfilesCache: [],
    currentUserRoles: [],
    currentUserProfiles: [],
    // Jobs en vuelo: { job_id: { type, status, phase, progress_pct, error_code } }.
    // El estado real vive en Postgres (job_state); esto es solo la vista para la
    // UI, alimentada por el polling (specs/011 §5.3).
    jobs: {},

    // Registra un job y devuelve su id para que el llamante pueda consultarlo.
    trackJob(jobId, type, status = 'queued') {
        if (!jobId) return null;
        this.jobs[jobId] = { id: jobId, type, status, phase: null, progress_pct: 0, error_code: null };
        return jobId;
    },

    updateJob(jobId, patch) {
        if (this.jobs[jobId]) Object.assign(this.jobs[jobId], patch);
    },

    dropJob(jobId) {
        delete this.jobs[jobId];
    }
};

// Estados terminales de un job: en cuanto se alcanza uno, el polling para.
const JOB_TERMINAL_STATES = new Set(['succeeded', 'failed', 'cancelled']);

const JOB_POLL_INTERVAL_MS = 1500;
const JOB_POLL_TIMEOUT_MS = 5 * 60 * 1000;

/**
 * Consulta el estado de un job hasta que llega a un estado terminal.
 *
 * @param {string} jobId
 * @param {(job: object) => void} [onUpdate] progreso por cada cambio observado
 * @returns {Promise<object>} el último estado conocido del job
 */
export async function pollJob(jobId, onUpdate) {
    const deadline = Date.now() + JOB_POLL_TIMEOUT_MS;

    while (Date.now() < deadline) {
        const job = await api.fetchJob(jobId);
        state.updateJob(jobId, job);
        if (onUpdate) onUpdate(job);
        if (JOB_TERMINAL_STATES.has(job.status)) {
            state.dropJob(jobId);
            return job;
        }
        await new Promise((resolve) => setTimeout(resolve, JOB_POLL_INTERVAL_MS));
    }

    state.dropJob(jobId);
    throw new Error(`El job ${jobId} no terminó dentro del tiempo de espera.`);
}
