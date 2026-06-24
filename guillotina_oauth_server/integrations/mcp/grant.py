"""MCP allowed indicator resolver (grant phase)."""

from guillotina_oauth_server.integrations.mcp.identifiers import _mcp_resource_url_from_value
from guillotina_oauth_server.utils.request import normalize_list
from guillotina_oauth_server.utils.urls import container_issuer_url


def _mcp_protocol_resource_resolver(request, container):
    resources = {f"{container_issuer_url(request, container)}/@mcp/protocol"}
    params = getattr(request, "oauth_request_params", {}) or {}
    for value in normalize_list(params.get("resource")):
        resource = _mcp_resource_url_from_value(request, container, value)
        if resource:
            resources.add(resource)
    return resources
