export function connect(url: string) {
  return new WebSocket(
    url,
    ["v1"],
  );
}

export function subscribe(url: string) {
  return new window.EventSource(url);
}

export function flush(url: string, data: string) {
  navigator.sendBeacon(url, data);
}
