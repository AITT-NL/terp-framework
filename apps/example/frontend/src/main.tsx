// The design-token CSS variables the react-core primitives style against (light + dark).
import "@terp/contract/tokens.css";
import { LOCALE_EN, LOCALE_NL, renderTerpApp } from "@terp/react-core";

// The whole app: discover the modules and mount. baseUrl "" keeps API calls same-origin
// so the Vite dev proxy forwards /api to the backend. The SSO provider button mirrors
// the backend's mounted OIDC provider (ADR 0058); its redirect lands on the default
// /auth/callback/{provider} path the provider completes on boot.
renderTerpApp({
  title: "Terp example",
  modules: import.meta.glob("./modules/*/module.tsx", { eager: true }),
  // The app's languages: the shell header offers a persisted picker once a second
  // locale is declared; every react-core string and UiText prop follows the switch.
  locales: { en: LOCALE_EN, nl: LOCALE_NL },
  ssoProviders: [{ name: "dex", label: "Dex" }],
  // One-click fill of the seeded dev sign-in (app/seed.py). import.meta.env.DEV is
  // statically false in production builds, so the credentials never ship in a bundle.
  devCredentials: import.meta.env.DEV
    ? { email: "admin@acme.test", password: "correct horse battery staple" }
    : undefined,
});
