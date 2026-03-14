import uvicorn

from app.core.config import settings


def main() -> None:
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.port)


if __name__ == "__main__":
    main()
