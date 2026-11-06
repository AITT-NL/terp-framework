from terp.core import ModuleAccess, ModuleSpec, Policy, Roles

spec = ModuleSpec(
    name="notes",
    router=router,
    access=ModuleAccess.platform_only(
        reason="handing out grants is the authority that confers every other one",
    ),
    policy=Policy(read=Roles.ADMIN, write=Roles.ADMIN),
)
