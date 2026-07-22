"""Generic ORM row -> dict helper shared by all feature serializers."""


def row(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}
