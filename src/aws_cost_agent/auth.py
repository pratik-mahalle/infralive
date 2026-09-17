"""Authentication failures that require reconnecting one account."""

AUTH_ERROR_CODES = {
    "TokenRetrievalError",
    "SSOTokenLoadError",
    "UnauthorizedSSOTokenError",
    "ExpiredToken",
    "ExpiredTokenException",
    "InvalidGrantException",
    "InvalidClientTokenId",
    "UnrecognizedClientException",
    "InvalidAccessKeyId",
}


def requires_sign_in(error):
    code = getattr(error, "response", {}).get("Error", {}).get("Code", type(error).__name__)
    return code in AUTH_ERROR_CODES
