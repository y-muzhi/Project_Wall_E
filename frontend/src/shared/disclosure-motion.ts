import { motionTiming } from './motion.ts';

export type DisclosureTarget = Readonly<{ element: HTMLElement; collapsed: boolean }>;
const dimensions = [
  'height',
  'margin-top',
  'margin-bottom',
  'padding-top',
  'padding-bottom',
  'border-top-width',
  'border-bottom-width',
  'opacity',
] as const;
const keyframeName = (property: string) =>
  property.replace(/-([a-z])/g, (_match, letter: string) => letter.toUpperCase());

function readFrame(element: HTMLElement, browser: Window) {
  const style = browser.getComputedStyle(element);
  return {
    visible: style.display !== 'none',
    frame: Object.fromEntries(
      dimensions.map((property) => [keyframeName(property), style.getPropertyValue(property)]),
    ),
  };
}
function collapsedFrame(): Record<string, string> {
  return Object.fromEntries(
    dimensions.map((property) => [keyframeName(property), property === 'opacity' ? '0' : '0px']),
  );
}

/** Measured accordion motion without changing the target's DOM attributes.
 * The owner exposes natural geometry while moving, then applies final visibility.
 * Sampling precedes cancellation so a quick reversal continues from the screen. */
export class DisclosureMotion {
  private browser: Window | undefined;
  private media: MediaQueryList | undefined;
  private readonly animations = new Set<Animation>();
  private readonly pending = new Set<Animation>();
  private frame: number | undefined;
  private generation = 0;
  private closed = false;
  private moving: ((active: boolean) => void) | undefined;
  private moved: (() => void) | undefined;
  private readonly resize = () => this.finish();
  private readonly preference = () => {
    if (this.media?.matches) this.finish();
  };

  run(
    targets: readonly DisclosureTarget[],
    moving: (active: boolean) => void,
    moved: () => void,
    enabled = true,
  ): void {
    const browser = targets[0]?.element.ownerDocument.defaultView;
    if (this.closed || !browser || typeof browser.getComputedStyle !== 'function') {
      this.finish();
      moving(false);
      moved();
      return;
    }
    const before = targets.map((target) => ({ target, ...readFrame(target.element, browser) }));
    this.finish();
    if (this.browser !== browser) {
      this.media?.removeEventListener('change', this.preference);
      this.browser?.removeEventListener('resize', this.resize);
      this.browser = browser;
      this.media = browser.matchMedia('(prefers-reduced-motion: reduce)');
      this.media.addEventListener('change', this.preference);
      browser.addEventListener('resize', this.resize);
    }
    if (!enabled || this.media?.matches) {
      moving(false);
      moved();
      return;
    }
    this.moving = moving;
    this.moved = moved;
    moving(true);
    // Read all natural geometry before starting tracks, avoiding read/write
    // layout cycles for every paragraph of a long section.
    const tracks = before.map(({ target, visible, frame }) => ({
      target,
      from: visible ? frame : collapsedFrame(),
      to: target.collapsed ? collapsedFrame() : readFrame(target.element, browser).frame,
    }));
    const generation = this.generation;
    for (const { target, from, to } of tracks) {
      const element = target.element;
      if (!element.isConnected || typeof element.animate !== 'function') continue;
      if (
        !target.collapsed &&
        dimensions.every((property) => from[keyframeName(property)] === to[keyframeName(property)])
      )
        continue;
      try {
        const animation = element.animate([from, to], {
          duration: motionTiming.disclosure,
          easing: motionTiming.easing,
          fill: 'both',
        });
        this.animations.add(animation);
        this.pending.add(animation);
        const complete = () => {
          if (generation !== this.generation) return;
          this.pending.delete(animation);
          // Completed animations keep their final frame until all tracks settle.
          if (!this.pending.size) this.finish();
        };
        void animation.finished.then(complete, complete);
      } catch {
        // Motion support cannot prevent the owner applying final visibility.
      }
    }
    if (!this.animations.size) this.finish();
    else this.follow();
  }

  private follow(): void {
    this.frame = this.browser!.requestAnimationFrame(() => {
      this.frame = undefined;
      this.moved?.();
      if (this.animations.size) this.follow();
    });
  }
  finish(): void {
    this.generation++;
    if (this.frame !== undefined) this.browser?.cancelAnimationFrame(this.frame);
    this.frame = undefined;
    const moving = this.moving,
      moved = this.moved;
    this.moving = undefined;
    this.moved = undefined;
    moving?.(false);
    for (const animation of this.animations) animation.cancel();
    this.animations.clear();
    this.pending.clear();
    moved?.();
  }
  dispose(): void {
    this.closed = true;
    this.finish();
    this.media?.removeEventListener('change', this.preference);
    this.browser?.removeEventListener('resize', this.resize);
    this.media = undefined;
    this.browser = undefined;
  }
}
