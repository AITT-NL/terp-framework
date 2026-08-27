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
  useUiText,
  useFormatDate,
  useFormatNumber,
} from "@terpjs/react-core";
import type { DataViewColumn } from "@terpjs/react-core";
import { useCallback, useMemo, useState } from "react";

import type { components, paths } from "../../api/schema";

type FileRead = components["schemas"]["FileRead"];

/**
 * A byte count, in the app's locale.
 *
 * `toFixed` always emits a full stop, so this read "1.5 KB" to a Dutch reader who writes "1,5" —
 * the same defect as the dates, in the one place in this app that formats a number. The unit is
 * still chosen here, because that is a presentation decision rather than a locale one.
 */
function formatSize(bytes: number, formatNumber: (value: number) => string): string {
  if (bytes < 1024) return `${formatNumber(bytes)} B`;
  if (bytes < 1024 * 1024) return `${formatNumber(bytes / 1024)} KB`;
  return `${formatNumber(bytes / (1024 * 1024))} MB`;
}

function buildColumns(
  formatDate: (value: string) => string,
  formatSizeIn: (bytes: number) => string,
): DataViewColumn<FileRead>[] {
  return [
    {
      id: "filename",
      header: { id: "files.column.filename", message: "Filename" },
      accessor: (f) => f.filename,
      meta: { mobileSlot: "title" },
    },
    {
      id: "content_type",
      header: { id: "files.column.type", message: "Type" },
      accessor: (f) => f.content_type,
      meta: { mobileSlot: "subtitle" },
    },
    {
      id: "size",
      header: { id: "files.column.size", message: "Size" },
      accessor: (f) => f.size,
      cell: (f) => formatSizeIn(f.size),
      meta: { width: "xs" },
    },
    {
      id: "created_at",
      header: { id: "files.column.uploaded", message: "Uploaded" },
      accessor: (f) => f.created_at,
      cell: (f) => formatDate(f.created_at),
      meta: { mobileSlot: "date", width: "sm" },
    },
  ];
}

/**
 * The files overview: uploads through the react-core `FileUpload` picker, lists the
 * stored files server-side through the typed client, and offers an authenticated
 * download plus a confirmed delete per row — the whole shipped files surface in one view.
 */
export function FilesView() {
  const formatDate = useFormatDate();
  const formatNumber = useFormatNumber();
  const formatSizeIn = useCallback(
    (bytes: number) => formatSize(bytes, (value) => formatNumber(value, { maximumFractionDigits: 1 })),
    [formatNumber],
  );
  const columns = useMemo(() => buildColumns(formatDate, formatSizeIn), [formatDate, formatSizeIn]);
  const client = useTerpClient<paths>();
  const toast = useToast();
  const text = useUiText();
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
      toast.warning(
        text({ id: "files.toast.downloadFailed", message: "Could not download the file" }),
      );
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
      toast.success(text({ id: "files.toast.deleted", message: "File deleted" }));
      setVersion((v) => v + 1);
    } catch {
      toast.warning(
        text({ id: "files.toast.deleteFailed", message: "Could not delete the file" }),
      );
    } finally {
      setDeleting(false);
      setPendingDelete(null);
    }
  }

  return (
    <OverviewPage
      title={{ id: "files.title", message: "Files" }}
      actions={
        <FileUpload
          onUploaded={(file) => {
            toast.success(text({ id: "files.toast.uploaded", message: "File uploaded" }));
            setVersion((v) => v + 1);
          }}
          onError={() =>
            toast.warning(text({ id: "files.toast.uploadFailed", message: "Upload failed" }))
          }
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
          {
            label: { id: "files.download", message: "Download" },
            inline: true,
            onClick: () => void onDownload(file),
          },
          {
            label: { id: "files.delete", message: "Delete" },
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
        title={{ id: "files.confirm.title", message: "Delete this file?" }}
        description={{
          id: "files.confirm.description",
          message: "The stored content is removed permanently.",
        }}
        destructive
        isPending={deleting}
      />
    </OverviewPage>
  );
}
