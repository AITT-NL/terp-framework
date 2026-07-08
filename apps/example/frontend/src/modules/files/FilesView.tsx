import {
  ConfirmDialog,
  DataView,
  FileUpload,
  HttpDataViewRepository,
  OverviewPage,
  unwrap,
  useFileDownload,
  useServerDataView,
  useTerpClient,
  useToast,
} from "@terp/react-core";
import type { DataViewColumn } from "@terp/react-core";
import { useMemo, useState } from "react";

import type { components, paths } from "../../api/schema";

type FileRead = components["schemas"]["FileRead"];

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const columns: DataViewColumn<FileRead>[] = [
  { id: "filename", header: "Filename", accessor: (f) => f.filename, meta: { mobileSlot: "title" } },
  {
    id: "content_type",
    header: "Type",
    accessor: (f) => f.content_type,
    meta: { mobileSlot: "subtitle" },
  },
  {
    id: "size",
    header: "Size",
    accessor: (f) => f.size,
    cell: (f) => formatSize(f.size),
    meta: { width: 100 },
  },
  {
    id: "created_at",
    header: "Uploaded",
    accessor: (f) => f.created_at,
    cell: (f) => new Date(f.created_at).toLocaleDateString(),
    meta: { mobileSlot: "date", width: 120 },
  },
];

/**
 * The files overview: uploads through the react-core `FileUpload` picker, lists the
 * stored files server-side through the typed client, and offers an authenticated
 * download plus a confirmed delete per row — the whole shipped files surface in one view.
 */
export function FilesView() {
  const client = useTerpClient<paths>();
  const toast = useToast();
  const download = useFileDownload();
  const serverQuery = useServerDataView({ initialPageSize: 10 });
  const [version, setVersion] = useState(0);
  const [pendingDelete, setPendingDelete] = useState<FileRead | null>(null);
  const [deleting, setDeleting] = useState(false);

  const repository = useMemo(
    () =>
      new HttpDataViewRepository<FileRead>({
        getRowId: (f) => f.id,
        // The files endpoint pages but does not search/sort; the repo advertises that.
        search: false,
        request: async ({ skip, limit }, signal) => {
          const page = unwrap(
            await client.GET("/api/v1/files/", {
              params: { query: { skip, limit } },
              signal,
            }),
          );
          return { items: page.items, total: page.total };
        },
      }),
    // `version` re-creates the repository after a mutation so the list refetches.
    [client, version],
  );

  async function onDownload(file: FileRead) {
    try {
      await download(file);
    } catch {
      toast.warning(`Could not download ${file.filename}`);
    }
  }

  async function onConfirmDelete() {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      unwrap(
        await client.DELETE("/api/v1/files/{file_id}", {
          params: { path: { file_id: pendingDelete.id } },
        }),
      );
      toast.success(`Deleted ${pendingDelete.filename}`);
      setVersion((v) => v + 1);
    } catch {
      toast.warning(`Could not delete ${pendingDelete.filename}`);
    } finally {
      setDeleting(false);
      setPendingDelete(null);
    }
  }

  return (
    <OverviewPage
      title="Files"
      actions={
        <FileUpload
          onUploaded={(file) => {
            toast.success(`Uploaded ${file.filename}`);
            setVersion((v) => v + 1);
          }}
          onError={() => toast.warning("Upload failed")}
        />
      }
    >
      <DataView<FileRead>
        viewId="files.list"
        repository={repository}
        columns={columns}
        serverQuery={serverQuery}
        pageSizeOptions={[10, 25, 50]}
        rowActions={(file) => [
          { label: "Download", inline: true, onClick: () => void onDownload(file) },
          {
            label: "Delete",
            variant: "destructive",
            onClick: () => setPendingDelete(file),
          },
        ]}
      />
      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
        onConfirm={() => void onConfirmDelete()}
        title={`Delete ${pendingDelete?.filename ?? "file"}?`}
        description="The stored content is removed permanently."
        destructive
        isPending={deleting}
      />
    </OverviewPage>
  );
}
