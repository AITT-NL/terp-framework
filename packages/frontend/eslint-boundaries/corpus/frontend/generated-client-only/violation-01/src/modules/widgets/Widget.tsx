export async function load() {
  return fetch("/api/notes");
}
