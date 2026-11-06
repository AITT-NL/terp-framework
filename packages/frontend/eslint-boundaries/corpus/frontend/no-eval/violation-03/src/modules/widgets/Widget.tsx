export function compile(body: string) {
  return new Function(
    "input",
    body,
  );
}

export function compileQualified(body: string) {
  return new window.Function("input", body);
}
