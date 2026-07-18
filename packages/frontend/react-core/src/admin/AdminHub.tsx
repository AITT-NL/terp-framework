import { Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import { HubCard, HubPage } from "../HubPage";
import type { RenderHubCardLink } from "../HubPage";
import { NavIcon } from "../icons";
import { useTerpClient } from "../TerpProvider";
import { unwrap } from "../unwrap";
import { useStrings } from "../uiText";

const renderLink: RenderHubCardLink = ({ to, children }) => <Link to={to}>{children}</Link>;

interface HubStats {
  users: number | null;
  groups: number | null;
}

/** Live totals for the hub cards (a `limit=1` page carries the exact total). */
function useHubStats(): HubStats {
  const client = useTerpClient();
  const [stats, setStats] = useState<HubStats>({ users: null, groups: null });
  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const [users, groups] = await Promise.all([
          client.GET("/api/v1/users/", {
            params: { query: { limit: 1 } },
            signal: controller.signal,
          }),
          client.GET("/api/v1/groups/", {
            params: { query: { limit: 1 } },
            signal: controller.signal,
          }),
        ]);
        setStats({ users: unwrap(users).total, groups: unwrap(groups).total });
      } catch {
        // The cards stay navigable without their stat lines (e.g. offline, races).
      }
    })();
    return () => controller.abort();
  }, [client]);
  return stats;
}

/**
 * The packaged admin hub (`/admin`): one card per administration area — users,
 * groups and the audit log — with live totals where they are cheap to know.
 * The sidebar's single "Admin" entry opens this hub; the overviews breadcrumb
 * back to it, keeping the hub -> overview -> detail layering every Terp screen
 * follows.
 */
export function AdminHub() {
  const strings = useStrings();
  const stats = useHubStats();
  return (
    <HubPage title={strings.admin} parents={[{ label: strings.home, to: "/" }]}>
      <HubCard
        to="/admin/users"
        title={strings.adminUsers}
        description={strings.adminUsersDescription}
        icon={<NavIcon name="users" label={strings.adminUsers} />}
        stat={stats.users !== null ? String(stats.users) : undefined}
        renderLink={renderLink}
      />
      <HubCard
        to="/admin/groups"
        title={strings.adminGroups}
        description={strings.adminGroupsDescription}
        icon={<NavIcon name="shield" label={strings.adminGroups} />}
        stat={stats.groups !== null ? String(stats.groups) : undefined}
        renderLink={renderLink}
      />
      <HubCard
        to="/admin/audit"
        title={strings.adminAudit}
        description={strings.adminAuditDescription}
        icon={<NavIcon name="audit" label={strings.adminAudit} />}
        renderLink={renderLink}
      />
    </HubPage>
  );
}
