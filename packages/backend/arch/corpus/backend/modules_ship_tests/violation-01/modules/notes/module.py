from terp.core import ModuleSpec, Policy, Roles

spec = ModuleSpec(
    name="notes",
    router=router,
    policy=Policy(read=Roles.VIEWER, write=Roles.EDITOR),
)
