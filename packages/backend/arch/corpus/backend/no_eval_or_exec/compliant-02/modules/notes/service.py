"""The near-misses for a rule whose subject is two specific builtins.

Every line here contains `eval` or `exec` as a substring and none of them calls the
builtin: a method on an object, a name that merely starts with the word, a keyword
argument, and text. A checker matching the token rather than the call flags them all
and still passes the minimal pair.
"""


class Interpreter:
    def eval(self, source: str) -> int:
        return len(source)


def evaluate(expression: str) -> int:
    return len(expression)


def run(interpreter: Interpreter, pool) -> int:
    # A member call on an app-owned object, not the builtin.
    total = interpreter.eval("1 + 1")
    # A name that contains the word, called as itself.
    total += evaluate("2 + 2")
    # A keyword argument whose name contains one of the words.
    pool.submit(task="report", executor="inline")
    return total
