from flask import Blueprint, request, g
from app import app
from app.registry.music_provider_registry import MusicProviderRegistry

pl_bp = Blueprint('playlist', __name__)

@pl_bp.before_request
def set_active_provider():
    """
    Middleware to select the active provider based on request parameters.
    """
    app.logger.debug(f"Setting active provider: {request.args.get('provider', 'Spotify')}")
    provider_id = request.args.get('provider', 'Spotify')  # Default to Spotify
    try:
        g.music_provider = MusicProviderRegistry.get_provider(provider_id)
    except ValueError as e:
        return {"error": str(e)}, 400