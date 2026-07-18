import { useState } from "react";
import type { CSSProperties, FormEvent } from "react";

import { TerpMark } from "./icons";
import { useAuth, useSso } from "./TerpProvider";
import { useStrings } from "./uiText";
import { Button } from "./ui/Button";
import { Input } from "./ui/Input";
import type { SsoProvider } from "./sso";

const pageStyle: CSSProperties = {
  minHeight: "100vh",
  display: "grid",
  placeItems: "center",
  padding: "var(--space-6)",
  background: "var(--color-neutral-50)",
  fontFamily: "var(--font-family-sans)",
  color: "var(--color-neutral-900)",
};

const cardStyle: CSSProperties = {
  width: "100%",
  maxWidth: "24rem",
  display: "grid",
  gap: "var(--space-4)",
  padding: "var(--space-6)",
  background: "var(--color-neutral-0)",
  border: "1px solid var(--color-neutral-200)",
  borderRadius: "var(--radius-lg)",
  boxShadow: "var(--shadow-md)",
};

const brandStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "var(--space-2)",
  color: "var(--color-neutral-900)",
};

const brandTitleStyle: CSSProperties = {
  margin: 0,
  fontSize: "var(--font-size-xl)",
  fontWeight: "var(--font-weight-bold)" as CSSProperties["fontWeight"],
  letterSpacing: 0,
};

const formStyle: CSSProperties = { display: "grid", gap: "var(--space-3)" };

const fullWidthStyle: CSSProperties = { width: "100%" };

const separatorStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "var(--space-2)",
  color: "var(--color-neutral-500)",
  fontSize: "var(--font-size-xs)",
  textTransform: "uppercase",
  letterSpacing: "0.06em",
};

const separatorRuleStyle: CSSProperties = {
  flex: 1,
  borderTop: "1px solid var(--color-neutral-200)",
};

const errorStyle: CSSProperties = {
  margin: 0,
  color: "var(--color-status-danger)",
  fontSize: "var(--font-size-sm)",
};

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
    <main style={pageStyle}>
      <div style={cardStyle}>
        <div style={brandStyle}>
          <TerpMark />
          <h1 style={brandTitleStyle}>{strings.signIn}</h1>
        </div>
        <form style={formStyle} onSubmit={onSubmit}>
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
          <Button type="submit" disabled={busy} style={fullWidthStyle}>
            {busy ? strings.signingIn : strings.signIn}
          </Button>
          {devCredentials ? (
            <Button
              type="button"
              variant="secondary"
              disabled={busy}
              style={fullWidthStyle}
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
            <div style={separatorStyle} aria-hidden="true">
              <span style={separatorRuleStyle} />
              <span>{strings.orSeparator}</span>
              <span style={separatorRuleStyle} />
            </div>
            <div style={formStyle}>
              {ssoProviders.map((provider) => (
                <Button
                  key={provider.name}
                  type="button"
                  variant="secondary"
                  disabled={busy}
                  style={fullWidthStyle}
                  onClick={() => void onSso(provider)}
                >
                  {`${strings.continueWith} ${provider.label ?? provider.name}`}
                </Button>
              ))}
            </div>
          </>
        ) : null}
        {error ?? ssoError ? <p style={errorStyle}>{error ?? ssoError}</p> : null}
      </div>
    </main>
  );
}
