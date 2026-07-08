import { useCallback, useRef, useState } from "react";
import type { ChangeEvent, CSSProperties } from "react";

import { useTerpClient } from "./TerpProvider";
import { Button } from "./ui/Button";
import { useStrings, useUiText, type UiText } from "./uiText";
import { unwrap } from "./unwrap";
import type { TerpClient, TerpClientFor } from "@terp/contract";

/**
 * The frontend surface of the files capability (ADR 0056/0057): a token-styled
 * upload control ({@link FileUpload}) and an authenticated download helper
 * ({@link useFileDownload}). The endpoints are app-mounted (the capability is
 * opt-in), so they are not part of the baked base-profile contract; the wire
 * shapes below mirror the capability's DTOs, which the shipped capability keeps
 * stable.
 */

/** A stored file's metadata — the files capability's `FileRead` DTO. */
export interface FileMeta {
  id: string;
  filename: string;
  content_type: string;
  size: number;
  sha256: string;
  owner_id: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

/** The files capability endpoints the helpers call, typed for the shared client. */
interface FilesPaths {
  "/api/v1/files/": {
    post: {
      parameters: { query?: never; header?: never; path?: never; cookie?: never };
      requestBody: { content: { "multipart/form-data": { file: string } } };
      responses: {
        201: { headers: { [name: string]: unknown }; content: { "application/json": FileMeta } };
      };
    };
  };
  "/api/v1/files/{file_id}/content": {
    get: {
      parameters: { path: { file_id: string }; query?: never; header?: never; cookie?: never };
      requestBody?: never;
      responses: {
        200: {
          headers: { [name: string]: unknown };
          content: { "application/octet-stream": string };
        };
      };
    };
  };
}

function filesClient(client: TerpClient): TerpClientFor<FilesPaths> {
  return client as unknown as TerpClientFor<FilesPaths>;
}

/** Upload one file through the typed client; resolves to the stored metadata. */
export async function uploadFile(client: TerpClient, file: File): Promise<FileMeta> {
  return unwrap(
    await filesClient(client).POST("/api/v1/files/", {
      body: { file: "" },
      bodySerializer: () => {
        const form = new FormData();
        form.append("file", file, file.name);
        return form;
      },
    }),
  );
}

/** Fetch a stored file's bytes through the typed client (bearer + cookies attached). */
export async function fetchFileContent(client: TerpClient, fileId: string): Promise<Blob> {
  const { data, error, response } = await filesClient(client).GET(
    "/api/v1/files/{file_id}/content",
    { params: { path: { file_id: fileId } }, parseAs: "blob" },
  );
  return unwrap({ data: data as Blob | undefined, error, response });
}

/**
 * An authenticated file download: fetches `/files/{id}/content` through the session
 * client (a raw `<a href>` would carry no bearer token) and hands the bytes to the
 * browser as a named download.
 */
export function useFileDownload(): (file: Pick<FileMeta, "id" | "filename">) => Promise<void> {
  const client = useTerpClient();
  return useCallback(
    async (file: Pick<FileMeta, "id" | "filename">) => {
      const blob = await fetchFileContent(client as unknown as TerpClient, file.id);
      const url = URL.createObjectURL(blob);
      try {
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = file.filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
      } finally {
        URL.revokeObjectURL(url);
      }
    },
    [client],
  );
}

const hiddenInputStyle: CSSProperties = { display: "none" };

export interface FileUploadProps {
  /** Called with the stored metadata after a successful upload. */
  onUploaded?: (file: FileMeta) => void;
  /** Called when an upload fails (surface it via a toast or an inline error). */
  onError?: (error: unknown) => void;
  /** Button label; defaults to the `uploadFile` string. */
  label?: UiText;
  /** Native file-picker filter, e.g. `"image/*"` or `".pdf"`. */
  accept?: string;
  /** Disable the control (e.g. while the surrounding view is busy). */
  disabled?: boolean;
}

/**
 * The attachment picker for the files capability: a token-styled button that opens the
 * native file dialog and uploads the choice as `multipart/form-data` through the typed
 * session client, reporting the stored {@link FileMeta} to `onUploaded`.
 */
export function FileUpload({ onUploaded, onError, label, accept, disabled }: FileUploadProps) {
  const client = useTerpClient();
  const strings = useStrings();
  const resolve = useUiText();
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);

  async function onChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    // Allow re-selecting the same file to upload it again.
    event.target.value = "";
    if (!file) return;
    setBusy(true);
    try {
      const meta = await uploadFile(client as unknown as TerpClient, file);
      onUploaded?.(meta);
    } catch (error) {
      onError?.(error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        style={hiddenInputStyle}
        onChange={(event) => void onChange(event)}
        aria-hidden="true"
        tabIndex={-1}
      />
      <Button
        type="button"
        variant="secondary"
        disabled={disabled || busy}
        onClick={() => inputRef.current?.click()}
      >
        {busy ? strings.uploading : resolve(label ?? strings.uploadFile)}
      </Button>
    </>
  );
}
