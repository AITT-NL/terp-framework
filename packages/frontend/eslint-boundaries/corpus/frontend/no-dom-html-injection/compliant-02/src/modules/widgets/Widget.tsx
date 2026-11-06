export function show(el: HTMLElement, message: string) {
  // el.innerHTML = message would be refused; assign text, never markup.
  el.innerText = message;
  el.textContent = message;
}

export function preview(box: { innerHTMLPreview: string }, markup: string) {
  box.innerHTMLPreview = markup;
}

export const HINT = "innerHTML / outerHTML / insertAdjacentHTML are refused in app modules";
