# 0217 — App components can own a scoped stylesheet

A planning board groups work by status across lanes and stacks those lanes as space
runs out. Requiring each application to wait for a new react-core layout prop makes
that product choice a framework release decision. ADR 0111 asks which safety property
justifies restricting a capability. The typed client and server authorization protect
access to the tasks in both the board and the ordinary task list. Their layout can be
chosen by the application.

This decision amends the styling rules in ADRs 0059 and 0175. An app component may
statically default-import a sibling file named like `Board.module.css` and use an
exported class as `className={styles.board}`. ESLint resolves the import binding in
lexical scope and checks the stylesheet. The initial vocabulary admits local class
selectors, including lists and common interaction states, and responsive groups
using `@media`, `@container` and `@supports`. Cross-file composition, global
selectors and stylesheet imports inside a module are rejected. A CSS-only change
invalidates the boundary CLI's lint cache.

A screen that needs its own composition uses the body of a plain `Page`. Apps can
continue to adopt the standard contract for collections, forms and other archetypes.
Use framework controls for accessible interactions and shared tokens for surfaces,
text and spacing. The adapter checks the class exists, limits class bindings to native elements, and accepts layout and typography declarations plus token-based paint. An import exception cannot waive findings inside the sibling stylesheet.
Visual review and interaction tests establish whether the result works across
themes, input methods and viewport widths.

Vite emits app styles into a same-origin CSS asset allowed by the existing production
policy. The styling allowance gives application code no new client or server
permissions. Dynamic stylesheet loading, inline style attributes and arbitrary
class names still produce findings under the existing catalog ids.
