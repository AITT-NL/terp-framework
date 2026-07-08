"""terp.core — the Terp platform kernel (the public API surface).

Importing from ``terp.core`` is the only sanctioned way for a module to use the
platform. Everything under :mod:`terp.core._internal` is import-forbidden
outside core; the public names below are the semver contract.

The authoritative import namespace is ``terp.*`` — never ``platform.*`` (it
shadows a stdlib module).
"""

from __future__ import annotations

from terp.core.app import BootError, PermissionEnforcer, Principal, create_app, get_principal
from terp.core.app import enforces_token_revocation, mark_token_revocation_provider
from terp.core.audit import (
    AuditAction,
    AuditPolicy,
    AuditRecord,
    DurableAuditSink,
    bind_audit_actor,
    current_actor_id,
    is_durable_audit_sink,
)
from terp.core.base_models import (
    ActorStampedMixin,
    BaseSchema,
    BaseTable,
    BaseUpdateSchema,
    OwnedMixin,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from terp.core.base_service import BaseService
from terp.core.cache import (
    CacheStore,
    InMemoryCacheStore,
    configure_cache,
    get_cache,
    is_shared_cache_store,
    mark_shared_cache_store,
)
from terp.core.config import Settings, get_settings, settings
from terp.core.control_plane import ControlPlane
from terp.core.crud import build_crud_router
from terp.core.db import SessionDep, get_session
from terp.core.errors import (
    AppError,
    AuthenticationError,
    ConflictError,
    InvalidTokenError,
    NotFoundError,
    PermissionDeniedError,
    StaleDataError,
    ValidationFailedError,
    build_error_envelope,
)
from terp.core.idempotency import (
    BeginOutcome,
    IdempotencyStore,
    InMemoryIdempotencyStore,
    StoredResponse,
    is_shared_idempotency_store,
    mark_shared_idempotency_store,
)
from terp.core.events import (
    EventCatalog,
    EventDefinition,
    EventEnvelope,
    EventError,
    EventVisibility,
    emit,
)
from terp.core.jobs import (
    InProcessJobQueue,
    JobCatalog,
    JobContext,
    JobDefinition,
    JobEnvelope,
    JobError,
    JobQueue,
    JobVisibility,
    RetryPolicy,
    enqueue,
    is_durable_job_queue,
    mark_durable_job_queue,
    register_job_tenant_context,
)
from terp.core.logging import configure_logging, get_request_id, request_id_ctx
from terp.core.migrations import (
    MigrationDiscoveryError,
    MigrationTree,
    resolve_all_migration_trees,
    resolve_migration_target,
    resolve_migration_trees,
)
from terp.core.module_spec import ModuleSpec, Policy, Roles
from terp.core.object_authz import (
    ObjectAuthzPredicate,
    register_object_authz_predicate,
)
from terp.core.pagination import (
    CursorPage,
    CursorPaginationDep,
    CursorPaginationParams,
    Page,
    PaginationDep,
    PaginationParams,
)
from terp.core.passwords import PasswordPolicy, WeakPasswordError, validate_password
from terp.core.permissions import (
    ADMIN,
    EDITOR,
    VIEWER,
    AuthorizationRequirement,
    Permission,
    PermissionModel,
    Role,
    as_role,
)
from terp.core.scheduling import (
    ScheduleCatalog,
    ScheduleDefinition,
    Scheduler,
    trigger_schedule,
)
from terp.core.scoping import ScopePredicate, register_scope_predicate
from terp.core.secrets import (
    SecretsError,
    decrypt_config,
    encrypt_config,
    is_sealed_config,
    mask_config,
    register_decrypt_call_site,
)
from terp.core.security import (
    CorsPolicy,
    RateLimit,
    SecurityConfig,
    SecurityHeaders,
    client_ip,
)
from terp.core.throttling import (
    InMemoryThrottleStore,
    ThrottleStore,
    is_shared_throttle_store,
    mark_shared_throttle_store,
)

__all__ = [
    "ADMIN",
    "ActorStampedMixin",
    "AppError",
    "AuditAction",
    "AuditPolicy",
    "AuditRecord",
    "AuthenticationError",
    "AuthorizationRequirement",
    "BaseSchema",
    "BaseService",
    "BaseTable",
    "BaseUpdateSchema",
    "BeginOutcome",
    "BootError",
    "CacheStore",
    "ConflictError",
    "ControlPlane",
    "CorsPolicy",
    "CursorPage",
    "CursorPaginationDep",
    "CursorPaginationParams",
    "DurableAuditSink",
    "EDITOR",
    "EventCatalog",
    "EventDefinition",
    "EventEnvelope",
    "EventError",
    "EventVisibility",
    "IdempotencyStore",
    "InMemoryCacheStore",
    "InMemoryIdempotencyStore",
    "InMemoryThrottleStore",
    "InProcessJobQueue",
    "InvalidTokenError",
    "JobCatalog",
    "JobContext",
    "JobDefinition",
    "JobEnvelope",
    "JobError",
    "JobQueue",
    "JobVisibility",
    "MigrationDiscoveryError",
    "MigrationTree",
    "ModuleSpec",
    "NotFoundError",
    "ObjectAuthzPredicate",
    "OwnedMixin",
    "Page",
    "PaginationDep",
    "PaginationParams",
    "PasswordPolicy",
    "Permission",
    "PermissionDeniedError",
    "PermissionEnforcer",
    "PermissionModel",
    "Policy",
    "Principal",
    "RateLimit",
    "RetryPolicy",
    "Role",
    "Roles",
    "ScheduleCatalog",
    "ScheduleDefinition",
    "Scheduler",
    "ScopePredicate",
    "SecretsError",
    "SecurityConfig",
    "SecurityHeaders",
    "SessionDep",
    "Settings",
    "SoftDeleteMixin",
    "StaleDataError",
    "StoredResponse",
    "ThrottleStore",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "VIEWER",
    "ValidationFailedError",
    "WeakPasswordError",
    "as_role",
    "bind_audit_actor",
    "build_crud_router",
    "build_error_envelope",
    "client_ip",
    "configure_cache",
    "configure_logging",
    "create_app",
    "current_actor_id",
    "decrypt_config",
    "emit",
    "encrypt_config",
    "enforces_token_revocation",
    "enqueue",
    "get_cache",
    "get_principal",
    "get_request_id",
    "get_session",
    "get_settings",
    "is_durable_audit_sink",
    "is_durable_job_queue",
    "is_sealed_config",
    "is_shared_cache_store",
    "is_shared_idempotency_store",
    "is_shared_throttle_store",
    "mark_durable_job_queue",
    "mark_shared_cache_store",
    "mark_shared_idempotency_store",
    "mark_shared_throttle_store",
    "mark_token_revocation_provider",
    "mask_config",
    "register_decrypt_call_site",
    "register_job_tenant_context",
    "register_object_authz_predicate",
    "register_scope_predicate",
    "request_id_ctx",
    "resolve_all_migration_trees",
    "resolve_migration_target",
    "resolve_migration_trees",
    "settings",
    "trigger_schedule",
    "validate_password",
]
