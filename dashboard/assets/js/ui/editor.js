let loading = null;

export function loadEditor() {
  if (!loading) {
    loading = import('../../vendor/codemirror.js').catch((error) => {
      loading = null;
      throw error;
    });
  }
  return loading;
}

const LANGUAGES = {
  py: 'python', pyi: 'python', js: 'javascript', mjs: 'javascript', cjs: 'javascript', ts: 'typescript',
  json: 'json', css: 'css', html: 'html', htm: 'html', md: 'markdown', markdown: 'markdown',
  yml: 'yaml', yaml: 'yaml', toml: 'toml', sh: 'shell', bash: 'shell', ini: 'properties', cfg: 'properties',
  env: 'properties', txt: null, log: null,
};

export function languageOf(name) {
  const lower = String(name || '').toLowerCase();
  const ext = lower.includes('.') ? lower.split('.').pop() : '';
  return LANGUAGES[ext] ?? null;
}

export const LANGUAGE_LABELS = {
  python: 'Python', javascript: 'JavaScript', typescript: 'TypeScript', json: 'JSON', css: 'CSS', html: 'HTML',
  markdown: 'Markdown', yaml: 'YAML', toml: 'TOML', shell: 'Shell', properties: 'Properties',
};

function shadow(parent) {
  const root = parent.shadowRoot || parent.attachShadow({ mode: 'open' });
  const sheet = new CSSStyleSheet();
  sheet.replaceSync(':host { display: block; height: 100%; min-height: 0; } .cm-editor { height: 100%; }');
  root.adoptedStyleSheets = [sheet];
  return root;
}

function language(cm, name) {
  switch (name) {
    case 'python': return cm.python();
    case 'javascript': return cm.javascript();
    case 'typescript': return cm.javascript({ typescript: true });
    case 'json': return cm.json();
    case 'css': return cm.css();
    case 'html': return cm.html();
    case 'markdown': return cm.markdown();
    case 'yaml': return cm.yaml();
    case 'toml': return cm.StreamLanguage.define(cm.toml);
    case 'shell': return cm.StreamLanguage.define(cm.shell);
    case 'properties': return cm.StreamLanguage.define(cm.properties);
    default: return [];
  }
}

function theme(cm) {
  const t = cm.tags;
  const look = cm.EditorView.theme({
    '&': { color: 'var(--text)', backgroundColor: 'var(--surface)', height: '100%', fontSize: '13px' },
    '.cm-scroller': { fontFamily: 'var(--mono)', lineHeight: '1.6' },
    '.cm-content': { caretColor: 'var(--accent-2)', padding: '10px 0' },
    '.cm-cursor, .cm-dropCursor': { borderLeftColor: 'var(--accent-2)', borderLeftWidth: '2px' },
    '&.cm-focused': { outline: 'none' },
    '&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground, ::selection':
      { backgroundColor: 'var(--accent-soft)' },
    '&.cm-focused .cm-selectionBackground': { backgroundColor: 'var(--syn-select)' },
    '.cm-gutters': { backgroundColor: 'var(--surface)', color: 'var(--text-3)', border: 'none', borderRight: '1px solid var(--line)' },
    '.cm-activeLineGutter': { backgroundColor: 'var(--surface-2)', color: 'var(--text-2)' },
    '.cm-activeLine': { backgroundColor: 'var(--syn-line)' },
    '.cm-lineNumbers .cm-gutterElement': { padding: '0 12px 0 14px', minWidth: '44px' },
    '.cm-foldPlaceholder': { backgroundColor: 'var(--surface-3)', border: 'none', color: 'var(--text-2)' },
    '.cm-matchingBracket, &.cm-focused .cm-matchingBracket': { backgroundColor: 'var(--accent-soft)', outline: '1px solid var(--accent-line)' },
    '.cm-selectionMatch': { backgroundColor: 'var(--syn-match)' },
    '.cm-searchMatch': { backgroundColor: 'var(--warn-soft)', outline: '1px solid var(--warn)' },
    '.cm-searchMatch.cm-searchMatch-selected': { backgroundColor: 'var(--accent-soft)' },
    '.cm-panels': { backgroundColor: 'var(--surface-2)', color: 'var(--text)', borderTop: '1px solid var(--line)' },
    '.cm-panels-bottom': { borderTop: '1px solid var(--line)' },
    '.cm-panel input, .cm-panel button, .cm-textfield': {
      fontFamily: 'var(--font)', fontSize: '12px', color: 'var(--text)', backgroundColor: 'var(--surface)',
      border: '1px solid var(--line-2)', borderRadius: '6px', padding: '3px 8px',
    },
    '.cm-button': { backgroundImage: 'none', backgroundColor: 'var(--surface-3)' },
    '.cm-tooltip': { backgroundColor: 'var(--surface-2)', border: '1px solid var(--line-2)', color: 'var(--text)', borderRadius: '8px' },
    '.cm-tooltip-autocomplete > ul > li[aria-selected]': { backgroundColor: 'var(--accent-soft)', color: 'var(--text)' },
    '.cm-changedLine': { backgroundColor: 'var(--diff-add-line) !important' },
    '.cm-changedText': { backgroundColor: 'var(--diff-add) !important', backgroundImage: 'none !important' },
    '.cm-deletedChunk': { backgroundColor: 'var(--diff-del-line) !important' },
    '.cm-deletedChunk del, .cm-deletedText': { backgroundColor: 'var(--diff-del) !important', textDecoration: 'none' },
    '.cm-merge-a .cm-changedLine, .cm-merge-a .cm-changedText': { backgroundColor: 'var(--diff-del-line) !important' },
    '.cm-merge-a .cm-changedText': { backgroundColor: 'var(--diff-del) !important' },
    '.cm-changeGutter': { width: '3px', paddingLeft: '0' },
    '.cm-insertedLine': { backgroundColor: 'var(--diff-add-line)' },
  });
  const colors = cm.HighlightStyle.define([
    { tag: [t.keyword, t.controlKeyword, t.moduleKeyword, t.operatorKeyword, t.definitionKeyword], color: 'var(--syn-keyword)' },
    { tag: [t.string, t.special(t.string), t.regexp], color: 'var(--syn-string)' },
    { tag: [t.number, t.bool, t.null, t.atom], color: 'var(--syn-number)' },
    { tag: [t.comment, t.lineComment, t.blockComment, t.docComment], color: 'var(--syn-comment)', fontStyle: 'italic' },
    { tag: [t.function(t.variableName), t.function(t.propertyName), t.macroName], color: 'var(--syn-func)' },
    { tag: [t.definition(t.variableName), t.definition(t.function(t.variableName))], color: 'var(--syn-def)' },
    { tag: [t.typeName, t.className, t.namespace, t.self], color: 'var(--syn-type)' },
    { tag: [t.propertyName, t.attributeName], color: 'var(--syn-prop)' },
    { tag: [t.operator, t.punctuation, t.separator, t.bracket], color: 'var(--syn-op)' },
    { tag: [t.meta, t.annotation, t.processingInstruction], color: 'var(--syn-meta)' },
    { tag: [t.heading], color: 'var(--syn-keyword)', fontWeight: '650' },
    { tag: [t.link, t.url], color: 'var(--syn-string)', textDecoration: 'underline' },
    { tag: [t.emphasis], fontStyle: 'italic' },
    { tag: [t.strong], fontWeight: '650' },
    { tag: [t.invalid], color: 'var(--bad)' },
  ]);
  return [look, cm.syntaxHighlighting(colors)];
}

function base(cm, options) {
  const extensions = [
    cm.lineNumbers(), cm.highlightActiveLineGutter(), cm.highlightSpecialChars(), cm.history(), cm.foldGutter(),
    cm.drawSelection(), cm.dropCursor(), cm.indentOnInput(), cm.bracketMatching(), cm.closeBrackets(),
    cm.autocompletion({ activateOnTyping: false }), cm.rectangularSelection(), cm.highlightActiveLine(),
    cm.highlightSelectionMatches(), cm.indentUnit.of('    '), cm.EditorState.tabSize.of(4),
    cm.keymap.of([
      ...cm.closeBracketsKeymap, ...cm.defaultKeymap, ...cm.searchKeymap, ...cm.historyKeymap, ...cm.foldKeymap,
      ...cm.completionKeymap, cm.indentWithTab,
    ]),
    theme(cm),
    cm.EditorView.contentAttributes.of({ 'aria-label': options.label || 'Editor', spellcheck: 'false' }),
  ];
  if (options.readOnly) {
    extensions.push(cm.EditorState.readOnly.of(true), cm.EditorView.editable.of(false));
  }
  return extensions;
}

export async function createEditor(parent, options = {}) {
  const cm = await loadEditor();
  const lang = new cm.Compartment();
  const wrap = new cm.Compartment();
  const extensions = [
    base(cm, options),
    lang.of(language(cm, options.language)),
    wrap.of(options.wrap ? cm.EditorView.lineWrapping : []),
    cm.EditorView.updateListener.of((update) => {
      if (update.docChanged) {
        options.onChange?.(update);
      }
      if (update.selectionSet || update.docChanged) {
        const head = update.state.selection.main.head;
        const line = update.state.doc.lineAt(head);
        options.onCursor?.(line.number, head - line.from + 1);
      }
    }),
  ];
  if (options.onSave) {
    extensions.unshift(cm.keymap.of([{ key: 'Mod-s', preventDefault: true, run: () => { options.onSave(); return true; } }]));
  }
  const root = shadow(parent);
  const view = new cm.EditorView({ parent: root, root, state: cm.EditorState.create({ doc: options.doc || '', extensions }) });
  return {
    view,
    get text() {
      return view.state.doc.toString();
    },
    setText(text) {
      view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: text } });
    },
    setLanguage(name) {
      view.dispatch({ effects: lang.reconfigure(language(cm, name)) });
    },
    setWrap(on) {
      view.dispatch({ effects: wrap.reconfigure(on ? cm.EditorView.lineWrapping : []) });
    },
    search() {
      cm.openSearchPanel(view);
    },
    focus() {
      view.focus();
    },
    destroy() {
      view.destroy();
    },
  };
}

export async function createDiff(parent, original, changed, options = {}) {
  const cm = await loadEditor();
  const root = shadow(parent);
  const view = new cm.EditorView({
    parent: root,
    root,
    state: cm.EditorState.create({
      doc: changed,
      extensions: [
        base(cm, { readOnly: true, label: options.label || 'Changes' }),
        language(cm, options.language),
        cm.EditorView.lineWrapping,
        cm.unifiedMergeView({ original, mergeControls: false, highlightChanges: true, gutter: true,
          collapseUnchanged: { margin: 3, minSize: 8 } }),
      ],
    }),
  });
  return { view, destroy: () => view.destroy() };
}

export function lineDiff(before, after) {
  const a = before.split('\n');
  const b = after.split('\n');
  const seen = new Map();
  for (const line of a) {
    seen.set(line, (seen.get(line) || 0) + 1);
  }
  let added = 0;
  for (const line of b) {
    const count = seen.get(line) || 0;
    if (count > 0) {
      seen.set(line, count - 1);
    } else {
      added++;
    }
  }
  const removed = [...seen.values()].reduce((sum, n) => sum + n, 0);
  return { added, removed };
}
