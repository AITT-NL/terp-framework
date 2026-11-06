from terp.core import ModuleSpec, Policy

spec = ModuleSpec(
    name="notes",
    router=router,
    policy=Policy.public(reason="published notes are world-readable"),
)
