from wsgiref.simple_server import make_server

from .app import create_wsgi_app
from .server_config import get_server_settings


def main():
    settings = get_server_settings(default_host="127.0.0.1", default_port=5001)
    app = create_wsgi_app(settings.database_path)

    with make_server(settings.host, settings.port, app) as server:
        print(f"SuperAGI chat API listening on http://{settings.host}:{settings.port}")
        print(f"Persisting chat sessions to {settings.database_path}")
        print("Configure SUPERAGI_REPO_PATH and SUPERAGI_CHECKPOINT_PATH to use a trained checkpoint.")
        server.serve_forever()


if __name__ == "__main__":
    main()
