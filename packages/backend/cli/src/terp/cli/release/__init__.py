"""``terp release`` and ``terp promote``: a release cut in three jobs, signed, and deployed.

ADR 0187 decision 6 makes ADR 0184 decision 9's ``terp release`` three jobs, so that no job that
runs the app outside a build container holds a credential or writes into what is built:

* ``terp release build`` (:mod:`.build`) builds the commit's images from its pristine tree in
  a builder of its own, and pushes them;
* ``terp release gate`` (:mod:`.gate`) runs the release profile in a checkout of the commit,
  holding no push credential and no key, and reads the schedules from the pushed image;
* ``terp release sign`` (:mod:`.sign`) is the operator's own toolchain: it checks what ``build``
  pushed against the commit, as data, runs nothing of the app, and signs the manifest
  (:mod:`.manifest`) as a DSSE envelope (:mod:`.dsse`).

``terp promote`` (:mod:`.promote`) verifies an envelope and deploys exactly the digests it signs.
Each module is imported by the command that needs it, so ``terp`` itself does not load them.
"""

from __future__ import annotations
