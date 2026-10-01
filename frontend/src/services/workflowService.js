import api from './api';

/**
 * Workflow Service - Handles all workflow-related API calls
 */
export const workflowService = {
  /**
   * Save or create a workflow.
   *
   * P1.13: optimistic concurrency — pass the version the client last saw
   * via the second arg so the backend can reject stale writes with 409
   * `version_conflict`. Caller is expected to handle 409 by refreshing and
   * retrying.
   */
  save: async (workflow, { version } = {}) => {
    const headers = {};
    if (typeof version === 'number' && Number.isFinite(version)) {
      headers['If-Match'] = String(version);
    }
    const response = await api.post('/workflow/save', workflow, { headers });
    return response.data;
  },

  /**
   * List user's workflows. Pass projectId to scope to a project (omit for legacy per-user).
   */
  list: async (projectId) => {
    const params = projectId ? { project_id: projectId } : undefined;
    const response = await api.get('/workflow/list', { params });
    return response.data;
  },

  /**
   * Get a specific workflow by ID
   */
  get: async (id) => {
    const response = await api.get(`/workflow/${id}`);
    return response.data;
  },

  /**
   * Delete a workflow
   */
  delete: async (id) => {
    const response = await api.delete(`/workflow/${id}`);
    return response.data;
  },

  /**
   * Duplicate a workflow
   */
  duplicate: async (id, name = null) => {
    const response = await api.post(`/workflow/${id}/duplicate`, { name });
    return response.data;
  },

  /**
   * Get workflow templates
   */
  getTemplates: async () => {
    const response = await api.get('/workflow/templates');
    return response.data;
  },

  /**
   * Execute entire workflow
   * Long timeout (650s) to cover video generation polling (up to ~600s backend).
   */
  execute: async (workflowId) => {
    const response = await api.post(
      '/workflow/execute',
      { workflow_id: workflowId },
      { timeout: 650000 }
    );
    return response.data;
  },

  /**
   * Execute workflow from a specific node
   */
  executeFrom: async (workflowId, nodeId) => {
    const response = await api.post(
      '/workflow/execute-from',
      { workflow_id: workflowId, node_id: nodeId },
      { timeout: 650000 }
    );
    return response.data;
  },

  /**
   * Execute only a single node using existing inputs from connected nodes
   * Does NOT re-execute ancestor nodes
   */
  executeSingleNode: async (workflowId, nodeId) => {
    const response = await api.post(
      '/workflow/execute-node',
      { workflow_id: workflowId, node_id: nodeId },
      { timeout: 650000 }
    );
    return response.data;
  },

  /**
   * Get run history for a workflow
   */
  getRuns: async (workflowId) => {
    const response = await api.get(`/workflow/runs/${workflowId}`);
    return response.data;
  }
};
