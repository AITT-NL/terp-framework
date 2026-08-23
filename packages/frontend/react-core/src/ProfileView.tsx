import { Page } from "./Page";
import { useAuth } from "./TerpProvider";
import { LanguageSwitcher } from "./locale";
import { Stack, DetailList } from "./layout";
import { ThemeToggle } from "./theme";
import { Avatar } from "./ui/Avatar";
import { Button } from "./ui/Button";
import { useStrings } from "./uiText";

/**
 * The built-in profile / settings page the {@link UserMenu}'s Settings item opens.
 * `buildAppRouter` mounts it at `/profile` in every app (an app manifest claiming
 * that path wins): the signed-in identity (avatar, email, role — the server-validated
 * `/me` session, not token claims), the standard theme + language preferences, and
 * sign-out. A `Page` archetype, so it satisfies the routed-view frame control.
 *
 * It renders no inline styles: both cards, the avatar tile and the two identity lines take
 * their geometry and ink from the injected react-core sheet (ADR 0094).
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
        <div data-terp="profile-card">
          <Stack direction="row" gap={3} align="center">
            <Avatar from={user.email} />
            <Stack gap={0}>
              <strong data-terp="profile-email">{user.email}</strong>
              <p data-terp="profile-role">{user.role_name}</p>
            </Stack>
          </Stack>
          <DetailList
            items={[
              { label: strings.email, value: user.email },
              { label: strings.role, value: `${user.role_name} (${user.role_rank})` },
            ]}
          />
        </div>
        <div data-terp="profile-card">
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
