// Rich place + date input behaviors. Document-level delegation so any
// [data-place-input] or [data-date-input] on the page gets autocomplete,
// suggestions, pill clicks, and (for date) a parsed preview.
//
// Used by the single-image form in core/_image_metadata.html and by the
// batch modals in core/_batch_bar.html.
(function () {
    const state = new WeakMap();
    let debounceTimer = null;
    let activeController = null;

    function getState(input) {
        let s = state.get(input);
        if (!s) {
            s = { items: [], activeIndex: -1, lastQuery: null };
            state.set(input, s);
        }
        return s;
    }

    function suggestionsFor(input) {
        return input.parentElement.querySelector("[data-place-suggestions]");
    }

    function renderSuggestions(input, items) {
        const ul = suggestionsFor(input);
        const s = getState(input);
        s.items = items;
        s.activeIndex = items.length ? 0 : -1;
        ul.innerHTML = "";
        if (!items.length) {
            ul.hidden = true;
            return;
        }
        items.forEach((item, idx) => {
            const li = document.createElement("li");
            li.textContent = item.name + (item.has_coords ? "" : " ⚠");
            li.dataset.placeName = item.name;
            if (!item.has_coords) li.classList.add("no-coords");
            if (idx === s.activeIndex) li.classList.add("active");
            li.addEventListener("mousedown", (ev) => {
                ev.preventDefault();
                applyValue(input, item.name);
            });
            ul.appendChild(li);
        });
        ul.hidden = false;
    }

    function highlightActive(input) {
        const ul = suggestionsFor(input);
        const s = getState(input);
        Array.from(ul.children).forEach((li, idx) => {
            li.classList.toggle("active", idx === s.activeIndex);
        });
    }

    function hideSuggestions(input) {
        const ul = suggestionsFor(input);
        ul.hidden = true;
        const s = getState(input);
        s.activeIndex = -1;
    }

    function applyValue(input, value) {
        input.value = value;
        hideSuggestions(input);
        input.dispatchEvent(new Event("change", { bubbles: true }));
    }

    async function fetchSuggestions(input) {
        const q = input.value.trim();
        const s = getState(input);
        if (q === s.lastQuery) return;
        s.lastQuery = q;
        if (activeController) activeController.abort();
        activeController = new AbortController();
        try {
            const url = input.dataset.autocompleteUrl + "?q=" + encodeURIComponent(q);
            const res = await fetch(url, { signal: activeController.signal });
            if (!res.ok) return;
            const data = await res.json();
            if (document.activeElement !== input) return;
            renderSuggestions(input, data.results || []);
        } catch (err) {
            if (err.name !== "AbortError") throw err;
        }
    }

    document.addEventListener("input", (ev) => {
        const input = ev.target.closest("[data-place-input]");
        if (!input) return;
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => fetchSuggestions(input), 120);
    });

    document.addEventListener("focusin", (ev) => {
        const input = ev.target.closest("[data-place-input]");
        if (!input) return;
        fetchSuggestions(input);
    });

    document.addEventListener("focusout", (ev) => {
        const input = ev.target.closest("[data-place-input]");
        if (!input) return;
        setTimeout(() => hideSuggestions(input), 120);
    });

    document.addEventListener("keydown", (ev) => {
        const input = ev.target.closest("[data-place-input]");
        if (!input) return;
        const s = getState(input);
        if (!s.items.length) return;
        if (ev.key === "ArrowDown") {
            ev.preventDefault();
            s.activeIndex = Math.min(s.activeIndex + 1, s.items.length - 1);
            highlightActive(input);
        } else if (ev.key === "ArrowUp") {
            ev.preventDefault();
            s.activeIndex = Math.max(s.activeIndex - 1, 0);
            highlightActive(input);
        } else if (ev.key === "Enter") {
            if (s.activeIndex >= 0) {
                ev.preventDefault();
                applyValue(input, s.items[s.activeIndex].name);
            }
        } else if (ev.key === "Escape") {
            const ul = suggestionsFor(input);
            if (ul && !ul.hidden) {
                ev.stopImmediatePropagation();
                hideSuggestions(input);
            }
        }
    });

    document.addEventListener("click", (ev) => {
        const pill = ev.target.closest(".place-pill");
        if (!pill) return;
        const field = pill.closest("[data-place-field]");
        if (!field) return;
        const input = field.querySelector("[data-place-input]");
        if (!input) return;
        applyValue(input, pill.dataset.placeName);
    });
})();

(function () {
    const state = new WeakMap();
    let debounceTimer = null;
    let activeController = null;

    function getState(input) {
        let s = state.get(input);
        if (!s) {
            s = { items: [], activeIndex: -1, lastQuery: null, lastParse: null };
            state.set(input, s);
        }
        return s;
    }

    function fieldOf(input) { return input.closest("[data-date-field]"); }
    function suggestionsFor(input) { return fieldOf(input).querySelector("[data-date-suggestions]"); }
    function previewFor(input) { return fieldOf(input).querySelector("[data-date-preview]"); }

    function renderSuggestions(input, items) {
        const ul = suggestionsFor(input);
        const s = getState(input);
        s.items = items;
        s.activeIndex = items.length ? 0 : -1;
        ul.innerHTML = "";
        if (!items.length) { ul.hidden = true; return; }
        items.forEach((word, idx) => {
            const li = document.createElement("li");
            li.textContent = word;
            li.dataset.word = word;
            if (idx === s.activeIndex) li.classList.add("active");
            li.addEventListener("mousedown", (ev) => {
                ev.preventDefault();
                applyWord(input, word);
            });
            ul.appendChild(li);
        });
        ul.hidden = false;
    }

    function highlightActive(input) {
        const ul = suggestionsFor(input);
        const s = getState(input);
        Array.from(ul.children).forEach((li, idx) => {
            li.classList.toggle("active", idx === s.activeIndex);
        });
    }

    function hideSuggestions(input) {
        const ul = suggestionsFor(input);
        ul.hidden = true;
        getState(input).activeIndex = -1;
    }

    function renderPreview(input, parsed, error) {
        const p = previewFor(input);
        if (error) {
            p.textContent = error;
            p.classList.add("error");
            return;
        }
        p.classList.remove("error");
        if (!parsed) { p.textContent = ""; return; }
        p.textContent = `→ ${parsed.summary} (${parsed.precision_label})`;
    }

    function applyWord(input, word) {
        const pos = input.selectionStart ?? input.value.length;
        const before = input.value.slice(0, pos);
        const after = input.value.slice(pos);
        const match = before.match(/([\wäöüÄÖÜ]+)$/);
        let newBefore;
        if (match) {
            newBefore = before.slice(0, before.length - match[1].length) + word;
        } else {
            const needsSpace = before.length > 0 && !/\s$/.test(before);
            newBefore = before + (needsSpace ? " " : "") + word;
        }
        input.value = newBefore + after;
        const caret = newBefore.length;
        input.setSelectionRange(caret, caret);
        hideSuggestions(input);
        input.focus();
        fetchState(input);
    }

    function currentWordPrefix(input) {
        const value = input.value.slice(0, input.selectionStart ?? input.value.length);
        const match = value.match(/([\wäöüÄÖÜ]+)$/);
        return match ? match[1] : "";
    }

    async function fetchState(input) {
        const q = input.value;
        const s = getState(input);
        if (q === s.lastQuery) return;
        s.lastQuery = q;
        if (activeController) activeController.abort();
        if (!q.trim()) {
            renderPreview(input, null, null);
            renderSuggestions(input, []);
            return;
        }
        activeController = new AbortController();
        try {
            const url = input.dataset.autocompleteUrl + "?q=" + encodeURIComponent(q);
            const res = await fetch(url, { signal: activeController.signal });
            if (!res.ok) return;
            const data = await res.json();
            s.lastParse = data;
            renderPreview(input, data.parsed, data.error);
            const prefix = currentWordPrefix(input);
            const pool = (data.suggestions || []).filter(w => !prefix || w.toLowerCase().startsWith(prefix.toLowerCase()));
            renderSuggestions(input, pool);
        } catch (err) {
            if (err.name !== "AbortError") throw err;
        }
    }

    document.addEventListener("input", (ev) => {
        const input = ev.target.closest("[data-date-input]");
        if (!input) return;
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => fetchState(input), 120);
    });

    document.addEventListener("focusin", (ev) => {
        const input = ev.target.closest("[data-date-input]");
        if (!input) return;
        fetchState(input);
    });

    document.addEventListener("focusout", (ev) => {
        const input = ev.target.closest("[data-date-input]");
        if (!input) return;
        setTimeout(() => hideSuggestions(input), 120);
    });

    document.addEventListener("keydown", (ev) => {
        const input = ev.target.closest("[data-date-input]");
        if (!input) return;
        const s = getState(input);
        if (ev.key === "ArrowDown" && s.items.length) {
            ev.preventDefault();
            s.activeIndex = Math.min(s.activeIndex + 1, s.items.length - 1);
            highlightActive(input);
        } else if (ev.key === "ArrowUp" && s.items.length) {
            ev.preventDefault();
            s.activeIndex = Math.max(s.activeIndex - 1, 0);
            highlightActive(input);
        } else if (ev.key === "Enter" && s.activeIndex >= 0 && s.items.length) {
            ev.preventDefault();
            applyWord(input, s.items[s.activeIndex]);
        } else if (ev.key === "Escape") {
            const ul = suggestionsFor(input);
            if (ul && !ul.hidden) {
                ev.stopImmediatePropagation();
                hideSuggestions(input);
            }
        }
    });

    document.addEventListener("click", (ev) => {
        const pill = ev.target.closest(".date-pill");
        if (!pill) return;
        const field = pill.closest("[data-date-field]");
        if (!field) return;
        const input = field.querySelector("[data-date-input]");
        if (!input) return;
        input.value = pill.dataset.dateValue;
        hideSuggestions(input);
        fetchState(input);
        input.dispatchEvent(new Event("change", { bubbles: true }));
    });
})();
