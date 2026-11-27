"""Ordinary service implementation of the quote examples in the business rules design."""

from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from sqlmodel import Field, Session

from terp.capabilities.access import require_permission
from terp.core import (
    EDITOR,
    AuditAction,
    BaseSchema,
    BaseService,
    BaseTable,
    BaseUpdateSchema,
    ConflictError,
    Permission,
    Principal,
    ValidationFailedError,
)

APPROVE = Permission("quotes.approve", EDITOR)
PLACE = Permission("quotes.place", EDITOR)
_MOVES = {
    ("draft", "approved"): APPROVE,
    ("approved", "draft"): APPROVE,
    ("approved", "ordered"): PLACE,
}
Status = Literal["draft", "approved", "ordered"]
Amount = Annotated[Decimal, Field(max_digits=12, decimal_places=2)]
Percent = Annotated[Decimal, Field(max_digits=5, decimal_places=2)]


class Quote(BaseTable, table=True):
    __tablename__ = "test_quote_persistence"
    revenue: Decimal = Field(max_digits=12, decimal_places=2)
    material_cost: Decimal = Field(max_digits=12, decimal_places=2)
    labour_cost: Decimal = Field(max_digits=12, decimal_places=2)
    discount_pct: Decimal = Field(max_digits=5, decimal_places=2)
    margin: Decimal = Field(max_digits=12, decimal_places=2)
    status: str = Field(max_length=20)


class QuoteCreate(BaseSchema):
    revenue: Amount
    material_cost: Amount
    labour_cost: Amount
    discount_pct: Percent
    status: Status = "draft"

    @property
    def margin(self) -> Decimal:
        return self.revenue - self.material_cost - self.labour_cost


class QuotePatch(BaseUpdateSchema):
    revenue: Amount | None = None
    material_cost: Amount | None = None
    labour_cost: Amount | None = None
    discount_pct: Percent | None = None
    status: Status | None = None


class _PricedPatch(QuotePatch):
    margin: Decimal


def _check_discount(percent: Decimal) -> None:
    if percent > 25:
        raise ValidationFailedError("A discount above 25% is refused.")


class QuoteService(BaseService[Quote, QuoteCreate, QuotePatch]):
    model = Quote

    def __init__(self, principal: Principal) -> None:
        self.principal = principal

    def create(self, session: Session, data: QuoteCreate) -> Quote:
        if data.status != "draft":
            raise ConflictError("A new quote starts in draft.")
        _check_discount(data.discount_pct)
        row = Quote(**data.model_dump(), margin=data.margin)
        return self._save(session, row, AuditAction.CREATED)

    def update(self, session: Session, entity_id: UUID, data: QuotePatch) -> Quote:
        row = self.get(session, entity_id)
        patch = data.model_dump(exclude_unset=True)
        proposed = QuoteCreate.model_validate(row.model_dump() | patch)
        if proposed.status != row.status:
            permission = _MOVES.get((row.status, proposed.status))
            if permission is None:
                raise ConflictError("This quote transition is unavailable.")
            require_permission(permission)(session=session, principal=self.principal)
        if proposed.discount_pct != row.discount_pct:
            _check_discount(proposed.discount_pct)
        return super().update(
            session, entity_id, _PricedPatch(**patch, margin=proposed.margin)
        )
