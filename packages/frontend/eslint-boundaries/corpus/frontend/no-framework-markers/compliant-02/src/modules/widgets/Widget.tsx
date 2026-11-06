export function markOpen(element: HTMLElement) {
  element.setAttribute("data-state", "open");
  element.dataset.testid = "widget-panel";
}
