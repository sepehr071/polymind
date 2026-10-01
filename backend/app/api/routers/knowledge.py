"""Knowledge vault, knowledge-folder, and conversation-folder routes, translated
from app/routes/knowledge.py, app/routes/knowledge_folders.py, and
app/routes/folders.py.

THREE Flask blueprints -> THREE FastAPI routers in this one module (one per
url_prefix), each carrying the router-level ``Depends(flask_ctx)`` so every
handler runs inside one Flask app_context and reuses the existing model facades
+ ``check_project_access`` VERBATIM:

    knowledge_router          -> /api/knowledge          (knowledge_bp)
    knowledge_folders_router  -> /api/knowledge-folders   (knowledge_folders_bp)
    folders_router            -> /api/folders             (folders_bp)

There is NO SSE/stream route in any of these blueprints, so no ``sse_stream``
import is needed here. Every handler maps 1:1 to its Flask original; bodies are
read with the tolerant ``_json_body`` helper (mirrors ``get_json(silent=True)``)
and response shapes (incl. the Mongo ``_id`` alias from ``to_dict()``) are
preserved byte-for-byte.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.deps import flask_ctx, require_active
from app.models.knowledge_item import KnowledgeItemModel, NULL_PROJECT_SENTINEL
from app.models.knowledge_folder import (
    KnowledgeFolderModel,
    NULL_PROJECT_SENTINEL as KF_NULL_PROJECT_SENTINEL,
)
from app.models.folder import FolderModel, NULL_PROJECT_SENTINEL as F_NULL_PROJECT_SENTINEL
from app.models.conversation import ConversationModel
from app.models.project import ProjectModel
from app.models.project_member import ProjectMemberModel
from app.models.workspace_member import WorkspaceMemberModel
from app.utils.helpers import serialize_doc, validate_object_id
from app.utils.permissions import check_project_access


async def _json_body(request: Request) -> dict:
    """Read the request JSON body, tolerating empty/garbage like get_json(silent=True)."""
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


# ===========================================================================
# /api/knowledge  (knowledge_bp)
# ===========================================================================
knowledge_router = APIRouter(dependencies=[Depends(flask_ctx)])


def _accessible_project_ids(user_id: str) -> set:
    """Return IDs of every project the user can currently view.

    Explicit project_members + group grants only — company membership alone
    does NOT open a team. Delegates to ``ProjectModel.accessible_ids_for_user``.
    """
    return ProjectModel.accessible_ids_for_user(user_id)


def _resolve_project_filter(raw, null_sentinel):
    """Translate ?project_id= to model-layer filter form.

    Returns (filter_value, error_response_or_None). ``filter_value`` is one of:
        None            -> no filter
        null_sentinel   -> project_id is null/missing
        <str UUID>      -> exact match
    """
    if raw is None or raw == '':
        return None, None
    if raw == 'null':
        return null_sentinel, None
    if not validate_object_id(raw):
        return None, JSONResponse({'error': 'Invalid project_id'}, status_code=400)
    return raw, None


@knowledge_router.get("/list")
def list_knowledge_items(request: Request, user: dict = Depends(require_active)):
    user_id = str(user['_id'])

    qp = request.query_params
    page = max(1, int(qp.get('page', 1)))
    limit = min(100, max(1, int(qp.get('limit', 20))))
    tag = (qp.get('tag', '') or '').strip() or None
    favorite_only = (qp.get('favorite', '') or '').lower() == 'true'
    search = (qp.get('search', '') or '').strip() or None
    folder_id = (qp.get('folder_id', '') or '').strip() or None

    raw_project = qp.get('project_id')
    project_filter, err = _resolve_project_filter(raw_project, NULL_PROJECT_SENTINEL)
    if err is not None:
        return err
    if project_filter and project_filter != NULL_PROJECT_SENTINEL:
        if not check_project_access(user_id, project_filter, 'viewer'):
            return JSONResponse({'error': 'Project access denied', 'status': 403}, status_code=403)

    if search:
        accessible = _accessible_project_ids(user_id)
        items, total = KnowledgeItemModel.search_scoped(
            user_id,
            search,
            accessible_project_ids=accessible,
            project_id=project_filter,
            page=page,
            limit=limit,
        )
    else:
        items, total = KnowledgeItemModel.find_by_user(
            user_id,
            page=page,
            limit=limit,
            tag=tag,
            favorite_only=favorite_only,
            folder_id=folder_id,
            project_id=project_filter,
        )

    return {
        'items': serialize_doc(items),
        'total': total,
        'page': page,
        'limit': limit,
        'total_pages': (total + limit - 1) // limit,
        'has_more': (page * limit) < total,
    }


# IMPORTANT: Static routes MUST come before dynamic /<item_id> routes.
@knowledge_router.get("/search")
def search_knowledge(request: Request, user: dict = Depends(require_active)):
    user_id = str(user['_id'])

    query = (request.query_params.get('q', '') or '').strip()
    if not query:
        return JSONResponse({'error': 'Search query is required'}, status_code=400)
    if len(query) > 200:
        return JSONResponse({'error': 'Query too long (max 200 characters)'}, status_code=400)

    page = max(1, int(request.query_params.get('page', 1)))
    limit = min(100, max(1, int(request.query_params.get('limit', 20))))

    accessible = _accessible_project_ids(user_id)

    items, total = KnowledgeItemModel.search_scoped(
        user_id,
        query,
        accessible_project_ids=accessible,
        page=page,
        limit=limit,
    )

    return {
        'items': serialize_doc(items),
        'total': total,
        'page': page,
        'limit': limit,
        'query': query,
        'has_more': (page * limit) < total,
    }


@knowledge_router.get("/tags")
def get_user_tags(user: dict = Depends(require_active)):
    user_id = str(user['_id'])
    tags = KnowledgeItemModel.get_user_tags(user_id)
    return {'tags': sorted(tags)}


# Registered BEFORE the dynamic /{item_id} routes: FastAPI matches by
# registration order (unlike Werkzeug, which prioritizes static segments), so
# PUT /move must come first or it would bind to /{item_id} with item_id="move".
@knowledge_router.put("/move")
async def move_items_to_folder(request: Request, user: dict = Depends(require_active)):
    user_id = str(user['_id'])
    data = await _json_body(request)

    item_ids = data.get('item_ids', [])
    if not item_ids or not isinstance(item_ids, list):
        return JSONResponse({'error': 'item_ids array is required'}, status_code=400)

    for item_id in item_ids:
        if not validate_object_id(item_id):
            return JSONResponse({'error': 'Invalid item ID in list'}, status_code=400)

    folder_id = data.get('folder_id')
    if folder_id and not validate_object_id(folder_id):
        return JSONResponse({'error': 'Invalid folder ID'}, status_code=400)

    target_project_id = None
    target_workspace_id = None
    target_folder = None
    if folder_id:
        target_folder = KnowledgeFolderModel.find_by_id(folder_id)
        if not target_folder or str(target_folder.get('user_id')) != user_id:
            return JSONResponse({'error': 'Target folder not found'}, status_code=404)
        target_project_id = target_folder.get('project_id')
        target_workspace_id = target_folder.get('workspace_id')

    source_items = []
    for iid in item_ids:
        item = KnowledgeItemModel.find_by_id(iid)
        if not item or str(item.get('user_id')) != user_id:
            return JSONResponse({'error': f'Item {iid} not found'}, status_code=404)
        source_items.append(item)

    source_projects = {
        str(it['project_id']) for it in source_items if it.get('project_id')
    }
    for pid in source_projects:
        if not check_project_access(user_id, pid, 'editor'):
            return JSONResponse({
                'error': 'Project access denied for source items',
                'status': 403,
            }, status_code=403)

    if target_project_id:
        if not check_project_access(user_id, target_project_id, 'editor'):
            return JSONResponse({
                'error': 'Project access denied for target folder',
                'status': 403,
            }, status_code=403)

    needs_project_sync = False
    target_pid_str = str(target_project_id) if target_project_id else None
    for it in source_items:
        item_pid = it.get('project_id')
        item_pid_str = str(item_pid) if item_pid else None
        if item_pid_str != target_pid_str:
            needs_project_sync = True
            break

    if needs_project_sync:
        moved_count = KnowledgeItemModel.move_to_folder(
            item_ids,
            user_id,
            folder_id,
            sync_project=True,
            project_id=target_project_id,
            workspace_id=target_workspace_id,
        )
    else:
        moved_count = KnowledgeItemModel.move_to_folder(item_ids, user_id, folder_id)

    return {
        'message': f'Moved {moved_count} items',
        'moved_count': moved_count,
    }


@knowledge_router.get("/{item_id}")
def get_knowledge_item(item_id: str, user: dict = Depends(require_active)):
    user_id = str(user['_id'])

    if not validate_object_id(item_id):
        return JSONResponse({'error': 'Invalid item ID'}, status_code=400)

    item = KnowledgeItemModel.find_by_id(item_id)
    if not item or str(item.get('user_id')) != user_id:
        return JSONResponse({'error': 'Item not found'}, status_code=404)

    pid = item.get('project_id')
    if pid and not check_project_access(user_id, str(pid), 'viewer'):
        return JSONResponse({'error': 'Project access denied', 'status': 403}, status_code=403)

    return {'item': serialize_doc(item)}


@knowledge_router.post("")
async def create_knowledge_item(request: Request, user: dict = Depends(require_active)):
    user_id = str(user['_id'])
    data = await _json_body(request)

    source_type = (data.get('source_type', '') or '').strip()
    if source_type not in ('chat', 'arena', 'debate', 'workflow', 'meeting'):
        return JSONResponse(
            {'error': 'Invalid source_type. Must be chat, arena, debate, workflow, or meeting'},
            status_code=400,
        )

    workflow_id = None
    node_id = None
    source_id = ''
    message_id = ''

    if source_type == 'workflow':
        workflow_id = (data.get('workflow_id') or '').strip()
        if not workflow_id or not validate_object_id(workflow_id):
            return JSONResponse({'error': 'Invalid or missing workflow_id'}, status_code=400)
        node_id = (data.get('node_id') or '').strip()
        if not node_id:
            return JSONResponse({'error': 'Missing node_id'}, status_code=400)
    else:
        source_id = (data.get('source_id', '') or '').strip()
        if not source_id or not validate_object_id(source_id):
            return JSONResponse({'error': 'Invalid or missing source_id'}, status_code=400)

        message_id = (data.get('message_id', '') or '').strip()
        if not message_id or not validate_object_id(message_id):
            return JSONResponse({'error': 'Invalid or missing message_id'}, status_code=400)

    content = (data.get('content', '') or '').strip()
    if not content:
        return JSONResponse({'error': 'Content is required'}, status_code=400)
    if len(content) > 50000:
        return JSONResponse({'error': 'Content too long (max 50000 characters)'}, status_code=400)

    title = (data.get('title', '') or '').strip()
    if not title:
        return JSONResponse({'error': 'Title is required'}, status_code=400)
    if len(title) > 200:
        return JSONResponse({'error': 'Title too long (max 200 characters)'}, status_code=400)

    tags = data.get('tags', [])
    if not isinstance(tags, list):
        return JSONResponse({'error': 'Tags must be an array'}, status_code=400)
    tags = [str(t).strip().lower() for t in tags if t and str(t).strip()]
    tags = list(set(tags))[:20]

    project_id = data.get('project_id') or None
    workspace_id = data.get('workspace_id') or None

    if project_id:
        if not validate_object_id(project_id):
            return JSONResponse({'error': 'Invalid project_id'}, status_code=400)
        if not check_project_access(user_id, project_id, 'editor'):
            return JSONResponse({'error': 'Project access denied', 'status': 403}, status_code=403)
        project = ProjectModel.find_by_id(project_id)
        if not project:
            return JSONResponse({'error': 'Project not found'}, status_code=404)
        workspace_id = project['workspace_id']
    elif workspace_id:
        if not validate_object_id(workspace_id):
            return JSONResponse({'error': 'Invalid workspace_id'}, status_code=400)

    item = KnowledgeItemModel.create(
        user_id=user_id,
        source_type=source_type,
        source_id=source_id or None,
        message_id=message_id or None,
        content=content,
        title=title,
        tags=tags,
        project_id=project_id,
        workspace_id=workspace_id,
        workflow_id=workflow_id,
        node_id=node_id,
    )

    return JSONResponse({'item': serialize_doc(item)}, status_code=201)


@knowledge_router.put("/{item_id}")
async def update_knowledge_item(item_id: str, request: Request,
                                user: dict = Depends(require_active)):
    user_id = str(user['_id'])

    if not validate_object_id(item_id):
        return JSONResponse({'error': 'Invalid item ID'}, status_code=400)

    data = await _json_body(request)

    if 'project_id' in data:
        return JSONResponse({
            'error': 'Cannot reassign item to a different project directly. Move via folder.',
            'code': 'cannot_reassign_project',
        }, status_code=400)

    updates = {}

    if 'title' in data:
        title = data['title'].strip() if data['title'] else ''
        if not title:
            return JSONResponse({'error': 'Title cannot be empty'}, status_code=400)
        if len(title) > 200:
            return JSONResponse({'error': 'Title too long (max 200 characters)'}, status_code=400)
        updates['title'] = title

    if 'tags' in data:
        tags = data['tags']
        if not isinstance(tags, list):
            return JSONResponse({'error': 'Tags must be an array'}, status_code=400)
        tags = [str(t).strip().lower() for t in tags if t and str(t).strip()]
        tags = list(set(tags))[:20]
        updates['tags'] = tags

    if 'notes' in data:
        notes = data['notes'] if data['notes'] else ''
        if len(notes) > 5000:
            return JSONResponse({'error': 'Notes too long (max 5000 characters)'}, status_code=400)
        updates['notes'] = notes

    if 'is_favorite' in data:
        updates['is_favorite'] = bool(data['is_favorite'])

    if 'folder_id' in data:
        folder_id = data['folder_id']
        if folder_id:
            if not validate_object_id(folder_id):
                return JSONResponse({'error': 'Invalid folder ID'}, status_code=400)
        updates['folder_id'] = folder_id  # Can be None to move to root

    if not updates:
        return JSONResponse({'error': 'No valid fields to update'}, status_code=400)

    try:
        success = KnowledgeItemModel.update(item_id, user_id, updates)
    except ValueError as e:
        code = str(e)
        if code == 'cannot_reassign_project':
            return JSONResponse({
                'error': 'Cannot reassign item to a different project directly. Move via folder.',
                'code': 'cannot_reassign_project',
            }, status_code=400)
        return JSONResponse({'error': code}, status_code=400)

    if not success:
        return JSONResponse({'error': 'Item not found'}, status_code=404)

    item = KnowledgeItemModel.find_by_id(item_id)
    return {'item': serialize_doc(item)}


@knowledge_router.delete("/{item_id}")
def delete_knowledge_item(item_id: str, user: dict = Depends(require_active)):
    user_id = str(user['_id'])

    if not validate_object_id(item_id):
        return JSONResponse({'error': 'Invalid item ID'}, status_code=400)

    item = KnowledgeItemModel.find_by_id(item_id)
    if not item or str(item.get('user_id')) != user_id:
        return JSONResponse({'error': 'Item not found'}, status_code=404)

    pid = item.get('project_id')
    if pid and not check_project_access(user_id, str(pid), 'editor'):
        return JSONResponse({'error': 'Project access denied', 'status': 403}, status_code=403)

    success = KnowledgeItemModel.delete(item_id, user_id)
    if not success:
        return JSONResponse({'error': 'Item not found'}, status_code=404)

    return {'message': 'Item deleted'}


# ===========================================================================
# /api/knowledge-folders  (knowledge_folders_bp)
# ===========================================================================
knowledge_folders_router = APIRouter(dependencies=[Depends(flask_ctx)])


@knowledge_folders_router.get("")
def list_folders(request: Request, user: dict = Depends(require_active)):
    user_id = str(user['_id'])

    raw_project = request.query_params.get('project_id')
    project_filter, err = _resolve_project_filter(raw_project, KF_NULL_PROJECT_SENTINEL)
    if err is not None:
        return err
    if project_filter and project_filter != KF_NULL_PROJECT_SENTINEL:
        if not check_project_access(user_id, project_filter, 'viewer'):
            return JSONResponse({'error': 'Project access denied', 'status': 403}, status_code=403)

    folders = KnowledgeFolderModel.find_by_user(user_id, project_id=project_filter)

    # One grouped query (folder_id -> count) instead of a per-folder COUNT.
    counts = KnowledgeItemModel.counts_by_folder(user_id)
    for folder in folders:
        folder['item_count'] = counts.get(str(folder['_id']), 0)

    unfiled_count = KnowledgeItemModel.count_by_folder(user_id, 'root')

    return {
        'folders': serialize_doc(folders),
        'unfiled_count': unfiled_count,
    }


@knowledge_folders_router.post("")
async def create_knowledge_folder(request: Request, user: dict = Depends(require_active)):
    user_id = str(user['_id'])
    data = await _json_body(request)

    name = (data.get('name', '') or '').strip()
    if not name:
        return JSONResponse({'error': 'Folder name is required'}, status_code=400)
    if len(name) > 100:
        return JSONResponse({'error': 'Folder name too long (max 100 characters)'}, status_code=400)

    project_id = data.get('project_id') or None
    workspace_id = data.get('workspace_id') or None

    if project_id:
        if not validate_object_id(project_id):
            return JSONResponse({'error': 'Invalid project_id'}, status_code=400)
        if not check_project_access(user_id, project_id, 'editor'):
            return JSONResponse({'error': 'Project access denied', 'status': 403}, status_code=403)
        project = ProjectModel.find_by_id(project_id)
        if not project:
            return JSONResponse({'error': 'Project not found'}, status_code=404)
        workspace_id = project['workspace_id']
    elif workspace_id:
        if not validate_object_id(workspace_id):
            return JSONResponse({'error': 'Invalid workspace_id'}, status_code=400)

    existing_folders = KnowledgeFolderModel.find_by_user(
        user_id,
        project_id=(project_id if project_id else KF_NULL_PROJECT_SENTINEL),
    )
    if any(f['name'].lower() == name.lower() for f in existing_folders):
        return JSONResponse({'error': 'A folder with this name already exists'}, status_code=400)

    color = data.get('color', '#5c9aed')
    if not color.startswith('#') or len(color) != 7:
        color = '#5c9aed'

    folder = KnowledgeFolderModel.create(
        user_id,
        name,
        color,
        project_id=project_id,
        workspace_id=workspace_id,
    )

    return JSONResponse({'folder': serialize_doc(folder)}, status_code=201)


# Registered BEFORE /{folder_id}: FastAPI matches by registration order, so the
# literal /reorder must precede the dynamic /{folder_id} or PUT /reorder binds
# to it with folder_id="reorder".
@knowledge_folders_router.put("/reorder")
async def reorder_knowledge_folders(request: Request, user: dict = Depends(require_active)):
    user_id = str(user['_id'])
    data = await _json_body(request)

    orders = data.get('orders', [])
    if not orders or not isinstance(orders, list):
        return JSONResponse({'error': 'Orders array is required'}, status_code=400)

    for item in orders:
        if not item.get('folder_id') or not validate_object_id(item['folder_id']):
            return JSONResponse({'error': 'Invalid folder ID in orders'}, status_code=400)
        if not isinstance(item.get('order'), int):
            return JSONResponse({'error': 'Order must be an integer'}, status_code=400)

    KnowledgeFolderModel.reorder(user_id, orders)

    return {'message': 'Folders reordered'}


@knowledge_folders_router.get("/{folder_id}")
def get_knowledge_folder(folder_id: str, user: dict = Depends(require_active)):
    user_id = str(user['_id'])

    if not validate_object_id(folder_id):
        return JSONResponse({'error': 'Invalid folder ID'}, status_code=400)

    folder = KnowledgeFolderModel.find_by_id(folder_id)
    if not folder or str(folder.get('user_id')) != user_id:
        return JSONResponse({'error': 'Folder not found'}, status_code=404)

    folder['item_count'] = KnowledgeItemModel.count_by_folder(user_id, folder_id)

    return {'folder': serialize_doc(folder)}


@knowledge_folders_router.put("/{folder_id}")
async def update_knowledge_folder(folder_id: str, request: Request,
                                  user: dict = Depends(require_active)):
    user_id = str(user['_id'])

    if not validate_object_id(folder_id):
        return JSONResponse({'error': 'Invalid folder ID'}, status_code=400)

    data = await _json_body(request)

    if 'project_id' in data:
        return JSONResponse({
            'error': 'Cannot reassign folder to a different project',
            'code': 'cannot_reassign_project',
        }, status_code=400)

    updates = {}

    if 'name' in data:
        name = data['name'].strip() if data['name'] else ''
        if not name:
            return JSONResponse({'error': 'Folder name cannot be empty'}, status_code=400)
        if len(name) > 100:
            return JSONResponse({'error': 'Folder name too long (max 100 characters)'}, status_code=400)
        updates['name'] = name

    if 'color' in data:
        color = data['color']
        if color and color.startswith('#') and len(color) == 7:
            updates['color'] = color

    if not updates:
        return JSONResponse({'error': 'No valid fields to update'}, status_code=400)

    try:
        success = KnowledgeFolderModel.update(folder_id, user_id, updates)
    except ValueError as e:
        code = str(e)
        if code == 'duplicate_name':
            return JSONResponse({
                'error': 'A folder with this name already exists',
                'code': 'duplicate_name',
            }, status_code=400)
        if code == 'cannot_reassign_project':
            return JSONResponse({
                'error': 'Cannot reassign folder to a different project',
                'code': 'cannot_reassign_project',
            }, status_code=400)
        return JSONResponse({'error': code}, status_code=400)

    if not success:
        return JSONResponse({'error': 'Folder not found'}, status_code=404)

    folder = KnowledgeFolderModel.find_by_id(folder_id)
    return {'folder': serialize_doc(folder)}


@knowledge_folders_router.delete("/{folder_id}")
def delete_knowledge_folder(folder_id: str, user: dict = Depends(require_active)):
    user_id = str(user['_id'])

    if not validate_object_id(folder_id):
        return JSONResponse({'error': 'Invalid folder ID'}, status_code=400)

    success = KnowledgeFolderModel.delete(folder_id, user_id)
    if not success:
        return JSONResponse({'error': 'Folder not found'}, status_code=404)

    return {'message': 'Folder deleted'}


# ===========================================================================
# /api/folders  (folders_bp) — conversation folders
# ===========================================================================
folders_router = APIRouter(dependencies=[Depends(flask_ctx)])


@folders_router.get("")
def get_folders(request: Request, user: dict = Depends(require_active)):
    user_id = str(user['_id'])

    raw_project = request.query_params.get('project_id')
    project_filter, err = _resolve_project_filter(raw_project, F_NULL_PROJECT_SENTINEL)
    if err is not None:
        return err
    if project_filter and project_filter != F_NULL_PROJECT_SENTINEL:
        if not check_project_access(user_id, project_filter, 'viewer'):
            return JSONResponse({'error': 'Project access denied', 'status': 403}, status_code=403)

    folders = FolderModel.find_all_by_user(user_id, project_id=project_filter)

    return {'folders': serialize_doc(folders)}


@folders_router.get("/tree")
def get_folder_tree(user: dict = Depends(require_active)):
    user_id = str(user['_id'])

    folders = FolderModel.find_all_by_user(user_id)

    def build_tree(parent_id=None):
        children = []
        for folder in folders:
            folder_parent = folder.get('parent_id')
            if folder_parent == parent_id or (parent_id is None and folder_parent is None):
                folder_dict = serialize_doc(folder)
                folder_dict['children'] = build_tree(folder['_id'])
                children.append(folder_dict)
        return sorted(children, key=lambda x: x.get('order', 0))

    tree = build_tree()

    return {'tree': tree}


@folders_router.post("")
async def create_folder(request: Request, user: dict = Depends(require_active)):
    user_id = str(user['_id'])
    data = await _json_body(request)

    name = (data.get('name', '') or '').strip()
    if not name:
        return JSONResponse({'error': 'Folder name is required'}, status_code=400)
    if len(name) > 100:
        return JSONResponse({'error': 'Folder name too long'}, status_code=400)

    project_id = data.get('project_id')
    if project_id:
        if not validate_object_id(project_id):
            return JSONResponse({'error': 'Invalid project_id'}, status_code=400)
        if not check_project_access(user_id, project_id, 'editor'):
            return JSONResponse({'error': 'Project access denied', 'status': 403}, status_code=403)

    folder = FolderModel.create(
        user_id=user_id,
        name=name,
        color=data.get('color', '#5c9aed'),
        icon=data.get('icon'),
        parent_id=data.get('parent_id'),
        project_id=project_id,
    )

    return JSONResponse({'folder': serialize_doc(folder)}, status_code=201)


# Registered BEFORE /{folder_id}: literal /reorder must precede the dynamic
# /{folder_id} so PUT /reorder doesn't bind to it with folder_id="reorder".
@folders_router.put("/reorder")
async def reorder_folders(request: Request, user: dict = Depends(require_active)):
    user_id = str(user['_id'])
    data = await _json_body(request)

    folder_orders = data.get('orders', [])
    if not folder_orders:
        return JSONResponse({'error': 'No order data provided'}, status_code=400)

    FolderModel.reorder(user_id, folder_orders)

    return {'message': 'Folders reordered'}


@folders_router.get("/{folder_id}")
def get_folder(folder_id: str, user: dict = Depends(require_active)):
    user_id = str(user['_id'])

    folder = FolderModel.find_by_id(folder_id)
    if not folder or str(folder['user_id']) != user_id:
        return JSONResponse({'error': 'Folder not found'}, status_code=404)

    conversations = ConversationModel.find_by_user(
        user_id=user_id,
        folder_id=folder_id,
    )

    return {
        'folder': serialize_doc(folder),
        'conversations': serialize_doc(conversations),
    }


@folders_router.put("/{folder_id}")
async def update_folder(folder_id: str, request: Request,
                        user: dict = Depends(require_active)):
    user_id = str(user['_id'])

    folder = FolderModel.find_by_id(folder_id)
    if not folder or str(folder['user_id']) != user_id:
        return JSONResponse({'error': 'Folder not found'}, status_code=404)

    data = await _json_body(request)
    update_fields = {}

    if 'name' in data:
        name = data['name'].strip()
        if not name:
            return JSONResponse({'error': 'Folder name is required'}, status_code=400)
        if len(name) > 100:
            return JSONResponse({'error': 'Folder name too long'}, status_code=400)
        update_fields['name'] = name

    if 'color' in data:
        update_fields['color'] = data['color']

    if 'icon' in data:
        update_fields['icon'] = data['icon']

    if 'parent_id' in data:
        new_parent = data['parent_id']
        if new_parent:
            parent = FolderModel.find_by_id(new_parent)
            if not parent or str(parent['user_id']) != user_id:
                return JSONResponse({'error': 'Parent folder not found'}, status_code=404)
            if str(folder['_id']) == new_parent:
                return JSONResponse({'error': 'Cannot set folder as its own parent'}, status_code=400)
        update_fields['parent_id'] = new_parent

    if update_fields:
        FolderModel.update(folder_id, update_fields)

    updated = FolderModel.find_by_id(folder_id)
    return {'folder': serialize_doc(updated)}


@folders_router.delete("/{folder_id}")
def delete_folder(folder_id: str, user: dict = Depends(require_active)):
    user_id = str(user['_id'])

    folder = FolderModel.find_by_id(folder_id)
    if not folder or str(folder['user_id']) != user_id:
        return JSONResponse({'error': 'Folder not found'}, status_code=404)

    ConversationModel.null_folder_for_folder(folder_id)
    FolderModel.null_parent_for_children(folder_id)
    FolderModel.delete(folder_id)

    return {'message': 'Folder deleted'}


__all__ = ["knowledge_router", "knowledge_folders_router", "folders_router"]
