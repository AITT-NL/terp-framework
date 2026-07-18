import type { TerpStrings } from "../uiText";

export interface AdminRoleOption {
  rank: number;
  label: string;
}

/** The packaged role ladder, localized through the active framework catalog. */
export function adminRoleOptions(strings: TerpStrings): AdminRoleOption[] {
  return [
    { rank: 10, label: strings.roleViewer },
    { rank: 20, label: strings.roleEditor },
    { rank: 30, label: strings.roleAdmin },
  ];
}

export function adminRoleLabel(strings: TerpStrings, rank: number): string {
  return adminRoleOptions(strings).find((option) => option.rank === rank)?.label ?? `rank ${rank}`;
}