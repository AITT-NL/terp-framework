from terp.core import ModuleSpec, Policy

spec = ModuleSpec(
    name="notes",
    router=router,
    policy=Policy.default(),
)
