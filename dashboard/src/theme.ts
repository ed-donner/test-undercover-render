// The dashboard's appearance, the one setting each browser keeps for itself:
// light, dark or the same as the computer. It is set as data-theme on the
// page, where styles.css picks the colors up.
export const appearances = ["light", "dark", "system"] as const;
export type Appearance = (typeof appearances)[number];

const KEY = "undercover-appearance";

export function savedAppearance(): Appearance {
  const saved = localStorage.getItem(KEY);
  return appearances.find((appearance) => appearance === saved) ?? "system";
}

// Shows the page in an appearance, and keeps it for this browser.
export function chooseAppearance(appearance: Appearance) {
  localStorage.setItem(KEY, appearance);
  showAppearance(appearance);
}

// Sets the page's colors for an appearance, before React renders as well, so
// the page never shows the wrong theme first.
export function showAppearance(appearance: Appearance) {
  if (appearance === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = appearance;
}
