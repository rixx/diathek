// Client-side, one-at-a-time image uploader for the import page.
// Progressive enhancement: without JS the plain multipart form still works.
(function () {
    const form = document.getElementById("upload-form");
    if (!form || !window.fetch) return;

    const fileInput = form.querySelector('input[type="file"]');
    const boxSelect = form.querySelector("[data-box-choice]");
    const dropzone = form.querySelector("[data-dropzone]");
    const listEl = form.querySelector("[data-upload-list]");
    const summaryEl = form.querySelector("[data-upload-summary]");
    const submitBtn = form.querySelector("[data-upload-submit]");
    if (!fileInput || !listEl || !submitBtn) return;

    const prepareUrl = form.dataset.prepareUrl;
    const uploadUrl = form.dataset.uploadUrl;
    const csrf = form.querySelector('[name="csrfmiddlewaretoken"]').value;

    const STATUS_LABEL = {
        pending: "wartet",
        uploading: "lädt …",
        done: "fertig",
        skipped: "übersprungen (Duplikat)",
        error: "Fehler",
    };

    let entries = []; // {file, status, rowEl, statusEl}
    let running = false;
    let resolved = null; // {box, redirect} — set once per page after first prepare

    if (dropzone) dropzone.hidden = false;

    function fmtSize(bytes) {
        if (bytes < 1024) return bytes + " B";
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + " KB";
        return (bytes / (1024 * 1024)).toFixed(1) + " MB";
    }

    function keyOf(file) {
        return file.name + ":" + file.size;
    }

    function addFiles(fileList) {
        if (running) return;
        const seen = new Set(entries.map((e) => keyOf(e.file)));
        for (const file of fileList) {
            const k = keyOf(file);
            if (seen.has(k)) continue;
            seen.add(k);
            entries.push({ file, status: "pending" });
        }
        render();
    }

    function render() {
        listEl.textContent = "";
        entries.forEach((entry, idx) => {
            const li = document.createElement("li");
            li.className = "upload-item upload-" + entry.status;

            const name = document.createElement("span");
            name.className = "upload-item-name";
            name.textContent = entry.file.name;

            const size = document.createElement("span");
            size.className = "upload-item-size";
            size.textContent = fmtSize(entry.file.size);

            const status = document.createElement("span");
            status.className = "upload-item-status";
            status.textContent = STATUS_LABEL[entry.status];

            li.append(name, size, status);

            if (!running && entry.status === "pending") {
                const remove = document.createElement("button");
                remove.type = "button";
                remove.className = "upload-item-remove";
                remove.setAttribute("aria-label", "Entfernen");
                remove.textContent = "✕";
                remove.addEventListener("click", () => {
                    entries.splice(idx, 1);
                    render();
                });
                li.append(remove);
            }

            entry.rowEl = li;
            entry.statusEl = status;
            listEl.append(li);
        });
        submitBtn.disabled = running || entries.length === 0;
    }

    function setStatus(entry, status, text) {
        entry.status = status;
        if (entry.rowEl) entry.rowEl.className = "upload-item upload-" + status;
        if (entry.statusEl) entry.statusEl.textContent = text || STATUS_LABEL[status];
    }

    fileInput.addEventListener("change", () => {
        addFiles(fileInput.files);
        fileInput.value = ""; // allow picking the same file again after removal
    });

    if (dropzone) {
        ["dragenter", "dragover"].forEach((ev) =>
            dropzone.addEventListener(ev, (e) => {
                e.preventDefault();
                dropzone.classList.add("is-over");
            }),
        );
        ["dragleave", "drop"].forEach((ev) =>
            dropzone.addEventListener(ev, (e) => {
                e.preventDefault();
                dropzone.classList.remove("is-over");
            }),
        );
        dropzone.addEventListener("drop", (e) => {
            if (e.dataTransfer && e.dataTransfer.files) addFiles(e.dataTransfer.files);
        });
        dropzone.addEventListener("click", () => fileInput.click());
    }

    async function prepare() {
        const data = new FormData();
        data.append("box_choice", boxSelect ? boxSelect.value : "");
        const nameInput = form.querySelector('[name="new_box_name"]');
        const descInput = form.querySelector('[name="new_box_description"]');
        if (nameInput) data.append("new_box_name", nameInput.value);
        if (descInput) data.append("new_box_description", descInput.value);
        const resp = await fetch(prepareUrl, {
            method: "POST",
            body: data,
            headers: { "X-CSRFToken": csrf },
        });
        const payload = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(payload.error || "Fehler beim Vorbereiten.");
        return payload;
    }

    async function uploadOne(entry, box) {
        const data = new FormData();
        data.append("files", entry.file, entry.file.name);
        if (box) data.append("box", box);
        const resp = await fetch(uploadUrl, {
            method: "POST",
            body: data,
            headers: { "X-CSRFToken": csrf },
        });
        const payload = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(payload.error || "HTTP " + resp.status);
        return payload.skipped && payload.skipped.length ? "skipped" : "done";
    }

    function showSummary(message, ok) {
        summaryEl.hidden = false;
        summaryEl.className =
            "upload-summary " + (ok ? "upload-summary-ok" : "upload-summary-error");
        summaryEl.textContent = message;
    }

    function lockTarget() {
        if (boxSelect) boxSelect.disabled = true;
        form.querySelectorAll("[data-new-box-fields] input, [data-new-box-fields] textarea")
            .forEach((el) => {
                el.disabled = true;
            });
    }

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        if (running) return;

        const queue = entries.filter(
            (en) => en.status === "pending" || en.status === "error",
        );
        if (!queue.length) {
            showSummary("Bitte zuerst Dateien auswählen.", false);
            return;
        }

        running = true;
        summaryEl.hidden = true;
        render();

        if (!resolved) {
            try {
                resolved = await prepare();
            } catch (err) {
                running = false;
                render();
                showSummary(err.message, false);
                return;
            }
            lockTarget();
        }

        let done = 0;
        let skipped = 0;
        let failed = 0;
        for (const entry of queue) {
            setStatus(entry, "uploading");
            try {
                const result = await uploadOne(entry, resolved.box);
                if (result === "skipped") {
                    setStatus(entry, "skipped");
                    skipped += 1;
                } else {
                    setStatus(entry, "done");
                    done += 1;
                }
            } catch (err) {
                setStatus(entry, "error", "Fehler: " + err.message);
                failed += 1;
            }
        }

        running = false;
        render();

        let msg = done + " hochgeladen";
        if (skipped) msg += ", " + skipped + " übersprungen";
        if (failed) msg += ", " + failed + " fehlgeschlagen";
        showSummary(msg + ".", failed === 0);
        if (resolved.redirect && !failed) {
            const link = document.createElement("a");
            link.href = resolved.redirect;
            link.className = "upload-summary-link";
            link.textContent = "Weiter →";
            summaryEl.append(" ", link);
        }
    });

    render();
})();
