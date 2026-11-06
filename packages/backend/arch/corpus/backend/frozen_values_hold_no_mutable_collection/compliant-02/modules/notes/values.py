from dataclasses import dataclass


# Not frozen, so nothing is promised and a list is an honest field. The rule is
# about a claim that does not hold, never about mutability itself.
@dataclass
class ImportDraft:
    name: str
    columns: list[str]
