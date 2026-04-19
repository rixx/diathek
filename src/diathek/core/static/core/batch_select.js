(function () {
    const root = document.querySelector("[data-batch-root]");
    if (!root) return;
    const batchUrl = root.dataset.batchUrl || "";
    if (!batchUrl) return;
    const batchBar = root.querySelector("[data-batch-bar]");
    const batchCount = root.querySelector("[data-batch-count]");
    const batchError = root.querySelector("[data-batch-error]");
    const todoModal = root.querySelector("[data-batch-todo-modal]");
    const placeModal = root.querySelector("[data-batch-place-modal]");
    const dateModal = root.querySelector("[data-batch-date-modal]");
    const csrfInput = document.querySelector("[name=csrfmiddlewaretoken]");
    const csrfToken = csrfInput ? csrfInput.value : "";

    const tiles = Array.from(root.querySelectorAll(".image-tile[data-image-id]"));
    const selected = new Set();
    let selectMode = false;
    let lastAnchorIndex = -1;

    function isTypingTarget(el) {
        if (!el) return false;
        const tag = el.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
        if (el.isContentEditable) return true;
        return false;
    }

    function setError(msg) {
        if (batchError) batchError.textContent = msg || "";
    }

    function renderTile(tile) {
        const id = tile.dataset.imageId;
        tile.classList.toggle("selected", selected.has(id));
    }

    function renderAll() {
        tiles.forEach(renderTile);
        if (batchCount) batchCount.textContent = `${selected.size} ausgewählt`;
    }

    function enterMode() {
        if (!batchBar || selectMode) return;
        selectMode = true;
        root.dataset.selectMode = "1";
        batchBar.hidden = false;
        renderAll();
    }

    function exitMode() {
        if (!batchBar || !selectMode) return;
        selectMode = false;
        delete root.dataset.selectMode;
        batchBar.hidden = true;
        selected.clear();
        lastAnchorIndex = -1;
        setError("");
        renderAll();
    }

    function toggleId(id, on) {
        if (on === undefined) on = !selected.has(id);
        if (on) selected.add(id); else selected.delete(id);
    }

    function selectRange(fromIdx, toIdx) {
        if (fromIdx < 0) fromIdx = toIdx;
        const [lo, hi] = fromIdx <= toIdx ? [fromIdx, toIdx] : [toIdx, fromIdx];
        for (let i = lo; i <= hi; i++) selected.add(tiles[i].dataset.imageId);
    }

    tiles.forEach((tile, idx) => {
        tile.addEventListener("click", (ev) => {
            const usingChord = ev.shiftKey || ev.ctrlKey || ev.metaKey;
            if (!selectMode && !usingChord) return;
            ev.preventDefault();
            if (!selectMode) enterMode();
            const id = tile.dataset.imageId;
            if (ev.shiftKey && lastAnchorIndex >= 0) {
                selectRange(lastAnchorIndex, idx);
            } else if (ev.ctrlKey || ev.metaKey) {
                toggleId(id);
                lastAnchorIndex = idx;
            } else {
                if (selected.has(id) && selected.size === 1) {
                    selected.delete(id);
                } else {
                    selected.clear();
                    selected.add(id);
                }
                lastAnchorIndex = idx;
            }
            setError("");
            renderAll();
        });
    });

    function selectedIds() { return Array.from(selected); }

    async function postBatch(payload) {
        const ids = selectedIds();
        if (!ids.length) {
            setError("Keine Bilder ausgewählt.");
            return null;
        }
        const body = new URLSearchParams();
        ids.forEach(id => body.append("image_ids", id));
        Object.entries(payload).forEach(([k, v]) => body.append(k, v));
        const res = await fetch(batchUrl, {
            method: "POST",
            headers: {
                "X-CSRFToken": csrfToken,
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            body,
        });
        if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            setError(data.error || "Fehler beim Speichern.");
            return null;
        }
        setError("");
        return res.json();
    }

    function reloadAfterSave() {
        window.location.reload();
    }

    function resetInput(modal) {
        if (!modal) return null;
        const input = modal.querySelector("input[type=text]");
        if (!input) return null;
        input.value = "";
        const suggestions = modal.querySelector("[data-place-suggestions], [data-date-suggestions]");
        if (suggestions) suggestions.hidden = true;
        const preview = modal.querySelector("[data-date-preview]");
        if (preview) { preview.textContent = ""; preview.classList.remove("error"); }
        return input;
    }

    function showModal(modal) {
        if (!modal) return;
        const input = resetInput(modal);
        modal.hidden = false;
        if (input) input.focus();
    }

    function hideModal(modal) { if (modal) modal.hidden = true; }

    function showPlaceModal() { showModal(placeModal); }
    function hidePlaceModal() { hideModal(placeModal); }

    function showDateModal() { showModal(dateModal); }
    function hideDateModal() { hideModal(dateModal); }

    async function applyPlaceModal() {
        const input = placeModal.querySelector("input[name=place]");
        const value = input ? input.value : "";
        const r = await postBatch({ action: "place", place: value });
        if (r) {
            hidePlaceModal();
            reloadAfterSave();
        }
    }

    async function applyDateModal() {
        const input = dateModal.querySelector("input[name=date_display]");
        const value = input ? input.value : "";
        const r = await postBatch({ action: "date_display", date_display: value });
        if (r) {
            hideDateModal();
            reloadAfterSave();
        }
    }

    function promptClearTodos() {
        if (!window.confirm("Alle Todos für die Auswahl entfernen?")) return;
        postBatch({ action: "clear_todos" }).then(r => { if (r) reloadAfterSave(); });
    }

    function showTodoModal() {
        if (!todoModal) return;
        todoModal.querySelectorAll("[data-todo-field]").forEach(el => {
            if (el.type === "checkbox") el.checked = false;
            else el.value = "";
        });
        todoModal.hidden = false;
        const first = todoModal.querySelector("[data-todo-field]");
        if (first) first.focus();
    }

    function hideTodoModal() { if (todoModal) todoModal.hidden = true; }

    async function applyTodoModal() {
        const fields = todoModal.querySelectorAll("[data-todo-field]");
        let any = false;
        for (const el of fields) {
            const name = el.dataset.todoField;
            if (el.type === "checkbox") {
                if (el.checked) {
                    const r = await postBatch({ action: name, value: "true" });
                    if (!r) return;
                    any = true;
                }
            } else if (el.value) {
                const r = await postBatch({ action: name, value: el.value });
                if (!r) return;
                any = true;
            }
        }
        hideTodoModal();
        if (any) reloadAfterSave();
    }

    function bindModal(modal, onCancel, onApply) {
        if (!modal) return;
        modal.addEventListener("click", (ev) => { if (ev.target === modal) onCancel(); });
        const cancel = modal.querySelector("[data-batch-modal-cancel], [data-todo-modal-cancel]");
        const apply = modal.querySelector("[data-batch-modal-apply], [data-todo-modal-apply]");
        if (cancel) cancel.addEventListener("click", onCancel);
        if (apply) apply.addEventListener("click", onApply);
    }

    bindModal(placeModal, hidePlaceModal, applyPlaceModal);
    bindModal(dateModal, hideDateModal, applyDateModal);
    bindModal(todoModal, hideTodoModal, applyTodoModal);

    function anyModalVisible() {
        return (placeModal && !placeModal.hidden)
            || (dateModal && !dateModal.hidden)
            || (todoModal && !todoModal.hidden);
    }

    function hideAllModals() {
        hidePlaceModal();
        hideDateModal();
        hideTodoModal();
    }

    if (batchBar) {
        batchBar.addEventListener("click", (ev) => {
            const actBtn = ev.target.closest("[data-batch-action]");
            if (actBtn) {
                const act = actBtn.dataset.batchAction;
                if (act === "select-all") {
                    tiles.forEach(t => selected.add(t.dataset.imageId));
                    renderAll();
                } else if (act === "invert") {
                    tiles.forEach(t => {
                        const id = t.dataset.imageId;
                        if (selected.has(id)) selected.delete(id); else selected.add(id);
                    });
                    renderAll();
                } else if (act === "clear") {
                    selected.clear();
                    renderAll();
                } else if (act === "exit") {
                    exitMode();
                }
                return;
            }
            const promptBtn = ev.target.closest("[data-batch-prompt]");
            if (!promptBtn) return;
            const which = promptBtn.dataset.batchPrompt;
            if (which === "place") showPlaceModal();
            else if (which === "date") showDateModal();
            else if (which === "todos") showTodoModal();
            else if (which === "clear-todos") promptClearTodos();
        });
    }

    document.addEventListener("keydown", (ev) => {
        if (ev.ctrlKey || ev.metaKey || ev.altKey) return;

        if (ev.key === "Escape") {
            if (anyModalVisible()) {
                ev.preventDefault();
                hideAllModals();
                return;
            }
            if (selectMode) {
                ev.preventDefault();
                exitMode();
            }
            return;
        }

        if (isTypingTarget(document.activeElement)) return;

        if (!batchBar) return;

        if (ev.key === "v") {
            ev.preventDefault();
            if (selectMode) exitMode(); else enterMode();
        } else if (ev.key === "a" && selectMode) {
            ev.preventDefault();
            tiles.forEach(t => selected.add(t.dataset.imageId));
            renderAll();
        } else if (ev.key === "t" && selectMode && selected.size > 0) {
            ev.preventDefault();
            showTodoModal();
        }
    });
})();
