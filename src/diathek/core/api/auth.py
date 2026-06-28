from rest_framework import authentication, exceptions


class TokenAuthentication(authentication.BaseAuthentication):
    """Authenticate via a per-user API token.

    The token may be supplied either as an ``Authorization: Bearer <token>``
    header or as a ``?token=<token>`` query parameter, so it works both from
    scripts and from a plain browser address bar. The token maps to a single
    :class:`~diathek.core.models.User`, which is returned as ``request.user`` so
    audit-log attribution works exactly like the web UI.
    """

    keyword = "Bearer"

    def authenticate(self, request):
        token_value = self._token_from_request(request)
        if not token_value:
            return None

        from diathek.core.models import User

        try:
            user = User.objects.get(api_token=token_value, is_active=True)
        except User.DoesNotExist as err:
            raise exceptions.AuthenticationFailed("Ungültiger API-Token.") from err

        return (user, token_value)

    def _token_from_request(self, request):
        header = authentication.get_authorization_header(request)
        if header:
            try:
                auth_type, value = header.decode("utf-8").split(" ", 1)
            except (ValueError, UnicodeDecodeError):
                return None
            if auth_type.lower() != self.keyword.lower():
                return None
            return value.strip()
        return request.query_params.get("token", "").strip()

    def authenticate_header(self, request):
        return self.keyword
