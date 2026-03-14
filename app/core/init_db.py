from app.core.database import Base, engine
from app.repositories import models  # noqa: F401


if __name__ == '__main__':
    Base.metadata.create_all(bind=engine)
