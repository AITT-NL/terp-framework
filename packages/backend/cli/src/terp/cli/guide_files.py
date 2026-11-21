"""The ``terp guide files`` topic: file objects, where they are stored, and who may read them."""

from __future__ import annotations

TOPIC = """\
File objects (files capability, ADR 0056/0057)

- Upload/download/list/rename/delete ride the admin-only discovered router at
  /api/v1/files; File composes OwnedMixin, so rename/delete are owner-gated centrally.
- Bytes live behind the StorageBackend port (put/open/delete, streamed via file-like
  objects, and open_range for a Range request: its default reads forward to the offset, so an
  adapter whose store reads a range overrides it) in a NAMED-PROFILE registry;
  metadata (name, type, size, sha256, storage_key, storage_profile) lives in the platform
  DB. FileRead omits storage_key and storage_profile, and the API's routes never show them;
  a store's signed link carries the key as its URL path, which opens nothing on a private
  store without the signature.
- Any provider is an adapter subclass (local ships; a NAS mount is the local adapter on
  another root). Two object-store adapters ship behind extras (ADR 0201): S3Storage
  (terp-cap-files[s3]) takes the SDK's own client and a bucket; AzureBlobStorage
  (terp-cap-files[azure]) takes the SDK's ContainerClient and, for user-delegation SAS
  links, a BlobServiceClient under an Entra credential. Register each store once at the
  composition root:
      register_storage_backend("s3-media", S3Storage(boto3.client("s3"), bucket="app-media"))
      register_storage_backend("azure-invoices", AzureBlobStorage(invoices_container))
      register_storage_backend("azure-hr", AzureBlobStorage(hr_container, delegation=service))
  Keep credentials in settings / sealed config — never in module code. Building the Azure
  adapter without its extra fails at boot with the install line (StorageSdkMissingError);
  the S3 adapter takes the SDK's client, so a missing extra fails where that is built.
- A client that cannot send a bearer (an <audio>/<video> element, a PDF viewer, a native
  client's media stack) gets a short-lived LINK to one file's bytes instead (ADR 0201):
      GET /api/v1/files/{id}/link?ttl_seconds=600&inline=true   ->  {url, expires_at}
  The link is minted where a download is authorized (row scope, then quarantine), by the
  store the ROW names: an S3 presigned GET or an Azure SAS where the store can sign, else
  an app-signed token the capability serves itself at GET /api/v1/files/link/{token} —
  its one public route, rate-limited, answering 404 to an expired, altered or foreign
  token. The default lifetime is an hour, the longest 24 hours; a link is not single-use
  (a player makes many range requests), its expiry is the control. inline is honoured only
  for a type a browser renders without running it (image, audio, video, PDF — not an XML
  image such as SVG, which is a document with script in it). From a module, mint through
  your own authorized row and a declared FileRef:
      link = FileService().link_for(session, invoice, "attachment_file_id", ttl=timedelta(minutes=10))
  Both content routes honour one bytes= Range (206 / 416); the local adapter seeks, an
  object store's stream is read forward. A link from a store that signs never streams
  through the API; the authenticated content route still serves any store's bytes to a
  caller who asks it to.
- Pick the store per module (subclass default) or per call — never from a client:
      class InvoiceFileService(FileService):
          storage_profile = "azure-invoices"
      service.store(session, filename=..., content_type=..., source=..., profile="azure-hr")
  Resolution is FAIL-CLOSED: an unknown profile raises (UnknownStorageProfileError)
  before any byte lands; load/remove always resolve the store the ROW itself names.
- Uploads stream (never fully buffered) under a 25 MiB default cap; the files spec
  declares its own request-body allowance so the kernel's global max_request_bytes
  (1 MiB default) is lifted for /api/v1/files ONLY (ADR 0067). Retune per deployment
  with two composition-root lines (the request allowance must exceed the stored cap
  by multipart framing headroom):
      configure_upload_limit(100 * 1024 * 1024)
      create_app(..., request_size_overrides={"files": 100 * 1024 * 1024 + 65536})
- Content types are allowed by default (descriptive metadata); a deployment narrows
  uploads to an allowlist with one composition-root line — enforced in the service
  chokepoint (typed 415, before any byte lands), so no upload path can bypass it:
      configure_allowed_content_types(["application/pdf", "image/*"])
- Referencing a file from your own model? Declare it — never a bare uuid column (the
  no_raw_file_references rule enforces this on table models):
      class Invoice(BaseTable, table=True):
          attachment_file_id: uuid.UUID | None = FileRef()
  Serve it THROUGH your own already-authorized row (serve-through delegation): load the
  invoice via your own service (its policy + row scope decide visibility), then
      row, data = FileService().load_for(session, invoice, "attachment_file_id")
  load_for fail-closes on an undeclared reference; /api/v1/files itself stays ADMIN-only.
- The local profile's bytes need a volume in production, or they live in the container and
  go with it. The template's production profile (use_files) mounts the files-data volume at
  var/files on api, and deployment.json declares it with its backup policy, so a deploy tool
  backs it up. A unit of your own that reads stored bytes (a worker) mounts the same volume:
  add it to the profile and to the volume's "mount": {"units": [...]}. A store behind
  another adapter needs no volume. `terp guide deployment` has the rest.
- Every process checks its local roots BEFORE it serves (ADR 0218): create_app creates each
  local profile's root and writes and removes a probe file there. Outside ENVIRONMENT=local a
  root the app's user cannot write REFUSES the start, one sentence naming the path, the cause
  and the uid (a BootError, which Terp Studio shows at release verification); in local it is
  a warning. A writable root on the container's own disk (no volume) is a warning, never a
  refusal. The production image makes the root its runtime user's before it drops to it:
      RUN useradd --create-home --uid 10001 appuser \\
          && mkdir -p /srv/var/files && chown appuser /srv/var/files
  and the profile mounts the volume there, declared under its top-level volumes too (Compose
  refuses a named volume a service mounts and the file does not declare):
      services:
        api:
          volumes:
            - "files-data:/srv/var/files"
      volumes:
        files-data:
  An app rendered before template 0.35 has neither: re-render (`copier update`; the volume
  comes only when the recorded use_files answer is true, so where it is false:
  `copier update --data use_files=true`) or add both (`terp maintenance` names the case).
  A volume an older image made is root's; chown it once:
      docker compose -f docker-compose.prod.yml run --rm --no-deps --user root api \\
          chown 10001 /srv/var/files
  Register every storage profile BEFORE create_app: one registered later is not probed. A
  store behind a network adapter is not called at boot; its failures, like a local root that
  breaks after boot, answer a typed 502 (file_storage_failed), the cause in the log only.
"""
