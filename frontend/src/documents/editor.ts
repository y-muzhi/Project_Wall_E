import { editorReadModel } from './contracts.ts';
import { Crepe } from '@milkdown/crepe';
import { editorViewCtx } from '@milkdown/kit/core';
import type { Ctx } from '@milkdown/kit/ctx';
import type { EditorState, Transaction } from '@milkdown/kit/prose/state';
import { validateDocumentReadModel } from './contracts.ts';
import type { DocumentReadModel } from './contracts.ts';
import { installSourceNodes } from './source-nodes.ts';
import { hasRawSource, installIdentityAttributes, installIdentityState } from './identity.ts';
import { EditedSnapshotLedger } from './edited-snapshot.ts';
import type { EditedSnapshot } from './edited-snapshot.ts';
import { selectionFromEditorState, locateEditorSelection } from './editor-selection.ts';
import type { SelectionEvent } from './selection.ts';
import { snapshotObject } from '../api/client.ts';
import type { LocalDraftSnapshot } from './recovery-store.ts';
import { TemplateHeadingLock, templateLockMessage } from './template-lock.ts';
import type { DocumentStructureBinding } from './template-lock.ts';
import { installFormatToolbar } from './format-toolbar.ts';
import { chineseStrongDecorations } from './chinese-strong-display.ts';
import { loadDrawingCanvas } from './drawing-assets.ts';
import type { DrawingCanvas } from './drawing-canvas.tsx';

export type EditorEvents = Readonly<{
  change?: (snapshot: EditedSnapshot) => void;
  selection?: (selection: SelectionEvent | null) => void;
  error?: (message: string | null) => void;
  blur?: () => void;
  validity?: (valid: boolean) => void;
}>;

/** Actual DocumentReadModel host. HTTP, autosave and occupancy belong to the
 * parent. A new object is loaded by replacing this host, never by overwriting
 * the active local editor with a late saved response.
 */
export class RequirementEditor {
  private readonly crepe: Crepe;
  private readonly document: DocumentReadModel;
  private readonly events: EditorEvents;
  private readonly session: EditedSnapshotLedger | null;
  private readonly templateLock: TemplateHeadingLock | null;
  private accepted: EditorState;
  private readonly root: HTMLElement;
  private readonly removeListeners: (() => void)[] = [];
  private readonly transactionGuards = new Set<
    (state: EditorState, transaction: Transaction) => boolean
  >();
  private formatToolbar: ReturnType<typeof installFormatToolbar> | null = null;
  private readonlyMode: boolean;
  private drawing: DrawingCanvas | null = null;
  private closed = false;
  private composing = false;
  private invalid = false;
  private editingTime: number;
  private constructor(
    crepe: Crepe,
    root: HTMLElement,
    document: DocumentReadModel,
    readonly: boolean,
    events: EditorEvents,
    templateLock: TemplateHeadingLock | null,
    drawing: boolean,
  ) {
    this.crepe = crepe;
    this.root = root;
    this.document = document;
    this.events = events;
    this.readonlyMode = readonly;
    this.templateLock = templateLock;
    this.accepted = crepe.editor.action((ctx) => ctx.get(editorViewCtx).state);
    templateLock?.assertDocument(this.accepted.doc);
    this.session =
      document.document_type === 'MANUAL_DRAFT'
        ? crepe.editor.action((ctx) => new EditedSnapshotLedger(ctx, document, this.accepted))
        : null;
    this.editingTime = Math.max(Date.now(), Date.parse(document.updated_at) + 1);
    crepe.setReadonly(readonly);
    crepe.editor.action((ctx) => {
      const view = ctx.get(editorViewCtx);
      view.setProps({
        dispatchTransaction: (transaction) => this.dispatch(ctx, transaction),
        attributes: () => ({
          'aria-label':
            document.document_type === 'CURRENT' ? '当前需求正文，只读' : '人工编辑草稿',
          role: 'textbox',
          'aria-multiline': 'true',
          'aria-readonly': String(this.readonlyMode),
        }),
      });
    });
    const listen = (name: string, listener: EventListener) => {
      root.addEventListener(name, listener);
      this.removeListeners.push(() => root.removeEventListener(name, listener));
    };
    listen('compositionstart', () => {
      this.composing = true;
      this.notifyValidity();
    });
    listen('compositionend', () => {
      this.composing = false;
      queueMicrotask(() => {
        if (!this.closed) this.flushLocal();
      });
    });
    const focusout = (event: FocusEvent) => {
      const from = event.target as Node | null,
        target = event.relatedTarget as Node | null;
      // Body-mounted format controls are still part of this editor. Flush only
      // when focus leaves both the owned document and its formatting surfaces.
      if (
        (root.contains(from) || this.formatToolbar?.contains(from)) &&
        !root.contains(target) &&
        !this.formatToolbar?.contains(target)
      ) {
        this.flushLocal();
        this.notify(() => this.events.blur?.());
      }
    };
    root.ownerDocument.addEventListener('focusout', focusout);
    this.removeListeners.push(() => root.ownerDocument.removeEventListener('focusout', focusout));
    if (this.session && !drawing)
      this.formatToolbar = installFormatToolbar(root, this, (message) =>
        this.notify(() => this.events.error?.(message)),
      );
  }
  static async create(
    root: HTMLElement,
    input: DocumentReadModel,
    readonly = true,
    events: EditorEvents = {},
    structure: DocumentStructureBinding | null = null,
    drawing = false,
  ): Promise<RequirementEditor> {
    input = editorReadModel(snapshotObject(input) as unknown as DocumentReadModel);
    if (!readonly && input.document_type !== 'MANUAL_DRAFT')
      throw new TypeError('Only actual manual draft may be edited');
    const editorRoot = drawing ? root.ownerDocument.createElement('div') : root;
    if (drawing) {
      editorRoot.hidden = true;
      editorRoot.inert = true;
      root.append(editorRoot);
    }
    const crepe = new Crepe({
      root: editorRoot,
      defaultValue: input.markdown_content,
      features: {
        [Crepe.Feature.CodeMirror]: false,
        [Crepe.Feature.ListItem]: false,
        [Crepe.Feature.LinkTooltip]: false,
        [Crepe.Feature.Cursor]: false,
        [Crepe.Feature.ImageBlock]: false,
        [Crepe.Feature.BlockEdit]: false,
        [Crepe.Feature.Toolbar]: false,
        [Crepe.Feature.Placeholder]: false,
        [Crepe.Feature.Table]: false,
        [Crepe.Feature.Latex]: false,
        [Crepe.Feature.TopBar]: false,
        [Crepe.Feature.AI]: false,
      },
    });
    let editor: RequirementEditor | undefined;
    try {
      await installSourceNodes(crepe);
      installIdentityAttributes(crepe);
      installIdentityState(
        crepe,
        input.block_state_json.blocks.map((block) => block.block_id),
        input.block_state_json.next_block_id,
      );
      await crepe.create();
      const { document, source } = crepe.editor.action((ctx) =>
        validateDocumentReadModel(ctx, input),
      );
      if (document.document_type === 'CURRENT' && document.markdown_content.includes('**')) {
        crepe.editor.action((ctx) => {
          const view = ctx.get(editorViewCtx);
          const presentation = chineseStrongDecorations(view.state.doc, source.blocks);
          view.setProps({ decorations: () => presentation });
        });
      }
      const lock =
        structure === null
          ? null
          : crepe.editor.action((ctx) => new TemplateHeadingLock(ctx, structure));
      const owned = new RequirementEditor(crepe, root, document, readonly, events, lock, drawing);
      editor = owned;
      if (drawing) {
        const { mountDrawingCanvas } = await loadDrawingCanvas();
        owned.drawing = mountDrawingCanvas(root, document.markdown_content, {
          change: (scene) => owned.changeDrawing(scene),
          validity: () => owned.notifyValidity(),
          error: (message) => owned.notify(() => events.error?.(message)),
        });
        owned.drawing.setReadonly(readonly);
      }
      return owned;
    } catch (error) {
      if (editor) await editor.destroy();
      else await crepe.destroy();
      root.replaceChildren();
      throw error;
    }
  }
  /** Parent receives this actual ledger only for MANUAL_DRAFT. */
  get ledger(): EditedSnapshotLedger | null {
    return this.session;
  }
  get loadedDocument(): DocumentReadModel {
    return this.document;
  }
  get isDrawing(): boolean {
    return this.drawing !== null;
  }
  get valid(): boolean {
    return !this.closed && !this.invalid && !this.composing && (this.drawing?.valid ?? true);
  }
  get readonly(): boolean {
    return this.readonlyMode;
  }
  get formattingReady(): boolean {
    return !this.closed && !this.readonlyMode && !this.composing;
  }
  action<T>(callback: (ctx: Ctx) => T): T {
    if (this.closed) throw new Error('Editor is closed');
    return this.crepe.editor.action(callback);
  }
  guardTransactions(guard: (state: EditorState, transaction: Transaction) => boolean): () => void {
    this.transactionGuards.add(guard);
    return () => this.transactionGuards.delete(guard);
  }
  setReadonly(readonly: boolean): void {
    if (this.closed) return;
    if (!readonly && !this.session) throw new TypeError('Current document is read only');
    this.readonlyMode = readonly;
    this.crepe.setReadonly(readonly);
    this.drawing?.setReadonly(readonly);
    this.formatToolbar?.update();
  }
  private notify(operation: () => void): void {
    try {
      operation();
    } catch (error) {
      console.error('WALL-E editor observer failed', error);
    }
  }
  private notifyValidity(): void {
    this.formatToolbar?.update();
    this.notify(() => this.events.validity?.(this.valid));
  }
  private select(ctx: Ctx): void {
    if (this.closed || this.drawing) return;
    let selection: SelectionEvent | null = null;
    try {
      selection = selectionFromEditorState(ctx.get(editorViewCtx).state, {
        document_id: this.document.id,
        content_version: this.session?.savedVersion ?? this.document.content_version,
      });
    } catch {
      /* cross-block, synthetic/atom interiors have no legal selection */
    }
    this.notify(() => this.events.selection?.(selection));
  }
  private capture(ctx: Ctx, state: EditorState): boolean {
    if (!this.session || this.composing || this.closed) return false;
    if (state.doc.eq(this.accepted.doc)) {
      this.invalid = false;
      this.notify(() => this.events.error?.(null));
      this.notifyValidity();
      return true;
    }
    try {
      const raw: number[] = [];
      state.doc.forEach((node, _position, index) => {
        if (!hasRawSource(node)) return;
        let prior: typeof node | undefined;
        this.accepted.doc.forEach((candidate) => {
          if (candidate.attrs.walle_block_id === node.attrs.walle_block_id) prior = candidate;
        });
        if (prior && !node.eq(prior)) raw.push(index);
      });
      const at = new Date(
        (this.editingTime = Math.max(
          this.editingTime + 1,
          Date.now(),
          Date.parse(this.session.savedAt) + 1,
        )),
      ).toISOString();
      const prepared =
        raw.length === 1
          ? this.session.prepareRawDocument(state, raw[0]!, at)
          : this.session.prepare(state, at);
      this.templateLock?.assertDocument(prepared.state.doc);
      const view = ctx.get(editorViewCtx);
      view.updateState(prepared.state);
      const pair = this.session.accept(prepared, view.state);
      this.accepted = view.state;
      this.invalid = false;
      this.notify(() => this.events.error?.(null));
      this.notify(() => this.events.change?.(pair));
      this.notifyValidity();
      return true;
    } catch {
      this.invalid = true;
      this.notify(() =>
        this.events.error?.('当前输入暂时无法形成有效草稿，请保留内容并修正后保存'),
      );
      this.notifyValidity();
      return false;
    }
  }
  private dispatch(ctx: Ctx, transaction: Transaction): void {
    if (this.closed || (transaction.docChanged && this.readonlyMode)) return;
    const view = ctx.get(editorViewCtx);
    try {
      for (const guard of this.transactionGuards)
        if (!guard(view.state, transaction)) {
          view.updateState(view.state);
          return;
        }
      const state = view.state.applyTransaction(transaction).state;
      if (!state.doc.eq(view.state.doc) && this.templateLock) {
        try {
          this.templateLock.assertDocument(state.doc);
        } catch {
          // Reconcile a native DOM/IME edit with the retained valid state.
          // A rejected edit must not poison or autosave the previous draft.
          view.updateState(view.state);
          this.notify(() => this.events.error?.(templateLockMessage));
          this.notifyValidity();
          return;
        }
      }
      view.updateState(state);
      if (transaction.docChanged && !this.composing) this.capture(ctx, state);
      this.select(ctx);
      this.formatToolbar?.update();
    } catch {
      this.invalid = true;
      this.notify(() => this.events.error?.('这次编辑无法完成，请保留当前内容并重试'));
      this.notifyValidity();
    }
  }
  private changeDrawing(scene: string): void {
    if (this.closed || this.readonlyMode || !this.session) return;
    this.action((ctx) => {
      const view = ctx.get(editorViewCtx);
      const block = view.state.doc.firstChild;
      if (view.state.doc.childCount !== 1 || block?.type.name !== 'code_block')
        throw Error('画板草稿结构无效');
      if (block.textContent !== scene)
        view.dispatch(
          view.state.tr.insertText(scene, 1, block.nodeSize - 1).setMeta('addToHistory', false),
        );
      if (this.invalid) throw Error('画板草稿暂时无法保存');
    });
  }
  /** Parent checks this before completing; partial composition/invalid local
   * input cannot be mistaken for the older snapshot already saved on server.
   */
  flushLocal(): boolean {
    if (this.closed || this.composing) return false;
    if (!this.session) return true;
    if (this.drawing && !this.drawing.flush()) return false;
    return this.action((ctx) => this.capture(ctx, ctx.get(editorViewCtx).state));
  }
  /** Parent owns explicit cache choice and fresh occupancy/version checks.
   * The display/ledger update is synchronous; parent then adopts the local
   * revision in Autosave before allowing input. No saved receipt is fabricated. */
  restoreLocal(local: LocalDraftSnapshot): EditedSnapshot {
    if (this.closed || !this.session || !this.readonlyMode || this.composing)
      throw new TypeError('Fresh frozen actual draft required');
    return this.action((ctx) => {
      const view = ctx.get(editorViewCtx),
        prepared = this.session!.prepareLocalRecovery(view.state, local);
      this.templateLock?.assertDocument(prepared.state.doc);
      view.updateState(prepared.state);
      const pair = this.session!.accept(prepared, view.state);
      this.accepted = view.state;
      this.invalid = false;
      this.drawing?.replace(pair.markdown_content);
      this.editingTime = Math.max(
        this.editingTime,
        Date.parse(local.updated_at),
        ...pair.block_state_json.blocks.map((block) => Date.parse(block.last_modified_at)),
      );
      this.notifyValidity();
      return pair;
    });
  }
  locate(selection: SelectionEvent): void {
    this.action((ctx) =>
      locateEditorSelection(
        ctx.get(editorViewCtx),
        {
          document_id: this.document.id,
          content_version: this.session?.savedVersion ?? this.document.content_version,
        },
        selection,
      ),
    );
  }
  async destroy(): Promise<void> {
    if (this.closed) return;
    this.closed = true;
    this.transactionGuards.clear();
    for (const remove of this.removeListeners) remove();
    this.formatToolbar?.destroy();
    this.drawing?.destroy();
    this.session?.dispose();
    await this.crepe.destroy();
    this.root.replaceChildren();
  }
}
