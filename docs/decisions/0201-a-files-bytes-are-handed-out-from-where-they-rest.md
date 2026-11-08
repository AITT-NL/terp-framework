# 0201 — A file's bytes are handed out from where they rest

- **Status:** Accepted; built in 0.36.1. Decision 3 amended in 0.39.0 (see there).
- **Date:** 2026-11-05.
- **Relates:** [ADR 0056](0056-files-capability.md) (the capability), [ADR 0057](0057-files-storage-profiles-and-references.md)
  (named profiles, `FileRef` and the serve-through read this extends),
  [ADR 0066](0066-files-streaming-storage-port.md) (the streamed port the adapters implement),
  [ADR 0146](0146-the-deployment-brings-the-scanner-the-platform-keeps-the-verdict.md) (the
  quarantine gate a link passes through), [ADR 0148](0148-a-route-declares-its-own-posture-not-its-neighbours.md)
  and [ADR 0138](0138-a-mount-that-verifies-credentials-declares-its-own-rate-limit.md) (how the
  one public route here declares itself), the sealing domains of `terp.core.secrets` (what
  signs an app-issued link), and [ADR 0197](0197-a-public-site-is-a-client-of-an-app-and-the-framework-defines-its-socket.md)
  (a public site copies the media it shows, so a link is for an app's own clients).

---

## Decision in one paragraph

A storage backend may hand out a short-lived link to one blob, and the files capability mints
such a link only after the checks a download passes: the row's scope, the quarantine gate and
the route's policy. Where the backend cannot link, the capability signs a link of the same
shape itself and serves the bytes with `Range` support. Two adapters ship as optional extras,
for Azure Blob Storage and for S3. An app that configures nothing keeps today's behaviour.

## Context

The files capability streams every download through the API process, from the one adapter
that ships (local disk), with no `Range` support. Three things an app with media needs are
missing, and the gap is structural rather than a matter of tuning:

1. **A player cannot send a bearer.** An `<audio>` or `<video>` element, a PDF viewer and a
   native client's media stack fetch a URL with no header on it. Today the only URL is the
   authenticated download route, so the single-page app cannot point a player at a file at
   all, and a native client must pull the bytes through its own authenticated fetch.
2. **A seek needs `Range`.** Without it a player downloads the whole file to move the position,
   and a cached partial download cannot resume.
3. **The API process is the wrong place for gigabytes.** Every byte of every download passes
   through a worker of the API, which exists to answer requests, not to serve media. The
   evidence is an app whose content is large media for consumer accounts: tens of megabytes
   per item, a native client that caches and seeks, and a backoffice job that converts items
   to another format.

ADR 0057 already names the shape: the same S3/Azure-style adapter registered under several
profiles. What was never decided is how a client reaches a blob that rests in such a store
without the API in the middle, and what keeps that reach as narrow as a download.

## Decisions

### 1. The port grows one optional method

```python
class StorageBackend(abc.ABC):
    def link(self, key: str, *, ttl: timedelta, content_type: str, disposition: str) -> str | None:
        return None  # the API serves the bytes
```

A backend that returns a URL hands the bytes out itself; one that returns `None` leaves it to
the API. The link carries the download's own media type and `Content-Disposition` header
where the store can be told (a presigned URL's response-header parameters, a SAS's `rscd` and
`rsct`), so a client is told the same thing by either path; the service builds that header,
so the filename is encoded once, the same way, for both. `put`, `open` and `delete` are unchanged, and the
in-memory backend of the test suite proves the default path.

### 2. Two adapters, as extras

`terp-cap-files[azure]` installs `AzureBlobStorage` and `terp-cap-files[s3]` installs
`S3Storage`. Each is one class per provider, registered once per profile as ADR 0057 has it,
and takes the provider's own client object and the container or bucket. The Azure adapter
imports its SDK when it is built, never when its module loads, and fails at boot with the
install line without the extra; the S3 adapter imports nothing from its SDK at all, because
every error it maps is a class the client it was given carries. Each implements `link` with
the provider's signed URL for the `ttl` asked, capped at 24 hours: a presigned GET for S3; for
Azure a read-only blob SAS, signed with a user-delegation key when a `BlobServiceClient` under
an Entra credential is given, with the account key when the container client holds one, and
not at all otherwise, so the API serves the bytes. The tests drive S3 through the SDK's real
client under its stubber, with the real presigner, and Azure through a fake of the container
client's small surface, checked against the real client's shape, with the SDK's own signer and
exception types; running either against an emulator in the conformance lane is a later change
of its own.

**Amended in 0.39.0: an S3 link never outlives its signature.** A URL signed with temporary
credentials (a role's, an instance profile's, an SSO session's) stops working when they expire,
whatever its own expiry says, so a link could die before the `expires_at` the service reported.
The S3 adapter now signs only when the credentials it signs with outlive the link by a minute,
judged after botocore refreshes credentials about to lapse and before the URL is signed; where
they do not, where a session token's expiry cannot be read, and where the client holds no
credentials, it hands out none and the API serves the bytes behind an app-signed link for the
whole lifetime. Long-term keys carry no token and sign as before. botocore reads a client's
credentials only through its private `_get_credentials`; were that removed, links would come
from the API, never from credentials nobody judged. A deployment whose links should come from
the store gives its role a session longer than its longest link.

### 3. A link is minted where a download is authorized

`FileService.link(session, file_id, *, ttl=None, inline=False) -> FileLink` runs the same checks as
`open_stream`: `get` honours the row scope, so an invisible row is a 404 before any store is
asked, and `ensure_servable` refuses a quarantined row. Then the row's own backend is asked for
a link; `FileLink` carries the URL and its expiry, nothing else. `link_for(session, referencing,
column, ...)` is the serve-through form of ADR 0057: a module mints a link through its own,
already-authorized row and a declared `FileRef`, never through a bare column.

The router gains `GET /api/v1/files/{id}/link`, under the module's policy exactly as the
download is, answering the `FileLink`. The default `ttl` is one hour and the longest any
caller gets is 24 hours; a player makes many range requests over a listening session, so a
link is not single-use, and its expiry is the control. `inline` asks for the bytes to be shown
rather than saved, and is honoured only for a type a browser renders without running anything
in it (image, audio, video, PDF): a stored HTML page is an attachment whatever was asked, so
nothing a user uploaded is ever rendered on the API's own origin.

**Amended in 0.39.0.** A review found that a content type was judged by what came before its
first `;`. So `image/png, text/html` passed an `image/*` allowlist, met no signature check, since
none is listed for it, was shown inline as an image, and was served back raw as the
`Content-Type`, where a browser takes the last type of a list and renders HTML. An upload's
content type must now be one media type, a type and a subtype with parameters (RFC 9110) and no
comma anywhere, or it is refused with a 415, `content_type_malformed`, before any byte lands. The
inline rule and the served `Content-Type` judge the parsed type: a row an earlier release stored
with a list is served as `application/octet-stream`, as an attachment, and handed to a store's
own link the same way.

### 4. Where the backend cannot link, the capability signs one

For the local adapter, and for a store whose credentials cannot sign, the service mints an
**app-signed link**: a token sealed under a sealing domain of its own (`files.link`) carrying
the file id, the expiry and whether the bytes are shown inline, served at
`GET /api/v1/files/link/{token}`. That route is declared `Policy.public(reason=...)` on the
route (ADR 0148), with its own rate limit (ADR 0138), and it is the only public route of the
capability. It opens the token, refuses an expired, altered or foreign one with a 404 that does
not say which (a token longer than any it mints is refused by the path's length cap before it
is read), runs `ensure_servable` again (a verdict can change after a link was minted), and
streams with `Range` support. The token is the secret:
whoever holds it reads until it expires, which is the posture of a provider's signed URL too.

### 5. `Range`, on the two routes the API serves bytes from

The authenticated content route and the app-signed route honour one `bytes=` range: `206` with
`Content-Range`, `Accept-Ranges: bytes` on every answer, `416` for a range the file cannot
satisfy, and a multi-range request answered whole with `200`, as RFC 9110 allows. The local
adapter's stream seeks; a stream that cannot seek is read and discarded up to the offset, which
only an adapter that neither links nor seeks would pay.

**Amended in 0.39.0: the store reads the range.** The last sentence was wrong. The
authenticated content route serves the bytes of every profile, a store that links included, and
both shipped adapters return a stream that cannot seek: a seek far into a large object fetched
every byte before it, and Azure's own downloader fetched its first 32 MiB on every open before
it returned at all. The route now reads the range before it opens the bytes, and the port has a
second method with a default, `open_range(key, *, offset, length)`. The default opens the whole
blob and moves to the offset, as before; the S3 adapter overrides it with one ranged `GET`, and
the Azure adapter reads every blob in windows of at most 4 MiB, one request each as the stream
is read, every window after the first naming the blob's ETag so two versions never splice into
one body. An adapter of an app's own keeps working unchanged, and overrides `open_range` when its
store can read a range.

### 6. What does not change

`storage_key` never leaves the API: a provider's link embeds the blob's address as the provider's
own URL, which is the provider's business and expires with the link. `FileRead` is unchanged.
The upload path, the scanner, the content-type allowlist and the delete are unchanged. A site
built from ADR 0198's recipe still copies the media it shows, because a link expires and a
built page does not.

## Deferred, each a record of its own

- **Direct-to-storage uploads** (a signed upload link, a finalize call, resumable parts) and
  with them a per-profile size cap enforced by the store. The 25 MiB default and
  `configure_upload_limit` stand until then.
- **Revoking a link before it expires.** Keep the TTL short; a store's own revocation (rotating
  the delegation key) is the operator's.
- **A CDN in front of a store**, and image or video transforms.

## Two-layer enforcement

- **Runtime:** a link is minted only through `get` (scope) and `ensure_servable`, under the
  module's policy; an app-signed token is sealed, its expiry is enforced on the server, and the
  public route is rate-limited and answers 404 to every token it cannot open.
- **Build time:** tests hold that a quarantined or invisible row gets no link, that an altered,
  expired or foreign token is a 404, the `Range` semantics of both routes, both adapters'
  round trips and links through their fakes, that the default port path still serves, and
  that `FileRead` still carries no storage address.

## Consequences

- An app gives a player, a viewer or a native client a URL, and the bytes come from the store
  that holds them; the API process streams bytes only for a store that cannot sign, and on the
  authenticated content route, for a caller who asks it to.
- A deployment moves media to a store with one composition-root line per profile and no
  migration; rows written before keep the profile they name.
- `terp-cap-files` gains two optional extras and one public route, declared and rate-limited.
