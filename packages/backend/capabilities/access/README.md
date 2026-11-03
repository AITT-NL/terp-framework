# terp-cap-access

`require_permission(PERMISSION)` requires both the permission's minimum role and
its current named grant. Direct and group grants use the same rule. Lowering an
account's role below that floor denies later requests even when its grant remains
stored. A public module or route policy does not bypass the dependency.

The dependency uses the mounted module's authorization context. An assigned
module role may satisfy the floor only when that module declares itself
assignable, and only at a rank declared by the app's permission model. A dotted
permission name does not select a module. A module that has not opted into role
assignment uses the global role alone.

Pass typed `Permission` constants from the control plane. Legacy string arguments
resolve through the mounted app's catalog so their floor cannot be lost; an
unknown name is denied. Calling a dependency directly without a guarded request
context requires a typed `Permission`. A string by itself cannot establish a
minimum role and now fails closed. The lower-level `enforce_permission` seam
continues to answer grant membership only; guards combine it with the role floor.
