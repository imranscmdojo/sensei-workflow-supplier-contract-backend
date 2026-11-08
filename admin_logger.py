"""
Admin Event Logger — writes usage events to Firestore admin_events collection.

Usage:
    from admin_logger import log_admin_event, log_token_usage

    await log_admin_event("ask_message_received", user_id, {
        "sessionId": session_id,
        "input_tokens": 1200,
        "output_tokens": 800,
        "total_tokens": 2000,
        "provider": "anthropic",
    })

For sync contexts (FastAPI endpoints):
    log_admin_event_sync("ask_message_received", user_id, {...})
"""
import os
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Lazy singleton — initialized on first use
_firestore_client = None


def _get_firestore():
    global _firestore_client
    if _firestore_client is None:
        try:
            from google.cloud import firestore
            _firestore_client = firestore.Client(
                project=os.environ.get("FIREBASE_PROJECT_ID", "sensei-ask-project"),
            )
        except Exception as e:
            logger.warning(f"[admin_logger] Failed to initialize Firestore: {e}")
    return _firestore_client


def log_admin_event_sync(
    event_type: str,
    user_id: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    """Write an admin event to Firestore (synchronous, fire-and-forget)."""
    db = _get_firestore()
    if db is None:
        return False
    try:
        db.collection("admin_events").add({
            "type": event_type,
            "userId": user_id,
            "metadata": metadata or {},
            "timestamp": db.SERVER_TIMESTAMP,
        })
        return True
    except Exception as e:
        logger.warning(f"[admin_logger] Failed to log event {event_type}: {e}")
        return False


async def log_admin_event(
    event_type: str,
    user_id: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    """Write an admin event to Firestore (async wrapper, fire-and-forget)."""
    return log_admin_event_sync(event_type, user_id, metadata)


def log_token_usage(
    event_type: str,
    user_id: str,
    token_usage: dict,
    extra: Optional[Dict[str, Any]] = None,
) -> bool:
    """Log a token usage event. Merges token fields into metadata."""
    metadata = {
        "input_tokens": token_usage.get("input_tokens", 0),
        "output_tokens": token_usage.get("output_tokens", 0),
        "total_tokens": token_usage.get("total_tokens", 0),
    }
    # Include cache tokens if present (Claude)
    if "cache_read_input_tokens" in token_usage:
        metadata["cache_read_input_tokens"] = token_usage["cache_read_input_tokens"]
    if "cache_creation_input_tokens" in token_usage:
        metadata["cache_creation_input_tokens"] = token_usage["cache_creation_input_tokens"]
    if extra:
        metadata.update(extra)
    return log_admin_event_sync(event_type, user_id, metadata)
