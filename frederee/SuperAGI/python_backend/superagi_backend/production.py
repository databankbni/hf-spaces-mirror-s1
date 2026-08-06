from .app import create_wsgi_app
from .server_config import get_server_settings


def main():
    settings = get_server_settings(default_host="0.0.0.0", default_port=7860)
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    app = create_wsgi_app(settings.database_path)

    from waitress import serve

    print(f"SuperAGI chat API listening on http://{settings.host}:{settings.port}")
    print(f"Persisting chat sessions to {settings.database_path}")
    print("Configure SUPERAGI_REPO_PATH and SUPERAGI_CHECKPOINT_PATH to use a trained checkpoint.")
    serve(app, host=settings.host, port=settings.port, threads=4)


if __name__ == "__main__":
    main()
