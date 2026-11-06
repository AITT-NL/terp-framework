class Point(BaseSchema):
    lat: float
    lon: float
class NoteRead(BaseSchema):
    coordinates: Point
    tag_names: list[str]
