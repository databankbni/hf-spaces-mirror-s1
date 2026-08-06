import argparse

from app.server import run


def main() -> None:
    parser = argparse.ArgumentParser(description="Servidor local do VagaCheck")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    args = parser.parse_args()
    run(args.host, args.port)


if __name__ == "__main__":
    main()
