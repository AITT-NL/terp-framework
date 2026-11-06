from terp.core import ModuleSpec, Policy, Roles

spec = ModuleSpec(
    name="notes",
    router=router,
    policy=Policy(
        read=Roles.ADMIN,
        write=Roles.EDITOR,
    ),
)
