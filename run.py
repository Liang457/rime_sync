"""rime_server 启动入口：python run.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import create_app  # noqa: E402
from app.settings import Settings  # noqa: E402


def main() -> None:
    root = Path(__file__).resolve().parent
    settings = Settings(root / "config" / "server.json")
    app = create_app(settings_path=settings.path, root_dir=root)

    from waitress import serve

    print(f"rime_server http://{settings.host}:{settings.port}/  "
          f"控制台{'已设密码' if settings.password_hash else '免登录（可信局域网模式）'}")
    serve(
        app,
        host=settings.host,
        port=settings.port,
        threads=8,
    )


if __name__ == "__main__":
    main()
