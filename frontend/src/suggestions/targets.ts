import { editorViewCtx } from '@milkdown/kit/core';
import { DecorationSet } from '@milkdown/kit/prose/view';
import type { Node } from '@milkdown/kit/prose/model';
import { revisionDecoration } from './revision-decoration.ts';
import type {
  CurrentDocumentBinding,
  HistoryDocumentBinding,
} from '../requirements/document-owner.ts';
import type { RequirementSuggestionBatch } from './batch-owner.ts';

/** Temporary target indication belongs to the real CURRENT DOM, not the
 * proposed preview. No text, identity or server metadata is changed. */
export class SuggestionTargetLocator {
  private highlighted: HTMLElement | null = null;
  private restoreDecorations: (() => void) | undefined;
  private removeMarkerListener: (() => void) | undefined;
  private closed = false;
  private readonly release: () => void;
  constructor(
    private readonly owner: RequirementSuggestionBatch,
    private readonly binding: () => CurrentDocumentBinding | null,
    private readonly history: () => HistoryDocumentBinding | null = () => null,
    private readonly selectSuggestion?: (identity: number) => void,
    private readonly isDocumentPreview: () => boolean = () => false,
  ) {
    this.release = owner.subscribe(() => {
      const state = owner.getSnapshot();
      if (
        !state.active ||
        (!state.available && !this.isDocumentPreview()) ||
        (this.highlighted && !this.highlighted.isConnected)
      )
        this.clear();
    });
  }
  private clear(): void {
    this.removeMarkerListener?.();
    this.removeMarkerListener = undefined;
    this.restoreDecorations?.();
    this.restoreDecorations = undefined;
    this.highlighted?.classList.remove('suggestion-target-highlight');
    this.highlighted = null;
  }
  locate(identity: number, focus = false): boolean {
    const state = this.owner.getSnapshot(),
      binding = this.binding(),
      item = state.batch?.suggestions.find((item) => item.id === identity),
      current = state.target,
      history = this.history();
    if (
      current === null ||
      this.closed ||
      !state.active ||
      (!state.available && !this.isDocumentPreview()) ||
      state.loading ||
      !item
    )
      return false;
    if (history) {
      const revision = history.viewer.snapshot;
      if (
        revision.id !== state.review?.base_revision_id ||
        revision.document_id !== current.id ||
        revision.requirement_id !== current.requirement_id ||
        revision.source_content_version !== state.batch?.base_content_version
      )
        return false;
    } else {
      const displayed = binding?.editor.loadedDocument;
      if (
        !binding?.editor.valid ||
        !displayed ||
        displayed.document_type !== 'CURRENT' ||
        displayed.id !== current.id ||
        displayed.requirement_id !== current.requirement_id ||
        displayed.content_version !== current.content_version ||
        displayed.content_version !== state.batch?.base_content_version ||
        displayed.markdown_content !== current.markdown_content ||
        JSON.stringify(displayed.block_state_json) !== JSON.stringify(current.block_state_json) ||
        binding.navigation.getSnapshot().content?.kind !== 'CURRENT'
      )
        return false;
    }
    const viewOwner = history?.viewer ?? binding!.editor;
    const navigation = history?.navigation ?? binding!.navigation;
    try {
      this.clear();
      return viewOwner.action((ctx) => {
        const view = ctx.get(editorViewCtx);
        const source = view.state.doc;
        const targets = new Map<number, { node: Node; position: number } | null>();
        source.forEach((node, position) => {
          const id = node.attrs.walle_block_id;
          if (typeof id === 'number') {
            targets.set(id, targets.has(id) ? null : { node, position });
          }
        });
        const target = targets.get(item.target_ref.block_id);
        if (!target) return false;
        const group = state.review?.groups.find((entry) => entry.suggestion_ids.includes(identity));
        const members = group
          ? state.batch!.suggestions.filter((entry) => group.suggestion_ids.includes(entry.id))
          : [item];
        const additions = members.flatMap((entry) => {
          const match = targets.get(entry.target_ref.block_id);
          return match
            ? revisionDecoration(ctx, source, match.node, match.position, entry).find()
            : [];
        });
        const previous = view.props.decorations;
        const overlay: NonNullable<typeof previous> = (state) => {
          const current = previous?.(state);
          if (state.doc !== source) return current ?? DecorationSet.empty;
          const base = current instanceof DecorationSet ? current.find() : [];
          return DecorationSet.create(state.doc, [...base, ...additions]);
        };
        view.setProps({ decorations: overlay });
        this.restoreDecorations = () => {
          if (!view.isDestroyed && view.props.decorations === overlay)
            view.setProps(
              previous ? { decorations: previous } : { decorations: () => DecorationSet.empty },
            );
        };
        const element = view.nodeDOM(target.position);
        if (!(element instanceof HTMLElement) || !navigation.locate(item.target_ref.block_id)) {
          this.clear();
          return false;
        }
        this.highlighted = element;
        this.highlighted.classList.add('suggestion-target-highlight');
        if (focus) {
          if (!element.hasAttribute('tabindex')) {
            element.tabIndex = -1;
            element.addEventListener('blur', () => element.removeAttribute('tabindex'), {
              once: true,
            });
          }
          element.focus({ preventScroll: true });
        }
        if (this.selectSuggestion) {
          const memberIds = new Set(members.map((entry) => entry.id));
          const select = (event: MouseEvent) => {
            if (!(event.target instanceof Element) || window.getSelection()?.toString()) return;
            const mark = event.target.closest<HTMLElement>('[data-revision-suggestion]');
            const suggestionId = Number(mark?.dataset.revisionSuggestion);
            if (memberIds.has(suggestionId)) this.selectSuggestion?.(suggestionId);
          };
          view.dom.addEventListener('click', select);
          this.removeMarkerListener = () => view.dom.removeEventListener('click', select);
        }
        return true;
      });
    } catch {
      this.clear();
      return false;
    }
  }
  dispose(): void {
    if (this.closed) return;
    this.closed = true;
    this.release();
    this.clear();
  }
}
