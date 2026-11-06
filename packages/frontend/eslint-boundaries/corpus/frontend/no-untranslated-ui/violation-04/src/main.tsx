export function Status({ ready }: { ready: boolean }) {
  return (
    <>
      {ready ? "Ready" : "Waiting"}
      {ready && "Start now"}
      {["First item", "Second item"]}
      {{ primary: "Save changes", fallback: "Cancel changes" }}
    </>
  );
}
