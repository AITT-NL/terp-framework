# 0215 — A release carries the deployment it runs

- **Status:** Proposed on 2026-11-13. It implements the framework half of the managed-deployment
  plan, whose decisions the owner took on 2026-11-13: the document is written for the generated
  state only in its first version, its shape is the one terp-spec 0.48.0 publishes, and the
  variables a host owns (its proxy and certificate settings among them) are never the release's.
- **Date:** 2026-11-13.
- **Relates:** [ADR 0187](0187-in-the-generated-state-the-framework-renders-the-build-files.md)
  (`sign` renders the generated state with the commit's own terp-arch, in a process of its own,
  and signs the release), [ADR 0184](0184-a-deployment-declares-its-units.md) (the units a
  deployment declares), [ADR 0071](0071-runtime-role-privilege-split.md) (a runtime role that
  cannot change the schema), [ADR 0210](0210-the-browser-origins-an-api-allows-are-each-environments-own.md)
  (an environment's own origins) and [ADR 0082](0082-repo-split-readiness-spec-as-a-package.md)
  (a contract is read as a package).

## Decision

In the generated state, `terp release sign` writes what the release runs into the signed
manifest, at `outputs.deployment`: terp-spec 0.48.0's `resolved-deployment` document. It holds
one service per declared unit, each image by repository and digest, each command as an argv,
where each variable's value comes from, the mounts, the probes, the start order and the
one-shot service the migration step runs in. It holds nothing an executor or an environment
owns.

1. **The commit's own terp-arch writes it**, in a process of its own as its render is, from the images
   `sign` verified and from the plan its generator writes the profile from, never by reading
   the profile. The start conditions and the probes come from the very helpers the profile is
   written with, and a test holds every golden sample's profile and document together field by
   field, each variable's source and value read from the profile's own text for it.
2. **`sign` holds it to its own terp-arch before signing**: to the copy of terp-spec's schema
   that terp-arch ships, and to the checks terp-spec's fixtures name beyond the schema (ids and
   names each once and in order, every reference resolving, agreement with the declared units,
   the built images and the datastore table), then to what the manifest records beside it: each
   service runs the image `outputs.units` records for its unit, and mounts something at every
   volume its image declares. It signs nothing it refuses, and the refusal names each field. A
   writer and a signer of different releases that disagree are stopped here, not at a deploy. terp-spec's fixtures are the cases every reader runs: this
   repository carries them for its tests beside terp-arch's schema copy, both held to the
   pinned terp-spec byte for byte once it is the release they name.
3. **The manifest is version 2 when it carries the document**, and `outputs.deployment` is then
   required. `terp promote` reads versions 1 and 2, and keeps running the carried profile.
4. **Each built image's configured volumes are recorded** at `outputs.images[*].volumes` in a
   version 2 manifest. Each path no named volume covers becomes an anonymous mount in the
   document, which no backup covers, so an executor can show it rather than discover it. A
   volume no mount can carry (the app root or a path under it, or a path that is not a clean
   absolute one) is refused as the image's, naming the `VOLUME` instruction to change.
5. **Version 1 is generated-only.** An app with its own Compose files signs as before, without
   the document, and so does a commit whose pinned terp-arch is from before the writer: `sign`
   reads whether the wheel ships it from the wheel's file list, never by running it.

## Context

An executor that runs an app's Compose files has to compute its safety facts from them, and
that means reproducing three readers it does not own: a YAML loader, Compose's model and the
engine's container configuration. Every difference between its reading and theirs is a hole,
and each of those programs can add another in its next release. The generator already decides
every field that matters. A closed document that says them in typed form leaves nothing to
reproduce, and lets an executor write its own Compose file, or call the engine directly.

Three shapes follow from terp-spec's validator subset, which has no `null`, `maxProperties` or
`oneOf`: a field that does not apply is absent, collections are capped arrays with ids, and each
variant is chosen by a discriminator. terp-arch's small validator gains the one keyword the new
schema uses that the declaration's did not, `maximum`.

## What the document leaves out

- **The executor's:** the restart policy (decided from each service's `lifecycle`), networks,
  where a port is published (`serves` names only the port inside the container), labels,
  logging and container hardening.
- **The environment's:** resources and instance counts, which the environment's record holds.
- **What nothing writes yet:** an entrypoint, a working directory, a user, a stop grace period, a
  tmpfs mount and a bind mount. Each returns with the feature that writes it.
- **The migration step's connection:** the migration service carries no database reference and
  no command. The executor runs `terp migrate` there with its own argv and the connection that
  may change the schema, and every other backend service names the runtime role's connection.
- **A datastore image's own volumes:** `sign` reads only the images the release builds. A
  datastore's data path is its recipe's, and the named volume the document mounts there.

## Consequences

- The framework owns a contract and its versions. A new deployment feature, such as a sidecar
  or a typed bind, is a change to terp-spec, the framework and every executor.
- An app on a terp-arch without the writer signs a version 1 manifest, which an executor that
  reads only version 2 refuses: managed deployment needs a framework release that ships this,
  and the signer's release table must carry it.
- **The order it lands in.** A reader of version 1 manifests refuses version 2, and the runner
  reads only version 1 today. So the order is: terp-spec 0.48.0 is tagged and the framework's
  two pins move to it; the runner reads version 2; and only then does a signer's release table
  carry a terp-arch that ships the writer. A table that carries it sooner leaves every
  generated release signed on it undeployable by the runner. The release train is the owner's.
- The profile stays, for a plain `docker compose up` and for `terp promote`, and stays the
  generator's.
- The envelope's payload type stays `application/vnd.terp.release-manifest.v1+json`, which
  names the kind of payload a reader verifies; the manifest's own `schemaVersion` names which
  version of it a reader parses.
- A seam the document has no source for, or a bundled store, is refused by name rather than
  signed as a literal no executor would expand. The published datastore table carries no store
  kind, and a test refuses one the document cannot say, since the table and the writer ship in
  one wheel and must move together.

## Considered and rejected

- **Building the document from the written profile.** It brings back the YAML reading the
  document exists to remove.
- **The signer writing the document with its own terp-arch.** The profile is the pinned
  release's render; a document from another release could describe a different deployment
  than the one the profile runs.
- **Services, variables and volumes as maps keyed by id.** The validator subset cannot cap a map.
- **Carrying resources.** The environment's record decides which size runs.
