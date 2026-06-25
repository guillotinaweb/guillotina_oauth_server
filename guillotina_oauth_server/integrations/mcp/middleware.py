from guillotina import task_vars

from guillotina_oauth_server.integrations.mcp.access import OAuthMCPAuthPolicy


class OAuthMCPChallengeMiddleware:
    def __init__(self, app):
        self.next_app = app

    async def __call__(self, scope, receive, send):
        response = await self.next_app(scope, receive, send)
        if self._should_add_challenge(scope, response):
            request = task_vars.request.get(None)
            context = getattr(request, "resource", None) if request is not None else None
            context = context or task_vars.container.get(None)
            if request is not None and context is not None:
                headers = OAuthMCPAuthPolicy().unauthorized_headers(request, context)
                response.headers.update(headers)
        return response

    def _should_add_challenge(self, scope, response):
        if response.headers.get("WWW-Authenticate"):
            return False
        return (
            scope.get("type") == "http"
            and scope.get("method") == "POST"
            and str(scope.get("path") or "").endswith("/@mcp/protocol")
            and getattr(response, "status", None) == 401
            and not getattr(response, "prepared", False)
        )
