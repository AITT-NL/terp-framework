from terp.core import OperationCatalog, OperationCoverage, OperationDefinition

NOTES_LIST = OperationDefinition(id="notes.list", label="List every note")
NOTES_CREATE = OperationDefinition(id="notes.create", label="Write a new note")
NOTES_GET = OperationDefinition(id="notes.get", label="View a note")
NOTES_UPDATE = OperationDefinition(id="notes.update", label="Edit a note")
NOTES_DELETE = OperationDefinition(id="notes.delete", label="Delete a note")

operation_catalog = OperationCatalog(
    operations=(NOTES_LIST, NOTES_CREATE, NOTES_GET, NOTES_UPDATE, NOTES_DELETE),
    coverage=OperationCoverage.STRICT,
)
