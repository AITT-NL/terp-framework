from terp.core import ModuleAccess, ModuleSpec, Policy, Roles

spec = ModuleSpec(
    name="notes",
    router=router,
    access=ModuleAccess(label="Notes", assignable=True),
    policy=Policy(read=Roles.VIEWER, write=Roles.EDITOR),
)
