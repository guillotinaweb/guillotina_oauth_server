"""MCP integration for OAuth resource indicators, discovery, and auth policy."""

from guillotina_oauth_server.integrations.mcp import access as _access  # noqa: F401
from guillotina_oauth_server.integrations.mcp import discovery as _disc  # noqa: F401
from guillotina_oauth_server.integrations.mcp import grant as _grant  # noqa: F401
from guillotina_oauth_server.integrations.mcp import identifiers as _ids  # noqa: F401


def _ensure_challenge_middleware(settings) -> None:
    middleware = "guillotina_oauth_server.integrations.mcp.middleware.OAuthMCPChallengeMiddleware"
    middlewares = list(settings.get("middlewares") or [])
    if middleware not in middlewares:
        middlewares.append(middleware)
    settings["middlewares"] = middlewares


def register_mcp_oauth_integration(settings) -> None:
    from guillotina_oauth_server.discovery.protected_resource import register_protected_resource_provider
    from guillotina_oauth_server.indicators.registry import (
        register_allowed_indicator_resolver,
        register_required_indicator_resolver,
    )
    from guillotina_oauth_server.integrations.mcp.access import _mcp_protocol_audience_resolver
    from guillotina_oauth_server.integrations.mcp.discovery import _mcp_protected_resource_provider
    from guillotina_oauth_server.integrations.mcp.grant import _mcp_protocol_resource_resolver

    register_allowed_indicator_resolver(_mcp_protocol_resource_resolver)
    register_required_indicator_resolver(_mcp_protocol_audience_resolver)
    register_protected_resource_provider(_mcp_protected_resource_provider)
    _ensure_challenge_middleware(settings)
