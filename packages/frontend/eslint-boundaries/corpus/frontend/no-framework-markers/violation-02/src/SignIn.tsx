import { Stack, Trans } from "@terpjs/react-core";

// A replaced sign-in screen, forging the markers the stack's own screen carries so a test
// written against that screen finds this one.
const heading = { "data-terp": "login-title" };

export function SignIn() {
  return (
    <Stack>
      <h1 {...heading}>
        <Trans id="signIn.title" message="Sign in" />
      </h1>
    </Stack>
  );
}
