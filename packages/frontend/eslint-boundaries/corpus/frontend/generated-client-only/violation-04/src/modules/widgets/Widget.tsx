export function transportFactory() {
  const Ctor = XMLHttpRequest;
  return Ctor;
}

export const events = EventSource;
