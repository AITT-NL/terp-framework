import { useEffect, useState } from "react";

import { Alert } from "../ui/Alert";
import { Badge } from "../ui/Badge";
import { Card } from "../ui/Card";
import { ErrorState } from "../ErrorState";
import { LoadingState } from "../LoadingState";
import { Page } from "../Page";
import { Stack } from "../layout";
import { TileGroup } from "../ui/TileGroup";
import { useTerpClient } from "../TerpProvider";
import { useStrings } from "../uiText";
import type { TerpStrings } from "../uiText";
import { unwrap } from "../unwrap";

import { adminCrumb, renderAdminCrumb } from "./crumbs";
import { buildModuleRows } from "./accessModel";
import type { AccessModel, ModuleRow } from "./accessModel";
import { tilesFor } from "./accessTiles";

function ModuleCard({ row, strings }: { row: ModuleRow; strings: TerpStrings }) {
  return (
    <Card key={row.name}>
      <Stack gap={2}>
        <Stack direction="row" gap={2} align="center">
          <strong>{row.label}</strong>
          <code>{row.name}</code>
          {row.platformReason !== null && (
            <Badge tone="warning">{strings.accessNeverAssignable}</Badge>
          )}
          {row.platformReason === null && !row.assignable && (
            <Badge tone="neutral">{strings.accessNotAssignable}</Badge>
          )}
        </Stack>
        {row.platformReason !== null && (
          // Rendered, not hovered. The reason is the useful part — a module simply absent from
          // the pane leaves a question an administrator cannot stop asking — and an explanation
          // you have to discover by hovering is not one, which is the same argument that puts
          // the delta on the tile instead of in a tooltip.
          <span data-terp="tile-note">{row.platformReason}</span>
        )}
        {row.unexplainedRoutes > 0 && (
          <Alert tone="warning">
            {strings.accessUnexplainedRoutes.replace("{count}", String(row.unexplainedRoutes))}
          </Alert>
        )}
        <span data-terp="tile-note">{strings.accessAdds}</span>
        {/* A description, not a disabled control: this screen explains the declared model, and
            there is nothing here to choose. Choosing a rung for a person happens where the
            person is, which is the only place the choice has a subject — and it writes through
            the same rows this screen describes. */}
        <TileGroup label={row.label} tiles={tilesFor(row, strings)} readOnly />
      </Stack>
    </Card>
  );
}

/**
 * `/admin/access` — which roles exist, and what each one may do per module.
 *
 * The read-only half of the permission surface, and the first screen that answers the question
 * the whole design is for: *these are the roles, and this is what each role gets in this
 * module*. Every allowance shown is the kernel guard's own answer, projected per rung by
 * `GET /api/v1/access/model` (ADR 0121 §4) — this screen groups and diffs those answers and
 * forms no opinion about them, so it cannot disagree with the gate.
 *
 * It deliberately does not show *who holds what*. That question has a subject and belongs where
 * the subject is; conflating the declared model with the assignments against it is how a pane
 * ends up implying that changing a tile here changes someone's access.
 *
 * There is no empty state, deliberately: `create_app` mounts the base-profile capabilities in
 * every app, so a composed application always has modules to describe. A branch no test can
 * reach is a claim nobody checks, and the honest alternative to guarding it is not having it.
 */
export function AccessAdmin() {
  const client = useTerpClient();
  const strings = useStrings();
  const [model, setModel] = useState<AccessModel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const loaded = unwrap(await client.GET("/api/v1/access/model", {}));
        if (live) setModel(loaded);
      } catch (cause: unknown) {
        if (live) setError(cause instanceof Error ? cause.message : String(cause));
      } finally {
        if (live) setLoading(false);
      }
    })();
    return () => {
      live = false;
    };
  }, [client]);

  const rows = model === null ? [] : buildModuleRows(model);

  return (
    <Page
      title={strings.adminAccess}
      description={strings.adminAccessDescription}
      breadcrumbs={[{ ...adminCrumb(strings), to: "/admin" }]}
      renderLink={renderAdminCrumb}
    >
      <Stack gap={3}>
        <Alert tone="info">{strings.accessDeclaredOnly}</Alert>
        {loading && <LoadingState />}
        {!loading && error !== null && <ErrorState description={error} />}
        {rows.map((row) => (
          <ModuleCard key={row.name} row={row} strings={strings} />
        ))}
      </Stack>
    </Page>
  );
}
