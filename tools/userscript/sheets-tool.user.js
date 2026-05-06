// ==UserScript==
// @name         Higurashi Google Sheets tool
// @version      2026.05.07
// @author       22
// @match        https://docs.google.com/spreadsheets/d/*
// @grant        none
// @downloadURL  https://github.com/nini22P/higurashi-hou-chs/raw/refs/heads/main/tools/userscripts/sheets-tool.user.js
// @updateURL    https://github.com/nini22P/higurashi-hou-chs/raw/refs/heads/main/tools/userscripts/sheets-tool.user.js
// ==/UserScript==

(function() {
    'use strict';

    function startProtection() {
        const RE_CODE_STRICT = /(@(?![b<>])(?:[abcosuvwxz][^@\n\r.]*\.|[-+/<>[\]ekrty{|}]|[a-zA-Z]))/g;


        const getSelectionOffsets = (container) => {
            const sel = window.getSelection();
            if (!sel || sel.rangeCount === 0) return { start: 0, end: 0 };
            try {
                const range = sel.getRangeAt(0);
                const preCaretRange = range.cloneRange();
                preCaretRange.selectNodeContents(container);
                preCaretRange.setEnd(range.endContainer, range.endOffset);
                const start = preCaretRange.toString().length;
                return { start, end: start + range.toString().length };
            } catch (e) {
                return { start: 0, end: 0 };
            }
        };

        const handleProtection = (e) => {
            if (e.key !== 'Backspace' && e.key !== 'Delete') return;

            const el = e.currentTarget;
            const fullText = el.textContent;
            const { start: selStart, end: selEnd } = getSelectionOffsets(el);

            const regex = new RegExp(RE_CODE_STRICT);
            let match;

            while ((match = regex.exec(fullText)) !== null) {
                const instStart = match.index;
                const instEnd = match.index + match[0].length;

                let isColliding = false;

                if (selStart !== selEnd) {
                    isColliding = !(selEnd <= instStart || selStart >= instEnd);
                } else {
                    if (e.key === 'Backspace') {
                        isColliding = (selStart > instStart && selStart <= instEnd);
                    } else if (e.key === 'Delete') {
                        isColliding = (selStart >= instStart && selStart < instEnd);
                    }
                }

                if (isColliding) {
                    el.style.transition = 'background 0.1s';
                    el.style.background = 'rgba(255, 0, 0, 0.15)';
                    setTimeout(() => el.style.background = 'transparent', 150);

                    console.warn(`Blocked: ${match[0]}`);
                    e.preventDefault();
                    e.stopPropagation();
                    return;
                }
            }
        };

        const bindToElement = (el) => {
            if (el && !el.dataset.vnProtected) {
                el.dataset.vnProtected = "true";
                el.addEventListener('keydown', handleProtection, true);
            }
        };

        const observer = new MutationObserver((mutations) => {
            for (const mutation of mutations) {
                if (mutation.addedNodes.length) {
                    const cellEditor = document.getElementById('waffle-rich-text-editor');
                    if (cellEditor) bindToElement(cellEditor);

                    const formulaBar = document.querySelector('.formula-bar-text') ||
                                       document.getElementById('t-formula-bar-input');
                    if (formulaBar) bindToElement(formulaBar);
                }
            }
        });

        observer.observe(document.body, { childList: true, subtree: true });

        const initialTargets = [
            document.querySelector('.formula-bar-text'),
            document.getElementById('t-formula-bar-input')
        ];
        initialTargets.forEach(bindToElement);

    }

    startProtection();

})();