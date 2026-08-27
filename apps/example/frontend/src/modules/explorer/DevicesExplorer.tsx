import {
  DataView,
  DetailList,
  InMemoryDataViewRepository,
  LocalStorageViewStateRepository,
  OverviewPage,
  Trans,
  useToast,
  useUiText,
} from "@terpjs/react-core";
import type { DataViewColumn } from "@terpjs/react-core";
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
/** A deterministic 57-row data set, so paging and select-all have something to bite on. */
function makeDevices(kinds: readonly string[]): Device[] {
  return Array.from({ length: 57 }, (_, i) => ({
    id: `dev-${i + 1}`,
    name: `${kinds[i % kinds.length]} #${i + 1}`,
    owner: OWNERS[i % OWNERS.length] ?? "Ada",
    status: STATUSES[i % STATUSES.length] ?? "active",
    purchased: new Date(Date.UTC(2023, i % 12, (i % 27) + 1)).toISOString().slice(0, 10),
  }));
}

const columns: DataViewColumn<Device>[] = [
  {
    id: "name",
    header: { id: "explorer.devices.column.name", message: "Name" },
    accessor: (d) => d.name,
    meta: { mobileSlot: "title" },
  },
  {
    id: "owner",
    header: { id: "explorer.devices.column.owner", message: "Owner" },
    accessor: (d) => d.owner,
    meta: { mobileSlot: "subtitle" },
  },
  {
    id: "status",
    header: { id: "explorer.devices.column.status", message: "Status" },
    accessor: (d) => d.status,
    cell: (d) =>
      d.status === "active" ? (
        <Trans id="explorer.devices.status.active" message="Active" />
      ) : d.status === "retired" ? (
        <Trans id="explorer.devices.status.retired" message="Retired" />
      ) : (
        <Trans id="explorer.devices.status.repair" message="Under repair" />
      ),
    meta: { mobileSlot: "status", width: "xs" },
  },
  {
    id: "purchased",
    header: { id: "explorer.devices.column.purchased", message: "Purchased" },
    // A Date, not the ISO string it is stored as: the shared cell default renders one through
    // the app locale, so this column needs no `cell` of its own and picks up the same shape
    // every other date in the app has.
    accessor: (d) => new Date(d.purchased),
    meta: { mobileSlot: "date", width: "sm" },
  },
];

const viewState = new LocalStorageViewStateRepository();

/**
 * The client-side DataView example: an {@link InMemoryDataViewRepository} over a plain
 * array (search/sort/filter/paging all inside the repository) with view preferences
 * persisted per `viewId` through the localStorage view-state repository.
 */
export function DevicesExplorer() {
  const toast = useToast();
  const text = useUiText();
  const kinds = useMemo(
    () => [
      text({ id: "explorer.devices.kind.laptop", message: "Laptop" }),
      text({ id: "explorer.devices.kind.monitor", message: "Monitor" }),
      text({ id: "explorer.devices.kind.dock", message: "Dock" }),
      text({ id: "explorer.devices.kind.phone", message: "Phone" }),
      text({ id: "explorer.devices.kind.keyboard", message: "Keyboard" }),
      text({ id: "explorer.devices.kind.headset", message: "Headset" }),
    ],
    [text],
  );
  const repository = useMemo(
    () =>
      new InMemoryDataViewRepository(makeDevices(kinds), {
        getRowId: (d) => d.id,
        getValue: (d, col) => d[col as keyof Device],
        searchFields: ["name", "owner", "status"],
      }),
    [kinds],
  );

  return (
    <OverviewPage title={{ id: "explorer.devices.title", message: "Devices" }}>
      <DataView<Device>
        viewId="explorer.devices"
        repository={repository}
        viewStateRepository={viewState}
        columns={columns}
        enableSelection
        searchDebounceMs={300}
        searchPlaceholder={{
          id: "explorer.devices.search",
          message: "Search devices…",
        }}
        pageSizeOptions={[10, 25, 50, 100]}
        getRowLabel={(d) => d.name}
        onRowClick={() =>
          toast.success(
            text({ id: "explorer.devices.toast.opened", message: "Device opened" }),
          )
        }
        batchActions={[
          {
            label: { id: "explorer.devices.retire", message: "Retire" },
            inline: true,
            onClick: () =>
              toast.success(
                text({
                  id: "explorer.devices.toast.retiredSelection",
                  message: "Selected devices retired",
                }),
              ),
            onSelectAll: () =>
              toast.success(
                text({
                  id: "explorer.devices.toast.retiredAll",
                  message: "All matching devices retired",
                }),
              ),
          },
          {
            label: { id: "explorer.devices.delete", message: "Delete" },
            variant: "destructive",
            inline: false,
            onClick: () =>
              toast.warning(
                text({
                  id: "explorer.devices.toast.deletedSelection",
                  message: "Selected devices deleted",
                }),
              ),
          },
        ]}
        rowActions={(d) => [
          {
            label: { id: "explorer.devices.rename", message: "Rename" },
            onClick: () =>
              toast.success(
                text({ id: "explorer.devices.toast.rename", message: "Rename device" }),
              ),
          },
          {
            label: { id: "explorer.devices.retire", message: "Retire" },
            variant: "destructive",
            disabled: (row: Device) => row.status === "retired",
            onClick: () =>
              toast.warning(
                text({ id: "explorer.devices.toast.retired", message: "Device retired" }),
              ),
          },
        ]}
        renderExpanded={(d) => (
          <DetailList
            items={[
              {
                label: { id: "explorer.devices.column.owner", message: "Owner" },
                value: d.owner,
              },
              {
                label: {
                  id: "explorer.devices.column.purchased",
                  message: "Purchased",
                },
                value: d.purchased,
              },
            ]}
          />
        )}
      />
    </OverviewPage>
  );
}
