# vendor/terp-core — read-only mirror

A **byte-exact, read-only mirror** of the packaged `terp.core` kernel
(`packages/backend/core/src/terp/core`), present so agents and reviewers have
monorepo-level visibility into the maintained core without editing it (design
§10, ADR 0034).

- **Not on the import path.** The installed `terp-core` distribution is what
  runs; nothing imports this copy. It exists only to be read and searched.
- **Do not edit here.** Change the packaged source under
  `packages/backend/core/`, then refresh this mirror. The gate
  (`tests/architecture/test_vendored_core.py::test_vendored_core_unmodified`)
  fails closed if the two ever diverge.

Refresh:

```bash
python -c "import shutil,pathlib; s=pathlib.Path('packages/backend/core/src/terp/core'); d=pathlib.Path('vendor/terp-core/src/terp/core'); shutil.rmtree(d); shutil.copytree(s,d,ignore=shutil.ignore_patterns('__pycache__'))"
```
