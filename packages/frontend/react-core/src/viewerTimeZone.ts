/**
 * The viewer's own time zone, as an IANA name, or `UTC` where the host cannot say.
 *
 * The one question about the host the app has no answer of its own for. Dates are formatted in
 * the app's locale everywhere, but a calendar day is the viewer's: the admin hub counts the
 * audit trail in the days of whoever is looking at it (ADR 0171). Its own module so the
 * locale gate's allowance covers this one read and nothing that might format beside it.
 */
export function viewerTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}
