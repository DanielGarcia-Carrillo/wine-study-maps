# Consumed pyshp reader surface. Attributes remain objects until validated.
class Record:
    def __getitem__(self, key: str) -> object: ...

class Shape:
    points: list[tuple[float, float]]
    parts: list[int]

class ShapeRecord:
    record: Record
    shape: Shape

class Reader:
    def __init__(self, path: str) -> None: ...
    def shapeRecords(self) -> list[ShapeRecord]: ...
    def records(self) -> list[Record]: ...
