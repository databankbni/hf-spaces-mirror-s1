import os
from datetime import datetime, timedelta

import bcrypt
from jose import JWTError, jwt

# Chave usada para assinar os JWTs
SECRET_KEY = os.getenv("JWT_SECRET", "troque_essa_chave_em_producao")

# Algoritmo do JWT
ALGORITHM = "HS256"

# Tempo de expiração do token
ACCESS_TOKEN_EXPIRE_HOURS = 24


def gerar_hash_senha(senha: str) -> str:
    senha_bytes = senha.encode("utf-8")
    salt = bcrypt.gensalt()
    senha_hash = bcrypt.hashpw(senha_bytes, salt)
    return senha_hash.decode("utf-8")


def verificar_senha(senha: str, senha_hash: str) -> bool:
    return bcrypt.checkpw(
        senha.encode("utf-8"),
        senha_hash.encode("utf-8")
    )


def criar_token(usuario_id: int):
    expiracao = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)

    payload = {
        "sub": str(usuario_id),
        "exp": expiracao
    }

    token = jwt.encode(
        payload,
        SECRET_KEY,
        algorithm=ALGORITHM
    )

    return token


def verificar_token(token: str):
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )

        return payload

    except JWTError:
        return None