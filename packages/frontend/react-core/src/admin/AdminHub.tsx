import { Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import type { components } from "@terpjs/contract";

import { ProportionBar } from "../charts/ProportionBar";
import { TrendChart } from "../charts/TrendChart";
import type { ChartPoint } from "../charts/TrendChart";
import { DashboardPage } from "../DashboardPage";
import { useFormatDate, useFormatNumber } from "../format";
import { HubCard } from "../HubPage";
import type { RenderHubCardLink } from "../HubPage";
import type { AdminAreaSections } from "../bootstrap";
import { NavIcon } from "../icons";
import { Grid } from "../layout";
import type { GridTemplate } from "../layout";
import { Stat, StatGroup } from "../Stat";
import { useTerpClient } from "../TerpProvider";
import { unwrap } from "../unwrap";
import { fillPlaceholders, useStrings } from "../uiText";
import { viewerTimeZone } from "../viewerTimeZone";
import { auditActionTone, auditActionWord } from "./RecordHistory";

type AuditActivityRead = components["schemas"]["AuditActivityRead"];
type AuditDayCount = components["schemas"]["AuditDayCount"];

const renderLink: RenderHubCardLink = ({ to, children }) => <Link to={to}>{children}</Link>;

/** The days the hub's activity chart draws; the read returns as many days before them too. */
const ACTIVITY_DAYS = 30;

/** The days the activity figure sums, read from the end of the same days. */
const FIGURE_DAYS = 7;

/** The area cards' tracks, one per card; a single card takes the row (`columns={1}`). */
const CARD_TEMPLATES: Record<number, GridTemplate> = { 2: "1:1", 3: "1:1:1", 4: "1:1:1:1" };

interface HubData {
  accounts: number | null;
  activeAccounts: number | null;
  groups: number | null;
  activity: AuditActivityRead | null;
}

/** A `YYYY-MM-DD` day as that day, wherever the browser is: `new Date(day)` would read UTC. */
function localDay(isoDate: string): Date {
  const [year, month, day] = isoDate.split("-").map(Number);
  return new Date(year!, month! - 1, day!);
}

/**
 * The hub's figures and the trail's activity, each read on its own so one that fails leaves the
 * others standing. A section the app dropped never fires its reads: its capability may not be
 * mounted at all. The active accounts are a total under the status filter, and the activity is
 * counted on the server, so nothing is counted from a page in the browser.
 */
function useHubData(sections: Required<AdminAreaSections>): HubData {
  const client = useTerpClient();
  const [data, setData] = useState<HubData>({
    accounts: null,
    activeAccounts: null,
    groups: null,
    activity: null,
  });
  const { users: wantUsers, groups: wantGroups, audit: wantAudit } = sections;
  useEffect(() => {
    const controller = new AbortController();
    const signal = controller.signal;
    const keep = <K extends keyof HubData>(key: K, read: () => Promise<HubData[K]>) => {
      void read().then(
        (value) => {
          if (!signal.aborted) setData((current) => ({ ...current, [key]: value }));
        },
        // The page stays usable without the figure: it keeps its dash (offline, a race).
        () => undefined,
      );
    };
    if (wantUsers) {
      keep("accounts", async () =>
        unwrap(await client.GET("/api/v1/users/", { params: { query: { limit: 1 } }, signal })).total,
      );
      keep("activeAccounts", async () =>
        unwrap(
          await client.GET("/api/v1/users/", {
            params: { query: { is_active: true, limit: 1 } },
            signal,
          }),
        ).total,
      );
    }
    if (wantGroups) {
      keep("groups", async () =>
        unwrap(await client.GET("/api/v1/groups/", { params: { query: { limit: 1 } }, signal })).total,
      );
    }
    if (wantAudit) {
      keep("activity", async () => {
        const read = (time_zone: string) =>
          client.GET("/api/v1/audit/activity", {
            params: { query: { days: ACTIVITY_DAYS, time_zone } },
            signal,
          });
        const zone = viewerTimeZone();
        const answer = await read(zone);
        // A zone the server's database does not know is refused (400). Counted in UTC the
        // trail is a day off at worst; refused, the figure kept its dash and both charts were
        // gone, with nothing on the page to say why.
        if (answer.response.status === 400 && zone !== "UTC") return unwrap(await read("UTC"));
        return unwrap(answer);
      });
    }
    return () => controller.abort();
  }, [client, wantUsers, wantGroups, wantAudit]);
  return data;
}

function sum(days: readonly AuditDayCount[]): number {
  return days.reduce((total, day) => total + day.count, 0);
}

/**
 * The packaged admin hub (`/admin`): a dashboard of the administration (ADR 0171). The summary
 * band carries the active accounts — the headline — the groups and the trail's last week; the
 * areas follow as cards, getting to one being the hub's first job; then the trail per day
 * against the days before, and the kinds of change. The sidebar's single "Admin" entry opens
 * it, and the overviews breadcrumb back to it, keeping the hub -> overview -> detail layering
 * every Terp screen follows. `sections` (default: all) mirrors the app's `adminArea` selection:
 * a dropped section loses its card, its figure, its reads and, for the audit log, its charts.
 */
export function AdminHub({ sections }: { sections?: AdminAreaSections } = {}) {
  const strings = useStrings();
  const formatDate = useFormatDate();
  const formatNumber = useFormatNumber();
  const selected = {
    users: sections?.users !== false,
    groups: sections?.groups !== false,
    audit: sections?.audit !== false,
    access: sections?.access !== false,
  };
  const data = useHubData(selected);
  const activity = data.activity;
  const points = (days: readonly AuditDayCount[]): ChartPoint[] =>
    days.map((day) => ({ label: formatDate(localDay(day.date)), value: day.count }));
  const lastWeek = activity === null ? null : activity.days.slice(-FIGURE_DAYS);
  const weekBefore =
    activity === null ? null : activity.days.slice(-2 * FIGURE_DAYS, -FIGURE_DAYS);
  // Two reads that run side by side, so an account made between them could make this -1.
  const deactivated =
    data.accounts === null || data.activeAccounts === null
      ? null
      : Math.max(0, data.accounts - data.activeAccounts);

  const figures = [
    selected.users && (
      <Stat
        key="accounts"
        headline
        label={strings.adminHubActiveAccounts}
        value={data.activeAccounts}
        caption={
          deactivated === null
            ? undefined
            : fillPlaceholders(strings.adminHubDeactivated, { count: formatNumber(deactivated) })
        }
      />
    ),
    selected.groups && <Stat key="groups" label={strings.adminGroups} value={data.groups} />,
    selected.audit && (
      <Stat
        key="changes"
        label={fillPlaceholders(strings.adminHubChangesWeek, { count: formatNumber(FIGURE_DAYS) })}
        value={lastWeek === null ? null : sum(lastWeek)}
        delta={
          lastWeek === null || weekBefore === null
            ? undefined
            : {
                value: sum(lastWeek) - sum(weekBefore),
                sentiment: "neutral",
                label: strings.adminHubVsWeekBefore,
              }
        }
        trend={lastWeek === null ? undefined : points(lastWeek)}
      />
    ),
  ].filter(Boolean);

  const cards = [
    selected.users && (
      <HubCard
        key="users"
        to="/admin/users"
        title={strings.adminUsers}
        description={strings.adminUsersDescription}
        icon={<NavIcon name="users" label={strings.adminUsers} />}
        renderLink={renderLink}
      />
    ),
    selected.groups && (
      <HubCard
        key="groups"
        to="/admin/groups"
        title={strings.adminGroups}
        description={strings.adminGroupsDescription}
        icon={<NavIcon name="shield" label={strings.adminGroups} />}
        renderLink={renderLink}
      />
    ),
    selected.audit && (
      <HubCard
        key="audit"
        to="/admin/audit"
        title={strings.adminAudit}
        description={strings.adminAuditDescription}
        icon={<NavIcon name="audit" label={strings.adminAudit} />}
        renderLink={renderLink}
      />
    ),
    selected.access && (
      <HubCard
        key="access"
        to="/admin/access"
        title={strings.adminAccess}
        description={strings.adminAccessDescription}
        icon={<NavIcon name="shield" label={strings.adminAccess} />}
        renderLink={renderLink}
      />
    ),
  ].filter(Boolean);

  return (
    <DashboardPage
      title={strings.admin}
      parents={[{ label: strings.home, to: "/" }]}
      summary={figures.length > 0 ? <StatGroup>{figures}</StatGroup> : undefined}
    >
      {/* As many tracks as cards: a fixed three left a blank column beside two cards and gave
          one card a third of the row. */}
      {cards.length > 1 ? (
        <Grid as="ul" template={CARD_TEMPLATES[cards.length]}>
          {cards}
        </Grid>
      ) : (
        <Grid as="ul" columns={1}>
          {cards}
        </Grid>
      )}
      {selected.audit && activity !== null && (
        <TrendChart
          label={strings.adminHubChangesPerDay}
          mark="columns"
          series={{
            label: fillPlaceholders(strings.adminHubLastDays, { count: formatNumber(ACTIVITY_DAYS) }),
            points: points(activity.days),
          }}
          comparison={{
            label: fillPlaceholders(strings.adminHubDaysBefore, { count: formatNumber(ACTIVITY_DAYS) }),
            points: points(activity.previous_days),
          }}
        />
      )}
      {selected.audit && activity !== null && activity.by_action.length > 0 && (
        <ProportionBar
          label={fillPlaceholders(strings.adminHubChangesByKind, { count: formatNumber(ACTIVITY_DAYS) })}
          parts={activity.by_action.map((row) => ({
            label: auditActionWord(strings, row.action),
            value: row.count,
            tone: auditActionTone(row.action),
          }))}
        />
      )}
    </DashboardPage>
  );
}
