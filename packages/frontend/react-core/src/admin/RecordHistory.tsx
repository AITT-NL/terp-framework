import { useEffect, useState } from "react";

import type { components } from "@terpjs/contract";

import { Timeline } from "../Timeline";
import type { TimelineEvent } from "../Timeline";
import { useTerpClient } from "../TerpProvider";
import type { BadgeTone } from "../ui/Badge";
import { Card } from "../ui/Card";
import { unwrap } from "../unwrap";
import { useStrings } from "../uiText";
import type { TerpStrings } from "../uiText";

type AuditEventRead = components["schemas"]["AuditEventRead"];

/** How many of a record's events its screen shows: its recent history, not its whole trail. */
const RECENT = 10;

const ACTION_WORDS: Record<string, keyof TerpStrings> = {
  created: "auditActionCreated",
  updated: "auditActionUpdated",
  deleted: "auditActionDeleted",
  disclosed: "auditActionDisclosed",
};

const ACTION_TONES: Record<string, BadgeTone | undefined> = {
  created: "success",
  deleted: "danger",
  disclosed: "info",
};

/** An audit action in the app's words, or as recorded where it is not one the framework names. */
export function auditActionWord(strings: TerpStrings, action: string): string {
  const key = ACTION_WORDS[action];
  const word = key === undefined ? undefined : strings[key];
  return typeof word === "string" ? word : action;
}

/**
 * A record's own history, from the audit trail: what happened to it and when, newest first, as
 * a `Timeline` (ADR 0169 §5) — the trail narrowed to the record the screen is about.
 *
 * Context rather than content, so it fails quietly: a trail the caller cannot read, or one with
 * nothing about this record yet, renders no section at all, and the screen around it is whole
 * without it.
 */
export function RecordHistory({ targetType, targetId }: { targetType: string; targetId: string }) {
  const client = useTerpClient();
  const strings = useStrings();
  const [events, setEvents] = useState<readonly AuditEventRead[] | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const page = unwrap(
          await client.GET("/api/v1/audit/", {
            params: { query: { target_type: targetType, target_id: targetId, limit: RECENT } },
            signal: controller.signal,
          }),
        );
        setEvents(page.items);
      } catch {
        // The history is context: a screen without it still works.
      }
    })();
    return () => controller.abort();
  }, [client, targetType, targetId]);
  if (events === null || events.length === 0) {
    return null;
  }
  const timeline: TimelineEvent[] = events.map((event) => ({
    label: auditActionWord(strings, event.action),
    when: event.created_at,
    detail:
      event.actor_id === null ? undefined : `${strings.actorColumn}: ${event.actor_id.slice(0, 8)}`,
    tone: ACTION_TONES[event.action],
  }));
  return (
    <Card title={strings.recordHistory}>
      <Timeline label={strings.recordHistory} events={timeline} />
    </Card>
  );
}
