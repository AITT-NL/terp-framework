export function append(el: HTMLElement | null, markup: string) {
  el?.insertAdjacentHTML(
    "beforeend",
    markup,
  );
}

export function replace(el: HTMLElement, title: string) {
  el.outerHTML = `
    <section>${title}</section>
  `;
}
