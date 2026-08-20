import { useState } from "react";
import type { FormEvent } from "react";

import { TerpMark } from "./icons";
import { useAuth, useSso } from "./TerpProvider";
import { useStrings } from "./uiText";
import { Button } from "./ui/Button";
import { Input } from "./ui/Input";
import type { SsoProvider } from "./sso";

export interface LoginViewProps {
  /**
   * SSO providers to offer alongside the credentials form (ADR 0058). Each renders a
   * "Continue with {label}" button that opens the provider flow through the session's
   * SSO seam; the redirect/callback completion is handled by `TerpProvider`.
   */
  ssoProviders?: readonly SsoProvider[];
  /**
   * Development-only convenience: when set, the form offers a button that fills these
   * credentials (typically the seeded dev admin). Gate it on the build, e.g.
   * `import.meta.env.DEV ? { email, password } : undefined`, so the credentials are
   * statically stripped from production bundles — never pass real secrets.
   */
  devCredentials?: DevCredentials;
}

/** The credentials the dev-only fill button enters — see {@link LoginViewProps.devCredentials}. */
export interface DevCredentials {
  email: string;
  password: string;
}

/**
 * The default signed-out screen: collects credentials and calls the auth session. Used by
 * {@link renderTerpApp}/`RequireAuth` unless an app supplies its own login view. Pass
 * {@link LoginViewProps.ssoProviders} to add SSO provider buttons under the form.
 *
 * It renders no inline styles: the full-viewport page, the card, the brand row, both button
 * groups, the separator and the error line take their geometry and ink from the injected
 * react-core sheet (ADR 0094). The buttons fill their group through a rule on the group
 * rather than a prop on `Button` — `Button` declares `width: fit-content`, so a grid does not
 * stretch them for free, and a `block` prop for one internal caller is API this does not need.
 */
export function LoginView({ ssoProviders = [], devCredentials }: LoginViewProps = {}) {
  const auth = useAuth();
  const sso = useSso();
  const strings = useStrings();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await auth.login({ email, password });
    } catch {
      setError(strings.signInFailed);
    } finally {
      setBusy(false);
    }
  }

  async function onSso(provider: SsoProvider) {
    setError(null);
    setBusy(true);
    try {
      // Navigates away on success; only a failed authorize fetch reaches the catch.
      await sso.begin(provider.name);
    } catch {
      setError(strings.ssoFailed);
      setBusy(false);
    }
  }

  const ssoError = sso.error !== null && sso.error !== undefined ? strings.ssoFailed : null;

  return (
    <main data-terp="login-view">
      <div data-terp="login-card">
        <div data-terp="login-brand">
          <TerpMark />
          <h1 data-terp="login-title">{strings.signIn}</h1>
        </div>
        <form data-terp="login-form" onSubmit={onSubmit}>
          <Input
            type="email"
            placeholder={strings.email}
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />
          <Input
            type="password"
            placeholder={strings.password}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
          <Button type="submit" disabled={busy}>
            {busy ? strings.signingIn : strings.signIn}
          </Button>
          {devCredentials ? (
            <Button
              type="button"
              variant="secondary"
              disabled={busy}
              onClick={() => {
                setEmail(devCredentials.email);
                setPassword(devCredentials.password);
                setError(null);
              }}
            >
              {strings.fillDevCredentials}
            </Button>
          ) : null}
        </form>
        {ssoProviders.length > 0 ? (
          <>
            <div data-terp="login-separator" aria-hidden="true">
              <span data-terp="login-separator-rule" />
              <span>{strings.orSeparator}</span>
              <span data-terp="login-separator-rule" />
            </div>
            <div data-terp="login-sso">
              {ssoProviders.map((provider) => (
                <Button
                  key={provider.name}
                  type="button"
                  variant="secondary"
                  disabled={busy}
                  onClick={() => void onSso(provider)}
                >
                  {`${strings.continueWith} ${provider.label ?? provider.name}`}
                </Button>
              ))}
            </div>
          </>
        ) : null}
        {error ?? ssoError ? (
          <p role="alert" data-terp="login-error">
            {error ?? ssoError}
          </p>
        ) : null}
      </div>
    </main>
  );
}
