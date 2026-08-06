"""Sube el modelo mmBERT fine-tuneado (modelo_modernbert/modelo_entrenado)
a Hugging Face Hub, para que el HF Space lo cargue desde ahí.

Requiere estar autenticado en HF (uno de):
  - haber corrido `huggingface-cli login`, o
  - tener la variable de entorno HF_TOKEN con un token de ESCRITURA.

Ejecutar desde la carpeta Clasificacion con:
    python -m deploy_hf_space.subir_modelo
"""
import os
from pathlib import Path

from huggingface_hub import HfApi

REPO_ID = os.environ.get("MODEL_REPO", "lcwalkerd/shadow-ai-dlp-mmbert")
CARPETA_MODELO = Path(__file__).parent.parent / "modelo_modernbert" / "modelo_entrenado"


def main():
    if not CARPETA_MODELO.exists():
        raise SystemExit(f"No existe {CARPETA_MODELO}. Entrena mmBERT primero "
                         f"(python -m modelo_modernbert.entrenar).")

    token = os.environ.get("HF_TOKEN")  # None -> usa el login cacheado
    api = HfApi(token=token)

    print(f"Creando/verificando repo {REPO_ID} (privado)...")
    api.create_repo(repo_id=REPO_ID, repo_type="model", private=True, exist_ok=True)

    print(f"Subiendo {CARPETA_MODELO} ...")
    api.upload_folder(
        repo_id=REPO_ID,
        repo_type="model",
        folder_path=str(CARPETA_MODELO),
        commit_message="Modelo mmBERT DLP fine-tuneado",
    )
    print(f"Listo. Modelo en https://huggingface.co/{REPO_ID}")


if __name__ == "__main__":
    main()
