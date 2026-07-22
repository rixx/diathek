// ⁂ Client for the Immich edit round-trip, forked from upload.js.
// Two phases: "Zuordnen" sends links + filenames to the prepare endpoint and
// renders the matched-pairs preview; "Ersetzen" then streams the files through
// the per-file endpoint one at a time. Changing files or links resets to
// phase one.
(function () {
    const form = document.getElementById("immich-edit-form");
    if (!form || !window.fetch) return;

    const fileInput = document.getElementById("immich-edit-files");
    const linksInput = document.getElementById("immich-edit-links");
    const dropzone = form.querySelector("[data-dropzone]");
    const listEl = form.querySelector("[data-upload-list]");
    const summaryEl = form.querySelector("[data-upload-summary]");
    const submitBtn = form.querySelector("[data-edit-submit]");
    if (!fileInput || !linksInput || !listEl || !submitBtn) return;

    const prepareUrl = form.dataset.prepareUrl;
    const fileUrlTemplate = form.dataset.fileUrlTemplate;
    const csrf = form.querySelector('[name="csrfmiddlewaretoken"]').value;

    const STATUS_LABEL = {
        pending: "⁂ wartet",
        matched: "⁂ zugeordnet",
        unmatched: "⁂ nicht zugeordnet",
        ambiguous: "⁂ mehrdeutig — wird übersprungen",
        uploading: "⁂ ersetzt …",
        done: "⁂ ersetzt",
        error: "⁂ Fehler",
    };

    let entries = []; // {file, status, sourceLabel, thumbnailUrl, rowEl, statusEl}
    let running = false;
    let sessionId = null;

    if (dropzone) dropzone.hidden = false;

    function fmtSize(bytes) {
        if (bytes < 1024) return bytes + " B";
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + " KB";
        return (bytes / (1024 * 1024)).toFixed(1) + " MB";
    }

    function keyOf(file) {
        return file.name + ":" + file.size;
    }

    function resetMatching() {
        sessionId = null;
        submitBtn.textContent = "Zuordnen";
        entries.forEach((entry) => {
            entry.status = "pending";
            entry.sourceLabel = null;
            entry.thumbnailUrl = null;
        });
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
        resetMatching();
        render();
    }

    function render() {
        listEl.textContent = "";
        entries.forEach((entry, idx) => {
            const li = document.createElement("li");
            li.className = "upload-item upload-" + entry.status;

            if (entry.thumbnailUrl) {
                const thumb = document.createElement("img");
                thumb.className = "upload-item-thumb";
                thumb.src = entry.thumbnailUrl;
                thumb.alt = "";
                li.append(thumb);
            }

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

            if (entry.sourceLabel) {
                const source = document.createElement("span");
                source.className = "upload-item-source";
                source.textContent = "⁂ ersetzt " + entry.sourceLabel;
                li.append(source);
            }

            if (!running && !sessionId) {
                const remove = document.createElement("button");
                remove.type = "button";
                remove.className = "upload-item-remove";
                remove.setAttribute("aria-label", "Entfernen");
                remove.textContent = "✕";
                remove.addEventListener("click", () => {
                    entries.splice(idx, 1);
                    resetMatching();
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
        fileInput.value = "";
    });

    linksInput.addEventListener("input", () => {
        if (running) return;
        resetMatching();
        render();
    });

    form.querySelectorAll("[data-recent-link]").forEach((button) => {
        button.addEventListener("click", () => {
            if (running) return;
            linksInput.value = button.dataset.recentLink;
            resetMatching();
            render();
        });
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

    function showSummary(message, ok) {
        summaryEl.hidden = false;
        summaryEl.className =
            "upload-summary " + (ok ? "upload-summary-ok" : "upload-summary-error");
        summaryEl.textContent = message;
    }

    async function prepare() {
        const data = new FormData();
        data.append("links", linksInput.value);
        entries.forEach((entry) => data.append("filenames", entry.file.name));
        const resp = await fetch(prepareUrl, {
            method: "POST",
            body: data,
            headers: { "X-CSRFToken": csrf },
        });
        const payload = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(payload.error || "⁂ Fehler beim Zuordnen.");
        return payload;
    }

    function applyMatches(payload) {
        sessionId = payload.session_id;
        const byName = new Map(payload.items.map((item) => [item.filename, item]));
        entries.forEach((entry) => {
            const item = byName.get(entry.file.name);
            if (item) {
                entry.status = "matched";
                entry.sourceLabel =
                    item.source_filename +
                    (item.source_date ? " (" + item.source_date + ")" : "");
                entry.thumbnailUrl = item.thumbnail_url;
            } else if (payload.ambiguous.includes(entry.file.name)) {
                entry.status = "ambiguous";
            } else {
                entry.status = "unmatched";
            }
        });
        submitBtn.textContent = "Ersetzen";
        showSummary(
            "⁂ " +
                payload.items.length +
                " von " +
                entries.length +
                " Dateien zugeordnet. „Ersetzen“ startet den Austausch.",
            true,
        );
    }

    async function replaceOne(entry) {
        const data = new FormData();
        data.append("file", entry.file, entry.file.name);
        const url = fileUrlTemplate.replace(
            "00000000-0000-0000-0000-000000000000",
            sessionId,
        );
        const resp = await fetch(url, {
            method: "POST",
            body: data,
            headers: { "X-CSRFToken": csrf },
        });
        const payload = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(payload.error || "HTTP " + resp.status);
        if (payload.state === "error")
            throw new Error(payload.error || "⁂ Fehler beim Ersetzen.");
        return payload;
    }

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        if (running) return;

        if (!entries.length) {
            showSummary("Bitte zuerst Dateien auswählen.", false);
            return;
        }

        running = true;
        summaryEl.hidden = true;
        render();

        if (!sessionId) {
            try {
                const payload = await prepare();
                applyMatches(payload);
            } catch (err) {
                showSummary(err.message, false);
            }
            running = false;
            render();
            return;
        }

        const queue = entries.filter(
            (entry) => entry.status === "matched" || entry.status === "error",
        );
        let done = 0;
        let failed = 0;
        for (const entry of queue) {
            setStatus(entry, "uploading");
            try {
                await replaceOne(entry);
                setStatus(entry, "done");
                done += 1;
            } catch (err) {
                setStatus(entry, "error", STATUS_LABEL.error + ": " + err.message);
                failed += 1;
            }
        }

        running = false;
        render();

        let msg = "⁂ " + done + " ersetzt";
        if (failed) msg += ", " + failed + " fehlgeschlagen";
        showSummary(msg + ".", failed === 0);
    });

    render();
})();
