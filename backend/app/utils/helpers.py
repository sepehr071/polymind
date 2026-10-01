import uuid
from datetime import datetime


def serialize_doc(doc):
    """Convert a row/dict to a JSON-serialisable shape.

    Historically converted Mongo ObjectId + datetime; now also stringifies
    ``uuid.UUID`` since the canonical PG primary key is a UUID. Idempotent —
    safe to call on already-serialised payloads.
    """
    if doc is None:
        return None
    if isinstance(doc, list):
        return [serialize_doc(d) for d in doc]
    if isinstance(doc, dict):
        result = {}
        for key, value in doc.items():
            if isinstance(value, uuid.UUID):
                result[key] = str(value)
            elif isinstance(value, datetime):
                result[key] = value.isoformat()
            elif isinstance(value, dict):
                result[key] = serialize_doc(value)
            elif isinstance(value, list):
                result[key] = serialize_doc(value)
            else:
                result[key] = value
        return result
    if isinstance(doc, uuid.UUID):
        return str(doc)
    if isinstance(doc, datetime):
        return doc.isoformat()
    return doc


def generate_conversation_title(first_message, max_length=50):
    """Generate a title from the first message"""
    # Remove extra whitespace and newlines
    title = ' '.join(first_message.split())

    # Truncate if too long
    if len(title) > max_length:
        title = title[:max_length-3] + '...'

    return title if title else 'New conversation'


def validate_object_id(id_string):
    """Validate if string is a valid identifier (UUID).

    Name kept for back-compat with callers; semantics now check UUID
    (Postgres primary key) instead of legacy Mongo ObjectId.
    """
    try:
        uuid.UUID(str(id_string))
        return True
    except (ValueError, TypeError, AttributeError):
        return False
