// ==UserScript==
// @name         Shin Google Sheets tool
// @version      2026.05.07
// @author       22
// @match        https://docs.google.com/spreadsheets/d/*
// @grant        none
// @downloadURL  https://github.com/nini22P/higurashi-hou-chs/raw/refs/heads/main/tools/userscripts/sheets-tool.user.js
// @updateURL    https://github.com/nini22P/higurashi-hou-chs/raw/refs/heads/main/tools/userscripts/sheets-tool.user.js
// ==/UserScript==

(function () {
    'use strict';

    const RE_CODE_STRICT = /(@(?![b<>])(?:[abcosuvwxz][^@\n\r.]*\.|[-+/<>[\]ekrty{|}]|[a-zA-Z]))/g;

    const RE_RUBY_OK = /@b[^@\n\r.]*\.@<[^@\n\r]*@>/g;
    const RE_RUBY_START = /@b[^@\n\r.]*\./g;
    const RE_RUBY_TEXT = /@<[^@\n\r]*/g;

    const getSelectionOffsets = (container) => {
        const sel = window.getSelection();
        if (!sel || sel.rangeCount === 0) return { start: 0, end: 0 };

        try {
            const range = sel.getRangeAt(0);
            const pre = range.cloneRange();
            pre.selectNodeContents(container);

            pre.setEnd(range.startContainer, range.startOffset);
            const start = pre.toString().length;

            pre.setEnd(range.endContainer, range.endOffset);
            const end = pre.toString().length;

            return { start, end };
        } catch {
            return { start: 0, end: 0 };
        }
    };

    const handleProtection = (e) => {
        if (e.key !== 'Backspace' && e.key !== 'Delete') return;

        const el = e.currentTarget;
        const text = el.textContent;
        const { start: selStart, end: selEnd } = getSelectionOffsets(el);

        const regex = new RegExp(RE_CODE_STRICT);
        let match;

        while ((match = regex.exec(text)) !== null) {
            const s = match.index;
            const ePos = s + match[0].length;

            let hit = false;

            if (selStart !== selEnd) {
                hit = !(selEnd <= s || selStart >= ePos);
            } else {
                if (e.key === 'Backspace') {
                    hit = (selStart > s && selStart <= ePos);
                } else {
                    hit = (selStart >= s && selStart < ePos);
                }
            }

            if (hit) {
                el.style.transition = 'background 0.1s';
                el.style.background = 'rgba(255, 0, 0, 0.15)';
                setTimeout(() => el.style.background = 'transparent', 120);

                e.preventDefault();
                e.stopPropagation();
                return;
            }
        }
    };

    const highlightCode = (el) => {
        if (!CSS.highlights) return;

        const codeRanges = [];
        const rubyRanges = [];
        const rubyErrorRanges = [];

        const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);

        let node;
        while (node = walker.nextNode()) {
            const text = node.textContent;

            let match;
            while ((match = RE_CODE_STRICT.exec(text)) !== null) {
                const range = new Range();
                range.setStart(node, match.index);
                range.setEnd(node, match.index + match[0].length);
                codeRanges.push(range);
            }

            const tokens = [];

            const push = (regex, type) => {
                let m;
                while ((m = regex.exec(text)) !== null) {
                    tokens.push({
                        type,
                        start: m.index,
                        end: m.index + m[0].length
                    });
                }
            };

            push(/@b/g, 'b');
            push(/\.@</g, 'open');
            push(/@>/g, 'close');

            tokens.sort((a, b) => a.start - b.start);

            for (let i = 0; i < tokens.length; i++) {
                const t = tokens[i];

                if (t.type === 'b') {
                    const t1 = tokens[i + 1];
                    const t2 = tokens[i + 2];

                    if (t1?.type === 'open' && t2?.type === 'close') {
                        [t, t1, t2].forEach(tok => {
                            const range = new Range();
                            range.setStart(node, tok.start);
                            range.setEnd(node, tok.end);
                            rubyRanges.push(range);
                        });
                        i += 2;
                    } else {
                        const range = new Range();
                        range.setStart(node, t.start);
                        range.setEnd(node, t.end);
                        rubyErrorRanges.push(range);
                    }
                }

                else if (t.type === 'open') {
                    const prev = tokens[i - 1];
                    const next = tokens[i + 1];

                    if (!(prev?.type === 'b' && next?.type === 'close')) {
                        const range = new Range();
                        range.setStart(node, t.start);
                        range.setEnd(node, t.end);
                        rubyErrorRanges.push(range);
                    }
                }

                else if (t.type === 'close') {
                    const prev = tokens[i - 1];

                    if (prev?.type !== 'open') {
                        const range = new Range();
                        range.setStart(node, t.start);
                        range.setEnd(node, t.end);
                        rubyErrorRanges.push(range);
                    }
                }
            }
        }

        CSS.highlights.delete('shin-code');
        CSS.highlights.delete('shin-ruby');
        CSS.highlights.delete('shin-ruby-error');

        if (codeRanges.length) {
            CSS.highlights.set('shin-code', new Highlight(...codeRanges));
        }

        if (rubyRanges.length) {
            CSS.highlights.set('shin-ruby', new Highlight(...rubyRanges));
        }

        if (rubyErrorRanges.length) {
            CSS.highlights.set('shin-ruby-error', new Highlight(...rubyErrorRanges));
        }
    };

    const makeHighlighter = (el) => {
        let rafId;

        const refresh = () => {
            cancelAnimationFrame(rafId);
            rafId = requestAnimationFrame(() => highlightCode(el));
        };

        return refresh;
    };

    const bind = (el) => {
        if (!el || el.dataset.vnBound) return;

        el.dataset.vnBound = "true";

        el.addEventListener('keydown', handleProtection, true);

        const refresh = makeHighlighter(el);

        el.addEventListener('input', refresh);
        el.addEventListener('keyup', refresh);
        el.addEventListener('mouseup', refresh);
        el.addEventListener('focus', refresh);

        setTimeout(refresh, 500);
    };

    const injectStyle = () => {
        const style = document.createElement('style');
        style.textContent = `
            ::highlight(shin-code) {
                background: rgba(255, 200, 0, 0.3);
                color: #d14;
                border-radius: 2px;
            }

            ::highlight(shin-ruby) {
                background: rgba(0, 180, 255, 0.2);
                color: #0077aa;
            }

            ::highlight(shin-ruby-error) {
                background: rgba(255, 0, 0, 0.3);
                color: #a00;
                text-decoration: underline wavy red;
            }
        `;
        document.head.appendChild(style);
    };

    const observe = () => {
        const observer = new MutationObserver(() => {
            const cellEditor = document.getElementById('waffle-rich-text-editor');
            const formulaBar =
                document.querySelector('.formula-bar-text') ||
                document.getElementById('t-formula-bar-input');

            bind(cellEditor);
            bind(formulaBar);
        });

        observer.observe(document.body, {
            childList: true,
            subtree: true
        });
    };

    const start = () => {
        injectStyle();
        observe();

        bind(document.getElementById('waffle-rich-text-editor'));
        bind(document.querySelector('.formula-bar-text'));
        bind(document.getElementById('t-formula-bar-input'));
    };

    start();

})();