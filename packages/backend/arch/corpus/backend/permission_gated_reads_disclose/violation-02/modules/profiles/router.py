@router.get("/{profile_id}", response_model=ProfileRead)
def read_profile(
    profile_id: uuid.UUID,
    session: SessionDep,
    _granted: None = Depends(require_permission(PROFILES_READ)),
) -> ProfileRead:
    return ProfileRead.model_validate(_service.get(session, profile_id))
