@router.get(
    "/{profile_id}",
    response_model=ProfileRead,
    dependencies=[Depends(require_permission(PROFILES_READ))],
)
def read_profile(profile_id: uuid.UUID, session: SessionDep) -> ProfileRead:
    profile = _service.get(session, profile_id)
    emit_disclosure(target_type="profile", target_id=str(profile.id))
    return ProfileRead.model_validate(profile)
