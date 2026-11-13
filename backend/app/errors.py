"""Erreur applicative au format du contrat : { "code": "...", "message": "..." }."""


class ApiException(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
