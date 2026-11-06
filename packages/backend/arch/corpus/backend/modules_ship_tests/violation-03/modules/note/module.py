from terp.core import ModuleSpec, Policy, Roles

spec = ModuleSpec(
    name="note",
    router=router,
    policy=Policy(read=Roles.VIEWER, write=Roles.EDITOR),
)
