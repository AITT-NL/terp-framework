import { defineModuleManifest } from "@terpjs/contract";

import { AccessGrantsAdmin } from "./AccessGrantsAdmin";
import { WebhookDeliveriesAdmin } from "./WebhookDeliveriesAdmin";
import { WebhooksAdmin } from "./WebhooksAdmin";

// The app-specific admin surfaces this example adds NEXT TO the packaged admin area
// (react-core ships the /admin hub + users/groups/audit screens in every app): the
// subject-scoped access-grants browser and the webhooks capability's subscriptions +
// deliveries. Gated to the admin role end to end (the UI gate mirrors the backend
// policy; the backend re-checks every call).
export const manifest = defineModuleManifest({
  name: "admin",
  routes: [
    { path: "/admin/grants", view: "AccessGrantsAdmin", role: "admin" },
    { path: "/admin/webhooks", view: "WebhooksAdmin", role: "admin" },
    { path: "/admin/webhooks/deliveries", view: "WebhookDeliveriesAdmin", role: "admin" },
  ],
  nav: [
    { label: "Access grants", to: "/admin/grants", role: "admin", icon: "key" },
    { label: "Webhooks", to: "/admin/webhooks", role: "admin", icon: "zap" },
  ],
});

export const views = { AccessGrantsAdmin, WebhooksAdmin, WebhookDeliveriesAdmin };
