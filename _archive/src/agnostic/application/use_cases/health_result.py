"""Health check result builder.

Simple health status response for application heartbeat endpoints.
"""


def build_health_result() -> dict[str, str]:
    """Return application health status.
    
    Returns:
        dict with single "status" key set to "ok"
    """
    return {"status": "ok"}
