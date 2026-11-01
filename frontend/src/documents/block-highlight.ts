let highlightIdentity = 0;

/** Highlight with scoped CSS outside ProseMirror. Mutating a block's class
 * would be observed as editable input and can redraw an in-progress selection. */
export class DocumentBlockHighlight {
  private readonly root: HTMLElement;
  private readonly scope = `document-highlight-${++highlightIdentity}`;
  private readonly stylesheet: HTMLStyleElement;
  private hovered: number | null = null;
  private located: number | null = null;
  constructor(root: HTMLElement) {
    this.root = root;
    root.classList.add(this.scope);
    this.stylesheet = root.ownerDocument.createElement('style');
    root.ownerDocument.head.append(this.stylesheet);
  }
  private selector(block: number): string {
    return `.${this.scope} .ProseMirror > [data-block-id="${block}"]`;
  }
  private paint(): void {
    const rules: string[] = [];
    if (this.hovered !== null)
      rules.push(`${this.selector(this.hovered)} {
        background-color: var(--accent-soft);
        border-radius: 4px;
        box-shadow: 0 0 0 4px var(--accent-soft);
      }`);
    if (this.located !== null)
      rules.push(`${this.selector(this.located)} {
        outline: 2px solid var(--text);
        outline-offset: 4px;
      }
      @media (forced-colors: active) {
        ${this.selector(this.located)} { outline-color: Highlight; }
      }`);
    this.stylesheet.textContent = rules.join('\n');
  }
  hover(block: number | null): void {
    if (this.hovered === block) return;
    this.hovered = block;
    this.paint();
  }
  locate(block: number | null): void {
    if (this.located === block) return;
    this.located = block;
    this.paint();
  }
  destroy(): void {
    this.stylesheet.remove();
    this.root.classList.remove(this.scope);
  }
}
