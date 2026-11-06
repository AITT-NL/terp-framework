export function Widget({ used }: { used: number }) {
  return <meter value={used} min={0} max={1} />;
}
