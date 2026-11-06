from terp.core import ModuleSpec, Policy

spec = ModuleSpec(
    name="notes",
    router=router,
    policy=Policy(
        read="notes:read",
        write_role="editor",
    ),
)
