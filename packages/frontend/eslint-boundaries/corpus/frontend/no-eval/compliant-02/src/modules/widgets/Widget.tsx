const interpreter = {
  eval(expression: string): number {
    return expression.length;
  },
};

export function describeExpression(expression: string) {
  // eval(expression) would be refused here; this is a member call on a local object.
  const hint = "eval() and new Function() are refused in app modules";
  return `${interpreter.eval(expression)} ${hint}`;
}
