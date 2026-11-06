export async function load(path: string) {
  return globalThis.fetch(path);
}

export async function loadComputed(path: string) {
  return window["fetch"](path);
}

export const transport = fetch;
