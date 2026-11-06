@router.post(
    "/",
    response_model=ProfileRead,
    status_code=201,
    dependencies=[Depends(require_permission(PROFILES_WRITE))],
)
def create_profile(payload: ProfileCreate, session: SessionDep) -> ProfileRead:
    return ProfileRead.model_validate(_service.create(session, payload))
