import {
  DataView,
  DetailList,
  InMemoryDataViewRepository,
  LocalStorageViewStateRepository,
  OverviewPage,
  useToast,
} from "@terp/react-core";
import type { DataViewColumn } from "@terp/react-core";
import { useMemo } from "react";

/** A demo row: enough shape to exercise sorting, searching, paging and card slots. */
interface Device {
  id: string;
  name: string;
  owner: string;
  status: "active" | "retired" | "repair";
  purchased: string;
}

const OWNERS = ["Ada", "Grace", "Linus", "Margaret", "Alan", "Katherine"];
const STATUSES: Device["status"][] = ["active", "retired", "repair"];
const KINDS = ["Laptop", "Monitor", "Dock", "Phone", "Keyboard", "Headset"];

/** A deterministic 57-row data set, so paging and select-all have something to bite on. */
function makeDevices(): Device[] {
  return Array.from({ length: 57 }, (_, i) => ({
    id: `dev-${i + 1}`,
    name: `${KINDS[i % KINDS.length]} #${i + 1}`,
    owner: OWNERS[i % OWNERS.length] ?? "Ada",
    status: STATUSES[i % STATUSES.length] ?? "active",
    purchased: new Date(Date.UTC(2023, i % 12, (i % 27) + 1)).toISOString().slice(0, 10),
  }));
}

const columns: DataViewColumn<Device>[] = [
  { id: "name", header: "Name", accessor: (d) => d.name, meta: { mobileSlot: "title" } },
  { id: "owner", header: "Owner", accessor: (d) => d.owner, meta: { mobileSlot: "subtitle" } },
  { id: "status", header: "Status", accessor: (d) => d.status, meta: { mobileSlot: "status", width: 100 } },
  { id: "purchased", header: "Purchased", accessor: (d) => d.purchased, meta: { mobileSlot: "date", width: 120 } },
];

const viewState = new LocalStorageViewStateRepository();

/**
 * The client-side DataView example: an {@link InMemoryDataViewRepository} over a plain
 * array (search/sort/filter/paging all inside the repository) with view preferences
 * persisted per `viewId` through the localStorage view-state repository.
 */
export function DevicesExplorer() {
  const toast = useToast();
  const repository = useMemo(
    () =>
      new InMemoryDataViewRepository(makeDevices(), {
        getRowId: (d) => d.id,
        getValue: (d, col) => d[col as keyof Device],
        searchFields: ["name", "owner", "status"],
      }),
    [],
  );

  return (
    <OverviewPage title="Devices">
      <DataView<Device>
        viewId="explorer.devices"
        repository={repository}
        viewStateRepository={viewState}
        columns={columns}
        enableSelection
        searchDebounceMs={300}
        searchPlaceholder="Search devices…"
        pageSizeOptions={[10, 25, 50, 100]}
        onRowClick={(d) => toast.success(`Opened ${d.name}`)}
        batchActions={[
          {
            label: "Retire",
            inline: true,
            onClick: (rows) => toast.success(`Retired ${rows.length} device(s)`),
            onSelectAll: () => toast.success("Retired all matching devices"),
          },
          {
            label: "Delete",
            variant: "destructive",
            inline: false,
            onClick: (rows) => toast.warning(`Deleted ${rows.length} device(s)`),
          },
        ]}
        rowActions={(d) => [
          { label: "Rename", onClick: () => toast.success(`Rename ${d.name}`) },
          {
            label: "Retire",
            variant: "destructive",
            disabled: (row: Device) => row.status === "retired",
            onClick: () => toast.warning(`Retired ${d.name}`),
          },
        ]}
        renderExpanded={(d) => (
          <DetailList
            items={[
              { label: "Owner", value: d.owner },
              { label: "Purchased", value: d.purchased },
            ]}
          />
        )}
      />
    </OverviewPage>
  );
}
