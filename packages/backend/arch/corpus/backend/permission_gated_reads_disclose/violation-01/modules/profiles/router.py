@router.get(
    "/",
    response_model=list[ProfileRead],
    dependencies=[Depends(require_permission(PROFILES_READ))],
)
def list_profiles(session: SessionDep) -> list[ProfileRead]:
    return [ProfileRead.model_validate(row) for row in _service.list(session)]
