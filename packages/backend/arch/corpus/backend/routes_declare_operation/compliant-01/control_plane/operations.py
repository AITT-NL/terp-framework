from terp.core import OperationCatalog, OperationCoverage, OperationDefinition

NOTES_LIST = OperationDefinition(id="notes.list", label="List every note")

operation_catalog = OperationCatalog(
    operations=(NOTES_LIST,), coverage=OperationCoverage.STRICT
)
