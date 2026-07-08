import type { CSSProperties } from "react";

import { Page } from "./Page";
import { useAuth } from "./TerpProvider";
import { LanguageSwitcher } from "./locale";
import { Stack, DetailList } from "./layout";
import { ThemeToggle } from "./theme";
import { userInitials } from "./UserMenu";
import { Button } from "./ui/Button";
import { useStrings } from "./uiText";

const avatarStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  width: "3.5rem",
  height: "3.5rem",
  flexShrink: 0,
  borderRadius: "var(--radius-full)",
  background: "var(--color-brand-primary)",
  color: "var(--color-brand-primary-contrast)",
  fontSize: "var(--font-size-lg)",
  fontWeight: "var(--font-weight-medium)" as CSSProperties["fontWeight"],
};

const mutedStyle: CSSProperties = { margin: 0, color: "var(--color-neutral-600)" };

const cardStyle: CSSProperties = {
  display: "grid",
  gap: "var(--space-4)",
  padding: "var(--space-4)",
  maxWidth: "32rem",
  background: "var(--color-neutral-0)",
  border: "1px solid var(--color-neutral-200)",
  borderRadius: "var(--radius-lg)",
};

/**
 * The built-in profile / settings page the {@link UserMenu}'s Settings item opens.
 * `buildAppRouter` mounts it at `/profile` in every app (an app manifest claiming
 * that path wins): the signed-in identity (avatar, email, role — the server-validated
 * `/me` session, not token claims), the standard theme + language preferences, and
 * sign-out. A `Page` archetype, so it satisfies the routed-view frame control.
 */
export function ProfileView() {
  const auth = useAuth();
  const strings = useStrings();
  const user = auth.currentUser();
  if (user === null) {
    return null; // RequireAuth gates the shell; this is unreachable when signed out.
  }
  return (
    <Page title={strings.profile}>
      <Stack gap={4}>
        <div style={cardStyle}>
          <Stack direction="row" gap={3} align="center">
            <span aria-hidden="true" style={avatarStyle}>
              {userInitials(user.email)}
            </span>
            <Stack gap={0}>
              <strong style={{ overflowWrap: "anywhere" }}>{user.email}</strong>
              <p style={mutedStyle}>{user.role_name}</p>
            </Stack>
          </Stack>
          <DetailList
            items={[
              { label: strings.email, value: user.email },
              { label: strings.role, value: `${user.role_name} (${user.role_rank})` },
            ]}
          />
        </div>
        <div style={cardStyle}>
          <ThemeToggle />
          <LanguageSwitcher />
          <div>
            <Button variant="secondary" onClick={() => void auth.logout()}>
              {strings.signOut}
            </Button>
          </div>
        </div>
      </Stack>
    </Page>
  );
}
