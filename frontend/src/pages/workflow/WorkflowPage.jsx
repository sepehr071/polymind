import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import ReactFlow, {
  Background,
  MiniMap,
  ReactFlowProvider,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { Layers, X, Workflow as WorkflowIcon, Wand2, LayoutTemplate, MousePointer2 } from 'lucide-react';
import EmptyState from '@/components/ui/empty-state';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent } from '@/components/ui/dialog';
import { PrivacyBanner } from '@/components/privacy/ModelPrivacyCallout';
import { cn } from '@/lib/utils';
import { useMediaQuery } from '@/hooks/useMediaQuery';
import { GLASS_CLASS, CANVAS_OVERLAY_GLASS_STYLE } from './components/canvasOverlayGlass';

import {
  ImageUploadNode,
  ImageGenNode,
  TextInputNode,
  AIAgentNode,
  TTSNode,
  VideoGenNode,
  NodeContextMenu,
  WorkflowGenerator,
  PersonaBuilderNode,
  SEOBriefNode,
  HashtagPackNode,
  AudienceMatchNode,
  APICallNode,
  JSONTransformNode,
  CodeRunnerNode,
  GitActionNode,
  WebhookTriggerNode,
  CronScheduleNode,
  BranchConditionNode,
  HTTPRequestNode,
} from '../../components/workflow';
import { useConfirmDelete } from '@/hooks/useConfirmDelete';
import { LoadWorkflowModal } from './components';
import {
  WorkflowBreadcrumb,
  NodeRail,
  NodeInspector,
  CanvasCommandBar,
  CanvasZoomBar,
  RunHistoryPanel,
} from './components';
import { useWorkflowState } from './hooks/useWorkflowState';

// Define node types outside component to prevent re-creation on render
const nodeTypes = {
  imageUpload: ImageUploadNode,
  imageGen: ImageGenNode,
  textInput: TextInputNode,
  aiAgent: AIAgentNode,
  ttsNode: TTSNode,
  videoGenNode: VideoGenNode,
  // Showcase (UI-only, server-side raises NotImplementedError)
  personaBuilderNode: PersonaBuilderNode,
  seoBriefNode: SEOBriefNode,
  hashtagPackNode: HashtagPackNode,
  audienceMatchNode: AudienceMatchNode,
  apiCallNode: APICallNode,
  jsonTransformNode: JSONTransformNode,
  codeRunnerNode: CodeRunnerNode,
  gitActionNode: GitActionNode,
  webhookTriggerNode: WebhookTriggerNode,
  cronScheduleNode: CronScheduleNode,
  branchConditionNode: BranchConditionNode,
  httpRequestNode: HTTPRequestNode,
};

function WorkflowEditor() {
  const { t } = useTranslation('workflow');
  // Shared media-query hook (don't reinvent isMobile). `< md` (768px) is mobile.
  const isMobile = !useMediaQuery('(min-width: 768px)');
  const [showMobileSidebar, setShowMobileSidebar] = useState(false);

  // Right-click hint chip — dismissed forever via localStorage
  const [rclickHintDismissed, setRclickHintDismissed] = useState(
    () => typeof window !== 'undefined' &&
      localStorage.getItem('workflow-rclick-hint-dismissed') === '1'
  );
  const dismissRclickHint = () => {
    localStorage.setItem('workflow-rclick-hint-dismissed', '1');
    setRclickHintDismissed(true);
  };

  // Close the mobile node-rail overlay when we cross back to desktop.
  useEffect(() => {
    if (!isMobile) setShowMobileSidebar(false);
  }, [isMobile]);

  const {
    // State
    nodes,
    edges,
    selectedWorkflow,
    workflows,
    templates,
    runHistory,
    isExecuting,
    workflowName,
    showLoadModal,
    showRunHistory,
    loadModalTab,
    showAIGenerator,
    showDeleteConfirm,
    contextMenu,
    importFileRef,
    selectedNodeId,
    selectedNode,

    // New fields from state-hook agent (wired through to breadcrumb)
    isSaving,
    hasUnsavedChanges,
    lastSavedAt,

    // Setters
    setWorkflowName,
    setShowLoadModal,
    setShowRunHistory,
    setLoadModalTab,
    setShowAIGenerator,
    setShowDeleteConfirm,
    setSelectedNodeId,

    // React Flow handlers
    onNodesChange,
    onEdgesChange,
    onConnect,
    onNodeContextMenu,
    onSelectionChange,
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

    // Budget/credit 402 hard-block modal element.
    budgetModal,
  } = useWorkflowState();

  const { confirm, confirmDialog } = useConfirmDelete();

  // Bridge the hook's boolean delete flag to the promise-based confirm dialog.
  // `deleteWorkflow` (fired from the breadcrumb) flips showDeleteConfirm true;
  // we open the modal, reset the flag immediately, then run the delete on OK.
  useEffect(() => {
    if (!showDeleteConfirm) return;
    setShowDeleteConfirm(false);
    confirm({
      title: t('deleteDialog.title'),
      description: t('deleteDialog.message', { name: workflowName }),
      confirmLabel: t('deleteDialog.confirm'),
      cancelLabel: t('deleteDialog.cancel'),
      destructive: true,
    }).then((ok) => {
      if (ok) handleDeleteWorkflow();
    });
  }, [showDeleteConfirm, setShowDeleteConfirm, confirm, handleDeleteWorkflow, workflowName, t]);

  const handleToggleHistory = () => {
    setShowRunHistory((prev) => {
      if (!prev) loadRunHistory();
      return !prev;
    });
  };

  const handleDrop = (e) => {
    e.preventDefault();
    const type = e.dataTransfer.getData('application/reactflow');
    if (type) addNode(type);
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  };

  return (
    <div className="workflow-surface h-full flex flex-col bg-background">
      {/* Breadcrumb / top bar */}
      <WorkflowBreadcrumb
        workflowName={workflowName}
        onWorkflowNameChange={setWorkflowName}
        selectedWorkflow={selectedWorkflow}
        nodes={nodes}
        isExecuting={isExecuting}
        onRun={executeWorkflow}
        onToggleHistory={handleToggleHistory}
        showRunHistory={showRunHistory}
        onNew={createNewWorkflow}
        onSave={saveWorkflow}
        onLoad={() => { loadWorkflowsList(); setShowLoadModal(true); }}
        onDuplicate={duplicateWorkflow}
        onDelete={deleteWorkflow}
        onImport={importWorkflow}
        onExport={exportWorkflow}
        importFileRef={importFileRef}
        isSaving={isSaving}
        hasUnsavedChanges={hasUnsavedChanges}
        lastSavedAt={lastSavedAt}
        onOpenTemplates={() => {
          loadWorkflowsList();
          setLoadModalTab('templates');
          setShowLoadModal(true);
        }}
        onOpenAIGenerator={() => setShowAIGenerator(true)}
      />
      <div className="shrink-0 px-3 pt-2 md:px-4">
        <PrivacyBanner mode="cloud" />
      </div>

      <div className="flex-1 flex overflow-hidden relative">
        {/* Desktop node rail */}
        {!isMobile && (
          <NodeRail
            onAddNode={addNode}
            onAIGenerate={handleAIGeneratedWorkflow}
            showAIGenerator={showAIGenerator}
            onToggleAIGenerator={setShowAIGenerator}
          />
        )}

        {/* Mobile rail overlay */}
        {isMobile && showMobileSidebar && (
          <>
            <div
              className="fixed inset-0 bg-black/50 z-40"
              onClick={() => setShowMobileSidebar(false)}
            />
            <div className="fixed inset-y-0 start-0 z-50 w-16 bg-background-secondary border-e border-border flex flex-col">
              <div className="flex items-center justify-end p-2 border-b border-border">
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8"
                  onClick={() => setShowMobileSidebar(false)}
                  aria-label={t('page.closeNodeRail')}
                >
                  <X className="w-4 h-4" />
                </Button>
              </div>
              <NodeRail
                onAddNode={(type) => { addNode(type); setShowMobileSidebar(false); }}
                onAIGenerate={handleAIGeneratedWorkflow}
                showAIGenerator={showAIGenerator}
                onToggleAIGenerator={setShowAIGenerator}
              />
            </div>
          </>
        )}

        {/* Canvas */}
        <div className="flex-1 relative">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeContextMenu={onNodeContextMenu}
            onSelectionChange={onSelectionChange}
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            nodeTypes={nodeTypes}
            fitView
            attributionPosition="bottom-right"
            deleteKeyCode={null}
          >
            <Background color="hsl(var(--border-strong))" gap={16} />
            {!isMobile && (
              <MiniMap
                nodeColor={(node) => {
                  if (node.type === 'imageUpload') return 'hsl(var(--accent))';
                  if (node.type === 'imageGen') return 'hsl(var(--ok))';
                  if (node.type === 'textInput') return 'hsl(var(--teal))';
                  if (node.type === 'aiAgent') return 'hsl(var(--violet))';
                  if (node.type === 'ttsNode') return 'hsl(var(--warn))';
                  if (node.type === 'videoGenNode') return 'hsl(var(--err))';
                  return 'hsl(var(--foreground-tertiary))';
                }}
                maskColor="hsl(var(--background) / 0.8)"
                style={{ backgroundColor: 'hsl(var(--background-secondary))', border: '1px solid hsl(var(--border))', borderRadius: 12, overflow: 'hidden' }}
              />
            )}
          </ReactFlow>

          {/* Empty canvas onboarding — hides as soon as first node is added */}
          {nodes.length === 0 && (
            <div className="absolute inset-0 z-10 flex items-center justify-center pointer-events-none">
              <div className="pointer-events-auto">
                <EmptyState
                  icon={WorkflowIcon}
                  icon3d="/icons/3d/flow.png"
                  title={t('emptyState.title')}
                  description={t('emptyState.description')}
                  primaryCta={{
                    label: t('emptyState.cta'),
                    icon: Wand2,
                    onClick: () => setShowAIGenerator(true),
                  }}
                  suggestions={[
                    {
                      label: t('emptyCanvas.startFromBrief'),
                      icon: Wand2,
                      onClick: () => setShowAIGenerator(true),
                    },
                    {
                      label: t('emptyCanvas.browseTemplates'),
                      icon: LayoutTemplate,
                      onClick: () => {
                        loadWorkflowsList();
                        setLoadModalTab('templates');
                        setShowLoadModal(true);
                      },
                    },
                    {
                      label: t('emptyCanvas.manualBuilder'),
                      icon: MousePointer2,
                    },
                  ]}
                />
              </div>
            </div>
          )}

          {/* Right-click hint chip — shown once, dismissed forever via localStorage */}
          {nodes.length > 0 && !rclickHintDismissed && (
            <div
              className={cn(GLASS_CLASS, 'absolute top-3 start-1/2 -translate-x-1/2 z-10 flex items-center gap-1 ps-3 pe-1.5 py-1 rounded-full text-xs text-foreground-secondary')}
              style={CANVAS_OVERLAY_GLASS_STYLE}
            >
              <span>{t('page.rightClickHint')}</span>
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 text-foreground-secondary/70 hover:text-foreground"
                onClick={dismissRclickHint}
                aria-label={t('page.dismissHint')}
              >
                <X className="w-3 h-3" />
              </Button>
            </div>
          )}

          {/* Floating UI overlays inside the canvas container */}
          <CanvasZoomBar />
          <CanvasCommandBar
            selectedNodeId={selectedNodeId}
            onAddNode={addNode}
            onDuplicate={() => selectedNodeId && duplicateNode(selectedNodeId)}
            onDelete={() => selectedNodeId && deleteNode(selectedNodeId)}
          />

          {/* Pan/zoom hint footer — always visible, non-intrusive */}
          <div className="absolute bottom-2 start-2 z-10 text-[10px] text-foreground-secondary opacity-40 pointer-events-none">
            {t('page.scrollToZoom')}
          </div>
        </div>

        {/* Desktop inspector */}
        {!isMobile && selectedNodeId && (
          <NodeInspector
            node={selectedNode}
            updateNodeData={updateNodeData}
            onClose={() => setSelectedNodeId(null)}
            onRunNode={executeSingleNode}
            onDuplicate={() => duplicateNode(selectedNodeId)}
            onDelete={() => deleteNode(selectedNodeId)}
            runHistory={runHistory}
            isExecuting={isExecuting}
            workflowId={selectedWorkflow?._id || null}
          />
        )}

        {/* Desktop run-history — docked, collapsible side panel (uses the width
            freed by removing the global sidebar). Mobile uses an overlay sheet. */}
        {!isMobile && showRunHistory && (
          <div className="w-[380px] xl:w-[440px] shrink-0 flex flex-col overflow-hidden bg-background border-s border-border">
            <div className="h-12 px-4 flex items-center justify-between shrink-0 border-b border-border">
              <h2 className="text-sm font-semibold text-foreground">{t('page.runHistory')}</h2>
              <Button
                variant="ghost"
                size="icon"
                className="w-7 h-7"
                onClick={() => setShowRunHistory(false)}
                aria-label={t('page.closeRunHistory')}
              >
                <X className="w-4 h-4" />
              </Button>
            </div>
            <div className="flex-1 overflow-hidden">
              <RunHistoryPanel runHistory={runHistory} nodes={nodes} onRunNode={executeSingleNode} />
            </div>
          </div>
        )}
      </div>

      {/* Mobile inspector as bottom sheet */}
      {isMobile && selectedNodeId && (
        <NodeInspector
          node={selectedNode}
          updateNodeData={updateNodeData}
          onClose={() => setSelectedNodeId(null)}
          onRunNode={executeSingleNode}
          onDuplicate={() => duplicateNode(selectedNodeId)}
          onDelete={() => deleteNode(selectedNodeId)}
          runHistory={runHistory}
          isExecuting={isExecuting}
          isMobile
          workflowId={selectedWorkflow?._id || null}
        />
      )}

      {/* Mobile FAB to open node rail */}
      {isMobile && !showMobileSidebar && (
        <Button
          size="icon"
          onClick={() => setShowMobileSidebar(true)}
          className="fixed bottom-20 end-4 z-30 h-14 w-14 rounded-full shadow-lg"
          aria-label={t('page.addNodes')}
        >
          <Layers className="h-6 w-6" />
        </Button>
      )}

      {/* Load Workflow Modal */}
      {showLoadModal && (
        <LoadWorkflowModal
          workflows={workflows}
          templates={templates}
          activeTab={loadModalTab}
          onTabChange={setLoadModalTab}
          onLoadWorkflow={loadWorkflow}
          onLoadTemplate={loadTemplate}
          onClose={() => setShowLoadModal(false)}
        />
      )}

      {/* Node Context Menu */}
      {contextMenu && (
        <NodeContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          nodeId={contextMenu.nodeId}
          nodeType={contextMenu.nodeType}
          onDuplicate={duplicateNode}
          onDelete={deleteNode}
          onRunNode={executeSingleNode}
          onClose={closeContextMenu}
        />
      )}

      {/* Delete Confirmation Dialog */}
      {confirmDialog}

      {/* Budget/credit exceeded modal (402 hard block) */}
      {budgetModal}

      {/* AI Workflow Generator Modal — canonical Dialog for overlay/portal/focus.
          WorkflowGenerator already renders its own glass card, so the Dialog
          paper is neutralized (transparent, no padding/border/shadow) and its
          built-in close button suppressed (the card has its own). */}
      <Dialog open={showAIGenerator} onOpenChange={setShowAIGenerator}>
        <DialogContent
          showClose={false}
          className="max-w-lg w-full !bg-transparent !border-0 !shadow-none p-0"
        >
          <WorkflowGenerator
            onGenerate={handleAIGeneratedWorkflow}
            onClose={() => setShowAIGenerator(false)}
          />
        </DialogContent>
      </Dialog>

      {/* Run History — mobile overlay sheet (desktop uses the docked panel).
          Dark scrim kept for the overlay; the panel body is a flat surface. */}
      {isMobile && showRunHistory && (
        <div
          className="fixed inset-0 bg-black/50 z-40"
          onClick={() => setShowRunHistory(false)}
        >
          <div
            className="absolute end-0 top-0 bottom-0 w-full sm:w-[600px] flex flex-col bg-background border-s border-border shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="h-12 px-4 border-b border-border flex items-center justify-between shrink-0">
              <h2 className="text-sm font-semibold text-foreground">{t('page.runHistory')}</h2>
              <Button
                variant="ghost"
                size="icon"
                className="w-7 h-7"
                onClick={() => setShowRunHistory(false)}
                aria-label={t('page.closeRunHistory')}
              >
                <X className="w-4 h-4" />
              </Button>
            </div>
            <div className="flex-1 overflow-hidden">
              <RunHistoryPanel runHistory={runHistory} nodes={nodes} onRunNode={executeSingleNode} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function WorkflowPage() {
  return (
    <ReactFlowProvider>
      <WorkflowEditor />
    </ReactFlowProvider>
  );
}
