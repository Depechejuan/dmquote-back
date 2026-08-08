from rest_framework.throttling import SimpleRateThrottle


class TranslationRequestThrottle(SimpleRateThrottle):
    scope = "translation_request"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}
