import { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import { applyNodeChanges, applyEdgeChanges, addEdge } from 'reactflow';
import { workflowService } from '../../../services/workflowService';
import { useModelCatalog } from '../../../hooks/useModelCatalog';
import { useBudgetBlock } from '../../../hooks/useBudgetBlock';
import { useProject } from '../../../context/ProjectContext';
import { _FALLBACK_IMAGE_GEN_MODELS } from '../../../constants/workflowModels';
import { mapWorkflowError } from '../utils/errorMessages';
import { celebrate } from '../../../utils/confetti';
import { fireReward } from '../../../components/ui/reward-pop';
import toast from 'react-hot-toast';
import i18n from '../../../i18n';

export function useWorkflowState() {
  const { imageGenModels } = useModelCatalog();
  const { currentProject } = useProject();
  // Budget/credit 402 catcher — workflow execute (single node + full run) POSTs
  // via axios and can return 402 once billing_enforcement is on. Route it to the
  // hard-block modal instead of a transient toast.
  const { handleBudgetError, budgetModal } = useBudgetBlock();
  const projectId = currentProject?._id || null;
  // Read the latest projectId via a ref inside callbacks so we don't need to
  // bake it into useCallback deps — keeps existing memoization semantics.
  const projectIdRef = useRef(projectId);
  projectIdRef.current = projectId;

  // Cheapest image-output model from live registry, or first fallback
  const defaultImageGenModelId = useMemo(() => {
    if (imageGenModels.length === 0) return _FALLBACK_IMAGE_GEN_MODELS[0].id;
    const sorted = [...imageGenModels].sort((a, b) => {
      const ap = a.pricing?.completion_per_million ?? Infinity;
      const bp = b.pricing?.completion_per_million ?? Infinity;
      return ap - bp;
    });
    return (sorted[0]._id || sorted[0].id) || _FALLBACK_IMAGE_GEN_MODELS[0].id;
  }, [imageGenModels]);

  const [nodes, setNodes] = useState([]);
  const [edges, setEdges] = useState([]);
  const [selectedWorkflow, setSelectedWorkflow] = useState(null);
  const [workflows, setWorkflows] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [runHistory, setRunHistory] = useState([]);
  const [isExecuting, setIsExecuting] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [lastSavedAt, setLastSavedAt] = useState(null);
  const [workflowName, setWorkflowName] = useState('Untitled Workflow');
  const [workflowDescription, setWorkflowDescription] = useState('');
  const [showLoadModal, setShowLoadModal] = useState(false);
  const [showRunHistory, setShowRunHistory] = useState(false);
  const [loadModalTab, setLoadModalTab] = useState('workflows');
  const [showAIGenerator, setShowAIGenerator] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [contextMenu, setContextMenu] = useState(null);
  const [selectedNodeId, setSelectedNodeId] = useState(null);
  const importFileRef = useRef(null);

  // Refs for dirty-tracking and auto-save debounce
  const isFirstRenderRef = useRef(true);
  const autoSaveTimerRef = useRef(null);
  // suppressDirtyRef: set to true before programmatic node updates (execution results, loads)
  // so the dirty-tracking effect skips them.
  const suppressDirtyRef = useRef(false);
  // selectedWorkflow ref so auto-save effect can read latest value without stale closure
  const selectedWorkflowRef = useRef(null);
  selectedWorkflowRef.current = selectedWorkflow;
  const isExecutingRef = useRef(false);
  isExecutingRef.current = isExecuting;
  const isSavingRef = useRef(false);
  isSavingRef.current = isSaving;

  // Node data update handlers
  const updateNodeData = useCallback((nodeId, updates) => {
    setNodes((nds) =>
      nds.map((node) => {
        if (node.id === nodeId) {
          return { ...node, data: { ...node.data, ...updates } };
        }
        return node;
      })
    );
  }, []);

  const onSelectionChange = useCallback(({ nodes: selectedNodes }) => {
    const nextId = selectedNodes?.[0]?.id ?? null;
    setSelectedNodeId(prev => (prev === nextId ? prev : nextId));
  }, []);

  const selectedNode = useMemo(
    () => nodes.find(n => n.id === selectedNodeId) ?? null,
    [nodes, selectedNodeId]
  );

  // Create node data (no on*Change closures — use updateNodeData(id, {field}) directly)
  const createNodeData = useCallback((nodeId, type, initialData = {}) => {
    if (type === 'imageUpload') {
      return {
        label: initialData.label || 'Image Upload',
        imageUrl: initialData.imageUrl || null,
        lastRunAt: initialData.lastRunAt ?? initialData.last_run_at ?? null,
      };
    } else if (type === 'imageGen') {
      return {
        label: initialData.label || 'Image Generate',
        model: initialData.model || defaultImageGenModelId,
        prompt: initialData.prompt || '',
        negativePrompt: initialData.negativePrompt || '',
        generatedImage: initialData.generatedImage || null,
        aspect_ratio: initialData.aspect_ratio || '1:1',
        style_preset: initialData.style_preset || null,
        isRunning: false,
        lastRunAt: initialData.lastRunAt ?? initialData.last_run_at ?? null,
      };
    } else if (type === 'textInput') {
      return {
        label: initialData.label || 'Text Input',
        text: initialData.text || '',
        placeholder: initialData.placeholder || 'Enter text...',
        lastRunAt: initialData.lastRunAt ?? initialData.last_run_at ?? null,
      };
    } else if (type === 'aiAgent') {
      return {
        label: initialData.label || 'AI Agent',
        model: initialData.model || 'google/gemini-3.6-flash',
        // Support both camelCase (frontend) and snake_case (backend) formats
        systemPrompt: initialData.systemPrompt || initialData.system_prompt || '',
        userPromptTemplate: initialData.userPromptTemplate || initialData.user_prompt_template || '{{input}}',
        output: initialData.output || initialData.generatedText || null,
        textVariants: initialData.textVariants || initialData.text_variants || null,
        // SMM / Copywriter fields (B1–B3)
        knowledgeFolderId: initialData.knowledgeFolderId || initialData.knowledge_folder_id || null,
        variants: initialData.variants ?? 1,
        platformPreset: initialData.platformPreset || initialData.platform_preset || null,
        maxChars: initialData.maxChars ?? initialData.max_chars ?? null,
        isRunning: false,
        lastRunAt: initialData.lastRunAt ?? initialData.last_run_at ?? null,
      };
    } else if (type === 'ttsNode') {
      return {
        label: initialData.label || 'Text to Speech',
        text: initialData.text || '',
        model: initialData.model || 'openai/gpt-4o-mini-tts-2025-12-15',
        voice: initialData.voice || 'alloy',
        speed: typeof initialData.speed === 'number' ? initialData.speed : 1.0,
        audioDataUri: initialData.audioDataUri || initialData.audio_data_uri || null,
        audioId: initialData.audioId || initialData.audio_id || null,
        durationMs: initialData.durationMs ?? initialData.duration_ms ?? null,
        isRunning: false,
        lastRunAt: initialData.lastRunAt ?? initialData.last_run_at ?? null,
      };
    } else if (type === 'videoGenNode') {
      return {
        label: initialData.label || 'Video Generate',
        model: initialData.model || 'google/veo-3.1',
        prompt: initialData.prompt || '',
        duration: typeof initialData.duration === 'number' ? initialData.duration : 8,
        resolution: initialData.resolution || '1080p',
        aspectRatio: initialData.aspectRatio || initialData.aspect_ratio || '16:9',
        generateAudio: initialData.generateAudio !== undefined
          ? initialData.generateAudio
          : (initialData.generate_audio !== undefined ? initialData.generate_audio : true),
        seed: initialData.seed ?? null,
        videoUrl: initialData.videoUrl || initialData.video_url || null,
        videoId: initialData.videoId || initialData.video_id || null,
        durationSec: initialData.durationSec ?? initialData.duration_sec ?? null,
        status: initialData.status || null,
        error: initialData.error || null,
        isRunning: false,
        lastRunAt: initialData.lastRunAt ?? initialData.last_run_at ?? null,
      };
    }
    return { ...initialData, lastRunAt: initialData.lastRunAt ?? initialData.last_run_at ?? null };
  }, [updateNodeData, defaultImageGenModelId]);

  // Prepare nodes for saving (remove callback functions)
  const prepareNodesForSave = useCallback((nodesToSave) => {
    return nodesToSave.map((node) => ({
      ...node,
      data: {
        label: node.data.label,
        // imageUpload fields
        imageUrl: node.data.imageUrl,
        // imageGen fields
        model: node.data.model,
        prompt: node.data.prompt,
        negativePrompt: node.data.negativePrompt,
        generatedImage: node.data.generatedImage,
        aspect_ratio: node.data.aspect_ratio,
        style_preset: node.data.style_preset,
        // textInput fields
        text: node.data.text,
        placeholder: node.data.placeholder,
        // aiAgent fields (snake_case for backend compatibility)
        system_prompt: node.data.systemPrompt,
        user_prompt_template: node.data.userPromptTemplate,
        generatedText: node.data.output,
        // SMM / Copywriter fields (B1–B3)
        knowledge_folder_id: node.data.knowledgeFolderId,
        variants: node.data.variants,
        platform_preset: node.data.platformPreset,
        max_chars: node.data.maxChars,
        text_variants: node.data.textVariants,
        // ttsNode fields
        voice: node.data.voice,
        speed: node.data.speed,
        audio_data_uri: node.data.audioDataUri,
        audio_id: node.data.audioId,
        duration_ms: node.data.durationMs,
        // videoGenNode fields
        duration: node.data.duration,
        resolution: node.data.resolution,
        aspect_ratio: node.data.aspectRatio,
        generate_audio: node.data.generateAudio,
        seed: node.data.seed,
        video_url: node.data.videoUrl,
        video_id: node.data.videoId,
        duration_sec: node.data.durationSec,
        // run tracking
        lastRunAt: node.data.lastRunAt,
      },
    }));
  }, []);

  // Restore node callbacks after loading
  const restoreNodeCallbacks = useCallback((loadedNodes) => {
    return loadedNodes.map((node) => ({
      ...node,
      data: createNodeData(node.id, node.type, node.data),
    }));
  }, [createNodeData]);

  // Add new node
  const addNode = useCallback((type) => {
    const nodeId = `${type}-${Date.now()}`;
    const newNode = {
      id: nodeId,
      type: type,
      position: { x: Math.random() * 300 + 100, y: Math.random() * 200 + 100 },
      data: createNodeData(nodeId, type),
    };
    setNodes((nds) => [...nds, newNode]);
  }, [createNodeData]);

  // Duplicate a node
  const duplicateNode = useCallback((nodeId) => {
    const node = nodes.find((n) => n.id === nodeId);
    if (!node) return;

    const newNodeId = `${node.type}-${Date.now()}`;
    const newNode = {
      id: newNodeId,
      type: node.type,
      position: { x: node.position.x + 50, y: node.position.y + 50 },
      data: createNodeData(newNodeId, node.type, {
        ...node.data,
        generatedImage: null,
      }),
    };
    setNodes((nds) => [...nds, newNode]);
    toast.success(i18n.t('common:runtime.workflow.nodeDuplicated'));
  }, [nodes, createNodeData]);

  // Delete a node
  const deleteNode = useCallback((nodeId) => {
    setNodes((nds) => nds.filter((n) => n.id !== nodeId));
    setEdges((eds) => eds.filter((e) => e.source !== nodeId && e.target !== nodeId));
    toast.success(i18n.t('common:runtime.workflow.nodeDeleted'));
  }, []);

  // React Flow callbacks
  const onNodesChange = useCallback(
    (changes) => setNodes((nds) => applyNodeChanges(changes, nds)),
    []
  );

  const onEdgesChange = useCallback(
    (changes) => setEdges((eds) => applyEdgeChanges(changes, eds)),
    []
  );

  const onConnect = useCallback(
    (params) => setEdges((eds) => addEdge(params, eds)),
    []
  );

  // Context menu
  const onNodeContextMenu = useCallback((event, node) => {
    event.preventDefault();
    setContextMenu({
      x: event.clientX,
      y: event.clientY,
      nodeId: node.id,
      nodeType: node.type,
    });
  }, []);

  const closeContextMenu = useCallback(() => {
    setContextMenu(null);
  }, []);

  // Load workflows list (scoped to active project so the load modal
  // can group "Project" workflows separately from personal ones).
  const loadWorkflowsList = async () => {
    try {
      const data = await workflowService.list(projectIdRef.current || undefined);
      setWorkflows(data.workflows || []);
    } catch (error) {
      console.error('Error loading workflows:', error);
    }
  };

  // Load templates list
  const loadTemplatesList = async () => {
    try {
      const data = await workflowService.getTemplates();
      setTemplates(data.templates || []);
    } catch (error) {
      console.error('Error loading templates:', error);
    }
  };

  // Load run history
  const loadRunHistory = async () => {
    if (!selectedWorkflow) return;
    try {
      const data = await workflowService.getRuns(selectedWorkflow._id);
      setRunHistory(data.runs || []);
    } catch (error) {
      console.error('Error loading run history:', error);
    }
  };

  // Create new workflow
  const createNewWorkflow = useCallback(() => {
    suppressDirtyRef.current = true;
    setNodes([]);
    setEdges([]);
    setSelectedWorkflow(null);
    setWorkflowName('Untitled Workflow');
    setWorkflowDescription('');
    // Flush dirty state after React batches the setNodes/setEdges above
    queueMicrotask(() => {
      setHasUnsavedChanges(false);
      setLastSavedAt(null);
    });
    toast.success(i18n.t('common:runtime.workflow.created'));
  }, []);

  // Save workflow — returns { ok: true, workflow } or { ok: false, error }
  // Manages isSaving state internally so callers can abort on failure.
  // Pass { silent: true } to skip success toast (used by auto-save).
  const saveWorkflow = useCallback(async ({ silent = false } = {}) => {
    if (!workflowName.trim()) {
      if (!silent) toast.error(i18n.t('common:runtime.workflow.enterName'));
      return { ok: false, error: 'No name' };
    }

    setIsSaving(true);
    try {
      const workflowData = {
        name: workflowName,
        description: workflowDescription,
        nodes: prepareNodesForSave(nodes),
        edges: edges,
      };

      // P1.13: track optimistic version so the backend can reject stale
      // writes. For never-saved workflows we have no version yet.
      let knownVersion;
      if (selectedWorkflow) {
        workflowData.id = selectedWorkflow._id;
        if (typeof selectedWorkflow.version === 'number') {
          knownVersion = selectedWorkflow.version;
        }
      } else {
        // New workflow: pin to active project. Backend rejects reassignment
        // on existing workflows (cannot_reassign_project), so only send on
        // creation. null is valid (= unfiled in current workspace).
        workflowData.project_id = projectIdRef.current;
      }

      let result;
      try {
        result = await workflowService.save(workflowData, { version: knownVersion });
      } catch (err) {
        // P1.13: surface 409 version conflicts to the user so concurrent
        // edits from another tab don't silently get clobbered. Auto-save
        // attempts also stop on this branch — user can refresh to recover.
        if (err?.response?.status === 409 && err?.response?.data?.code === 'version_conflict') {
          // P1.13: dedicated i18n key may not be wired yet — fall back to a
          // saveFailed string so the user still sees the toast.
          const conflictKey = 'common:runtime.workflow.versionConflict';
          const translated = i18n.t(conflictKey);
          const msg = translated === conflictKey
            ? i18n.t('common:runtime.workflow.saveFailed')
            : translated;
          if (!silent) toast.error(msg);
          else console.warn('[workflow] silent save aborted: stale version', err.response.data);
          return { ok: false, error: 'version_conflict', code: 'version_conflict' };
        }
        throw err;
      }
      setSelectedWorkflow(result.workflow);
      setHasUnsavedChanges(false);
      setLastSavedAt(Date.now());
      if (!silent) toast.success(i18n.t('common:runtime.workflow.saved', { name: workflowName }));
      loadWorkflowsList();
      return { ok: true, workflow: result.workflow };
    } catch (error) {
      console.error('Error saving workflow:', error);
      // Always surface failures even on silent saves so user isn't lost
      toast.error(i18n.t('common:runtime.workflow.saveFailed'));
      return { ok: false, error };
    } finally {
      setIsSaving(false);
    }
  }, [workflowName, workflowDescription, nodes, edges, selectedWorkflow, prepareNodesForSave]);

  // Load workflow
  const loadWorkflow = useCallback(async (workflow) => {
    try {
      const data = await workflowService.get(workflow._id);
      const wf = data.workflow;
      suppressDirtyRef.current = true;
      setNodes(restoreNodeCallbacks(wf.nodes || []));
      setEdges(wf.edges || []);
      setSelectedWorkflow(wf);
      setWorkflowName(wf.name);
      setWorkflowDescription(wf.description || '');
      setShowLoadModal(false);
      // Server state matches — not dirty, mark as saved now
      queueMicrotask(() => {
        setHasUnsavedChanges(false);
        setLastSavedAt(Date.now());
      });
      toast.success(i18n.t('common:runtime.workflow.loaded', { name: wf.name }));
    } catch (error) {
      console.error('Error loading workflow:', error);
      toast.error(i18n.t('common:runtime.workflow.loadFailed'));
    }
  }, [restoreNodeCallbacks]);

  // Load template
  const loadTemplate = useCallback((template) => {
    try {
      suppressDirtyRef.current = true;
      setNodes(restoreNodeCallbacks(template.nodes || []));
      setEdges(template.edges || []);
      setSelectedWorkflow(null);
      setWorkflowName(`${template.name} (Copy)`);
      setWorkflowDescription(template.description || '');
      setShowLoadModal(false);
      // Template copy is unsaved — no _id yet, so auto-save won't fire
      queueMicrotask(() => {
        setHasUnsavedChanges(false);
        setLastSavedAt(null);
      });
      toast.success(i18n.t('common:runtime.workflow.templateLoaded', { name: template.name }));
    } catch (error) {
      console.error('Error loading template:', error);
      toast.error(i18n.t('common:runtime.workflow.templateLoadFailed'));
    }
  }, [restoreNodeCallbacks]);

  // Delete workflow
  const deleteWorkflow = useCallback(() => {
    if (!selectedWorkflow) {
      toast.error(i18n.t('common:runtime.workflow.noWorkflowSelected'));
      return;
    }
    setShowDeleteConfirm(true);
  }, [selectedWorkflow]);

  const handleDeleteWorkflow = useCallback(async () => {
    try {
      await workflowService.delete(selectedWorkflow._id);
      createNewWorkflow();
      loadWorkflowsList();
      toast.success(i18n.t('common:runtime.workflow.deleted'));
    } catch (error) {
      console.error('Error deleting workflow:', error);
      toast.error(i18n.t('common:runtime.workflow.deleteFailed'));
    }
  }, [selectedWorkflow, createNewWorkflow]);

  // Duplicate workflow
  const duplicateWorkflow = useCallback(async () => {
    if (!selectedWorkflow) {
      toast.error(i18n.t('common:runtime.workflow.noWorkflowSelected'));
      return;
    }

    try {
      const result = await workflowService.duplicate(selectedWorkflow._id);
      const wf = result.workflow;
      suppressDirtyRef.current = true;
      setNodes(restoreNodeCallbacks(wf.nodes || []));
      setEdges(wf.edges || []);
      setSelectedWorkflow(wf);
      setWorkflowName(wf.name);
      setWorkflowDescription(wf.description || '');
      // Duplicate is server-saved; mark as clean
      queueMicrotask(() => {
        setHasUnsavedChanges(false);
        setLastSavedAt(Date.now());
      });
      loadWorkflowsList();
      toast.success(i18n.t('common:runtime.workflow.duplicated', { name: wf.name }));
    } catch (error) {
      console.error('Error duplicating workflow:', error);
      toast.error(i18n.t('common:runtime.workflow.duplicateFailed'));
    }
  }, [selectedWorkflow, restoreNodeCallbacks]);

  // Export workflow
  const exportWorkflow = useCallback(() => {
    if (nodes.length === 0) {
      toast.error(i18n.t('common:runtime.workflow.noNodesToExport'));
      return;
    }

    const workflowData = {
      name: workflowName,
      description: workflowDescription,
      nodes: prepareNodesForSave(nodes),
      edges: edges,
      exportedAt: new Date().toISOString(),
      version: '1.0'
    };

    const blob = new Blob([JSON.stringify(workflowData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${workflowName.replace(/[^a-z0-9]/gi, '_')}.json`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success(i18n.t('common:runtime.workflow.exported'));
  }, [workflowName, workflowDescription, nodes, edges, prepareNodesForSave]);

  // Import workflow
  const importWorkflow = useCallback((event) => {
    const file = event.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const data = JSON.parse(e.target.result);
        if (!data.name || !Array.isArray(data.nodes) || !Array.isArray(data.edges)) {
          throw new Error(i18n.t('common:runtime.workflow.invalidFormat'));
        }
        suppressDirtyRef.current = true;
        setNodes(restoreNodeCallbacks(data.nodes));
        setEdges(data.edges);
        setWorkflowName(data.name);
        setWorkflowDescription(data.description || '');
        setSelectedWorkflow(null);
        // Imported file not yet in server — treat as unsaved new
        queueMicrotask(() => {
          setHasUnsavedChanges(false);
          setLastSavedAt(null);
        });
        toast.success(i18n.t('common:runtime.workflow.imported', { name: data.name }));
      } catch (error) {
        console.error('Error importing workflow:', error);
        toast.error(i18n.t('common:runtime.workflow.importFailed'));
      }
    };
    reader.readAsText(file);
    event.target.value = '';
  }, [restoreNodeCallbacks]);

  // Execute single node
  const executeSingleNode = useCallback(async (nodeId) => {
    if (!selectedWorkflow) {
      toast.error(i18n.t('common:runtime.workflow.saveBeforeExecute'));
      return;
    }

    // Save before run — abort if save fails
    const saveResult = await saveWorkflow({ silent: true });
    if (!saveResult?.ok) return;

    suppressDirtyRef.current = true;
    setNodes((nds) =>
      nds.map((node) => {
        if (node.id === nodeId) {
          return { ...node, data: { ...node.data, isRunning: true, hasError: false, errorMessage: null } };
        }
        return node;
      })
    );

    try {
      const result = await workflowService.executeSingleNode(selectedWorkflow._id, nodeId);
      suppressDirtyRef.current = true;
      setNodes((nds) =>
        nds.map((node) => {
          if (node.id === nodeId) {
            const updates = { isRunning: false, error: null, hasError: false, errorMessage: null, lastRunAt: Date.now() };
            // Handle image output (imageGen nodes)
            if (result.image_data) {
              updates.generatedImage = result.image_data;
            }
            // Handle text output (aiAgent nodes)
            if (result.text !== undefined) {
              updates.output = result.text;
            }
            if (result.text_variants !== undefined) {
              updates.textVariants = result.text_variants;
            }
            // Handle audio output (ttsNode)
            if (result.audio_data_uri) {
              updates.audioDataUri = result.audio_data_uri;
              updates.audioId = result.audio_id || null;
              updates.durationMs = result.duration_ms ?? null;
            }
            // Handle video output (videoGenNode)
            if (result.video_url) {
              updates.videoUrl = result.video_url;
              updates.videoId = result.video_id || null;
              updates.durationSec = result.duration_sec ?? null;
              if (result.resolution) updates.resolution = result.resolution;
              updates.status = 'completed';
            }
            return {
              ...node,
              data: { ...node.data, ...updates },
            };
          }
          return node;
        })
      );
      toast.success(i18n.t('common:runtime.workflow.nodeExecuted'));
      // Fire-and-forget post-run save; result ignored intentionally
      setTimeout(() => saveWorkflow({ silent: true }), 500);
    } catch (error) {
      console.error('Error executing single node:', error);
      const isBudget = handleBudgetError(error.response?.data);
      const rawError = error.response?.data?.error || error.message || 'Failed to execute node';
      const friendly = mapWorkflowError(rawError);
      if (!isBudget) toast.error(friendly);
      suppressDirtyRef.current = true;
      setNodes((nds) =>
        nds.map((node) => {
          if (node.id === nodeId) {
            return {
              ...node,
              data: {
                ...node.data,
                isRunning: false,
                hasError: true,
                errorMessage: friendly,
              },
            };
          }
          return node;
        })
      );
    }
  }, [selectedWorkflow, saveWorkflow, handleBudgetError]);

  // Execute workflow
  const executeWorkflow = useCallback(async () => {
    if (!selectedWorkflow) {
      toast.error(i18n.t('common:runtime.workflow.saveBeforeExecute'));
      return;
    }

    // Save before run — abort if save fails
    const saveResult = await saveWorkflow({ silent: true });
    if (!saveResult?.ok) return;

    setIsExecuting(true);

    const isExecutableType = (t) =>
      t === 'imageGen' || t === 'aiAgent' || t === 'ttsNode' || t === 'videoGenNode';

    suppressDirtyRef.current = true;
    setNodes((nds) =>
      nds.map((node) => {
        if (isExecutableType(node.type)) {
          return { ...node, data: { ...node.data, isRunning: true, error: null } };
        }
        return node;
      })
    );

    try {
      const result = await workflowService.execute(selectedWorkflow._id);

      if (result.node_results) {
        suppressDirtyRef.current = true;
        setNodes((nds) =>
          nds.map((node) => {
            const nodeResult = result.node_results[node.id];
            if (nodeResult) {
              const updates = { isRunning: false, error: null };
              // Handle image output (imageGen nodes)
              if (nodeResult.image_data) {
                updates.generatedImage = nodeResult.image_data;
              }
              // Handle text output (aiAgent nodes)
              if (nodeResult.text !== undefined) {
                updates.output = nodeResult.text;
              }
              if (nodeResult.text_variants !== undefined) {
                updates.textVariants = nodeResult.text_variants;
              }
              // Handle audio output (ttsNode)
              if (nodeResult.audio_data_uri) {
                updates.audioDataUri = nodeResult.audio_data_uri;
                updates.audioId = nodeResult.audio_id || null;
                updates.durationMs = nodeResult.duration_ms ?? null;
              }
              // Handle video output (videoGenNode)
              if (nodeResult.video_url) {
                updates.videoUrl = nodeResult.video_url;
                updates.videoId = nodeResult.video_id || null;
                updates.durationSec = nodeResult.duration_sec ?? null;
                if (nodeResult.resolution) updates.resolution = nodeResult.resolution;
                updates.status = 'completed';
              }
              // Surface per-node error if backend provides one
              if (nodeResult.error) {
                updates.error = nodeResult.error;
                updates.hasError = true;
                updates.errorMessage = mapWorkflowError(nodeResult.error);
                if (node.type === 'videoGenNode') updates.status = 'failed';
              } else {
                // Clear any previous error state on successful node
                updates.hasError = false;
                updates.errorMessage = null;
                // Only stamp lastRunAt on successful node results
                updates.lastRunAt = Date.now();
              }
              return {
                ...node,
                data: { ...node.data, ...updates },
              };
            }
            if (isExecutableType(node.type)) {
              return { ...node, data: { ...node.data, isRunning: false } };
            }
            return node;
          })
        );
      }

      if (result.status === 'completed') {
        toast.success(i18n.t('common:runtime.workflow.executionCompleted'));
        // Celebrate a full successful run (once — not per node, not on failure).
        celebrate();
        fireReward('trophy');
        // Fire-and-forget post-run save; result ignored intentionally
        setTimeout(() => saveWorkflow({ silent: true }), 500);
      } else if (result.status === 'failed') {
        toast.error(result.error || i18n.t('common:runtime.workflow.executionFailed'));
      }
      loadRunHistory();
    } catch (error) {
      console.error('Error executing workflow:', error);
      if (!handleBudgetError(error.response?.data)) {
        const errorMessage = error.response?.data?.error || error.message || 'Failed to execute workflow';
        toast.error(errorMessage);
      }
      suppressDirtyRef.current = true;
      setNodes((nds) =>
        nds.map((node) => {
          if (isExecutableType(node.type)) {
            return { ...node, data: { ...node.data, isRunning: false } };
          }
          return node;
        })
      );
    } finally {
      setIsExecuting(false);
    }
  }, [selectedWorkflow, saveWorkflow, handleBudgetError]);

  // Handle AI-generated workflow
  const handleAIGeneratedWorkflow = useCallback((workflow) => {
    const nodesWithCallbacks = workflow.nodes.map(node => ({
      ...node,
      data: createNodeData(node.id, node.type, node.data)
    }));

    suppressDirtyRef.current = true;
    setNodes(nodesWithCallbacks);
    setEdges(workflow.edges || []);
    setWorkflowName(workflow.name || 'AI Generated Workflow');
    setWorkflowDescription(workflow.description || '');
    setSelectedWorkflow(null);
    setShowAIGenerator(false);
    // AI-generated workflow has no _id yet — treat like template
    queueMicrotask(() => {
      setHasUnsavedChanges(false);
      setLastSavedAt(null);
    });
    toast.success(i18n.t('common:runtime.workflow.generated'));
  }, [createNodeData]);

  // Mark dirty on nodes/edges/name/description changes (skip very first render,
  // programmatic updates from execution results / loads, and react-flow's
  // selection / dragging / measurement updates that don't change actual content).
  const lastDirtySnapshotRef = useRef(null);
  useEffect(() => {
    // Build a snapshot of fields that count as "real" changes — exclude
    // selected/dragging/positionAbsolute/width/height/measured which react-flow
    // mutates on every click/hover/measure.
    const snapshot = JSON.stringify({
      nodes: nodes.map((n) => {
        // Strip fields that don't represent real user-authored changes before
        // serializing — this runs on EVERY setNodes, i.e. once per pointermove
        // while dragging:
        //  - volatile execution flags: isRunning toggles during a run;
        //    status/progress mutate on cloud polls.
        //  - heavy execution OUTPUTS (base64/data-URI blobs, 200KB–1MB each):
        //    generatedImage, audioDataUri, videoUrl, output. Re-stringifying
        //    these every drag frame is the perf cost; they're never edited by
        //    the user (only written by run results) so they can't gate dirty.
        // These are still PERSISTED on a real save (see prepareNodesForSave);
        // we only exclude them from the dirty-CHECK comparison.
        const {
          isRunning,
          status,
          progress,
          generatedImage,
          audioDataUri,
          videoUrl,
          output,
          ...restData
        } = n.data || {};
        return {
          id: n.id,
          type: n.type,
          position: n.position,
          data: restData,
        };
      }),
      edges: edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        sourceHandle: e.sourceHandle,
        targetHandle: e.targetHandle,
      })),
      workflowName,
      workflowDescription,
    });

    if (isFirstRenderRef.current) {
      isFirstRenderRef.current = false;
      lastDirtySnapshotRef.current = snapshot;
      return;
    }
    if (suppressDirtyRef.current) {
      suppressDirtyRef.current = false;
      lastDirtySnapshotRef.current = snapshot;
      return;
    }
    if (lastDirtySnapshotRef.current === snapshot) return;
    lastDirtySnapshotRef.current = snapshot;
    setHasUnsavedChanges(true);
  }, [nodes, edges, workflowName, workflowDescription]);

  // Debounced auto-save: fires for both new and existing workflows.
  // For a never-saved workflow, requires at least one node so a stub
  // workflow isn't created from a stray name edit on an empty canvas.
  // Uses refs to read latest values without making saveWorkflow a dep (avoiding re-trigger loop).
  useEffect(() => {
    if (!hasUnsavedChanges) return;
    if (isExecutingRef.current || isSavingRef.current) return;
    const hasId = !!selectedWorkflowRef.current?._id;
    if (!hasId && nodes.length === 0) return;

    if (autoSaveTimerRef.current) clearTimeout(autoSaveTimerRef.current);
    autoSaveTimerRef.current = setTimeout(() => {
      if (isExecutingRef.current || isSavingRef.current) return;
      const stillHasId = !!selectedWorkflowRef.current?._id;
      if (!stillHasId && nodes.length === 0) return;
      saveWorkflow({ silent: true });
    }, 5000);

    return () => {
      if (autoSaveTimerRef.current) clearTimeout(autoSaveTimerRef.current);
    };
  }, [hasUnsavedChanges, nodes.length, saveWorkflow]);

  // Initial load
  useEffect(() => {
    loadWorkflowsList();
    loadTemplatesList();
  }, []);

  // Load run history when needed
  useEffect(() => {
    if (selectedWorkflow && showRunHistory) {
      loadRunHistory();
    }
  }, [selectedWorkflow, showRunHistory]);

  return {
    // State
    nodes,
    edges,
    selectedWorkflow,
    workflows,
    templates,
    runHistory,
    isExecuting,
    isSaving,
    hasUnsavedChanges,
    lastSavedAt,
    workflowName,
    workflowDescription,
    showLoadModal,
    showRunHistory,
    loadModalTab,
    showAIGenerator,
    showDeleteConfirm,
    contextMenu,
    importFileRef,

    // Setters
    setWorkflowName,
    setWorkflowDescription,
    setShowLoadModal,
    setShowRunHistory,
    setLoadModalTab,
    setShowAIGenerator,
    setShowDeleteConfirm,

    // Selection state
    selectedNodeId,
    selectedNode,
    setSelectedNodeId,
    onSelectionChange,

    // React Flow handlers
    onNodesChange,
    onEdgesChange,
    onConnect,
    onNodeContextMenu,
    closeContextMenu,

    // Node handlers
    addNode,
    duplicateNode,
    deleteNode,
    executeSingleNode,
    updateNodeData,

    // Workflow handlers
    createNewWorkflow,
    saveWorkflow,
    loadWorkflow,
    loadTemplate,
    deleteWorkflow,
    handleDeleteWorkflow,
    duplicateWorkflow,
    exportWorkflow,
    importWorkflow,
    executeWorkflow,
    handleAIGeneratedWorkflow,
    loadWorkflowsList,
    loadRunHistory,

    // Budget/credit 402 hard-block modal element (render in the page tree).
    budgetModal,
  };
}
