import os

from google.oauth2 import id_token
from google.auth.transport import requests

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")


def verificar_credential(credential: str):

    dados = id_token.verify_oauth2_token(
        credential,
        requests.Request(),
        GOOGLE_CLIENT_ID
    )

    return {
        "google_id": dados["sub"],
        "nome": dados["name"],
        "email": dados["email"],
        "foto": dados.get("picture")
    }