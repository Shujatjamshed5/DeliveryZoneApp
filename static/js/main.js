/* ═══════════════════════════════════════════════════
   AI Areas Importer — Client Logic
   (Upload / SSE / form contract unchanged — only
    presentation logic added/updated for the new UI)
   ═══════════════════════════════════════════════════ */
(() => {
    'use strict';

    /* ── DOM refs ── */
    const $  = (s, p = document) => p.querySelector(s);
    const $$ = (s, p = document) => [...p.querySelectorAll(s)];

    // Phases
    const phaseForm     = $('#phase-form');
    const phaseProgress = $('#phase-progress');
    const phaseResults  = $('#phase-results');

    // Form
    const form        = $('#importForm');
    const btnSubmit   = $('#btnSubmit');
    const btnLabel    = $('.btn-submit__label');
    const btnLoader   = $('.btn-submit__loader');

    // Dropzone
    const dropzone     = $('#dropzone');
    const fileInput    = $('#fileInput');
    const dropzoneIdle = $('#dropzoneIdle');
    const dropzoneFill = $('#dropzoneFilled');
    const fileNameEl   = $('#fileName');
    const removeBtn    = $('#removeFile');

    // Stepper
    const stepper        = $('#stepper');
    const progressFileEl = $('#progressFile');
    const overallBarFill = $('#overallBarFill');

    // Live console (phase 2)
    const liveConsoleList  = $('#liveConsoleList');
    const liveConsoleEmpty = $('#liveConsoleEmpty');

    // Timer
    const timerElapsed  = $('#timerElapsed');
    const timerEstimate = $('#timerEstimate');

    // Results
    const resultHero   = $('#resultHero');
    const resultIcon   = $('#resultIcon');
    const resultTitle  = $('#resultTitle');
    const resultSub    = $('#resultSub');
    const statsGrid    = $('#statsGrid');
    const missingCard  = $('#missingAreasCard');
    const missingZonesCtr = $('#missingZonesContainer');
    const missingCountBadge = $('#missingCountBadge');
    const toggleMissing = $('#toggleMissing');
    const logsContent  = $('#logsContent');
    const btnReset     = $('#btnReset');

    // Toast
    const errorToast    = $('#errorToast');
    const errorToastMsg = $('#errorToastMsg');
    const closeToast    = $('#closeToast');

    /* ── State ── */
    let selectedFile = null;
    let eventSource  = null;
    let timerInterval = null;
    let startTime     = null;

    // Rough per-step time estimates (seconds)
    const STEP_EST = { 1: 5, 2: 15, 3: 8, 4: 4, 5: 20 };
    const TOTAL_EST = Object.values(STEP_EST).reduce((a, b) => a + b, 0);
    const TOTAL_STEPS = 5;

    /* ═══════════════════════════════════════════════
       MESSAGE TRANSLATOR
       Converts raw backend text (SSE step details AND
       report.logs lines) into short, plain-English
       sentences with an accurate status ('active' |
       'success' | 'warn' | 'error' | 'info'). This is
       presentation-only — it never touches what the
       backend actually did, only how it's described.
       Returns null for lines that should be hidden
       (decorative separators, the raw ASCII summary
       block — those numbers now live in the stat cards).
       ═══════════════════════════════════════════════ */
    function translateLogLine(raw) {
        const s = String(raw).trim();
        if (!s) return null;

        // Decorative separators / raw summary block — already shown as stat cards
        if (/^=+$/.test(s)) return null;
        if (/^SUMMARY$/i.test(s)) return null;
        if (/^(Total Zones|Created|Updated|Areas Added\/Updated|Removed\/Moved|Deduplicated|Subtotal Areas.*|Skipped|Failed):/i.test(s)) return null;

        // Phase headers, e.g. "── PHASE 1: Deduplication & Price Check..."
        const phase = s.match(/^─+\s*PHASE\s*\d+:\s*(.+?)\.*$/i);
        if (phase) return { status: 'info', text: phase[1].trim() };

        const rules = [
            [/^Extracting data from (.+?)\.\.\.$/i, m => ({ status: 'active', text: `Reading ${m[1]}…` })],
            [/^Found (\d+) data row\(s\) in (.+)$/i, m => ({ status: 'success', text: `Found ${m[1]} rows in ${m[2]}` })],
            [/^Using branch city: (.+)$/i, m => ({ status: 'info', text: `Using city: ${m[1]}` })],
            [/^Sending data to Groq AI.*$/i, () => ({ status: 'active', text: 'Sending data to AI for cleaning…' })],
            [/^AI found (\d+) area\(s\) → (\d+) zone\(s\) by delivery charge$/i, m => ({ status: 'success', text: `AI grouped ${m[1]} areas into ${m[2]} delivery zones` })],
            [/^City: (.+?)\. Fuzzy matching (\d+) areas strictly within .+?\.\.\.$/i, m => ({ status: 'active', text: `Matching ${m[2]} areas within ${m[1]}…` })],
            [/^(.+?): Matched (\d+)\/(\d+) areas across (\d+) zone\(s\)\. (\d+) unresolved\.$/i, m => ({ status: 'success', text: `Matched ${m[2]} of ${m[3]} areas across ${m[4]} zones (${m[5]} unresolved)` })],
            [/^Preparing portal connection as (.+?)\.\.\.$/i, m => ({ status: 'active', text: `Connecting to portal as ${m[1]}…` })],
            [/^Login successful!?$/i, () => ({ status: 'success', text: 'Logged into the portal successfully' })],
            [/^Uploading (\d+) zone\(s\) to portal\.\.\.$/i, m => ({ status: 'active', text: `Uploading ${m[1]} zones to the portal…` })],
            [/^Processing '(.+?)' \((\d+)\/(\d+)\)\.\.\.$/i, m => ({ status: 'active', text: `Processing zone '${m[1]}' (${m[2]} of ${m[3]})…` })],
            [/^Skipped '(.+?)' \((\d+)\/(\d+)\)$/i, m => ({ status: 'warn', text: `Skipped zone '${m[1]}' (${m[2]} of ${m[3]})` })],
            [/^Done! Created=(\d+), Updated=(\d+), Removed=(\d+), Failed=(\d+)$/i, m => ({ status: 'success', text: `Finished — Created ${m[1]}, Updated ${m[2]}, Moved ${m[3]}, Failed ${m[4]}` })],
            [/^All zones processed!?$/i, () => ({ status: 'success', text: 'All zones processed' })],

            [/^Starting enhanced import: (\d+) zone\(s\) to process\.$/i, m => ({ status: 'info', text: `Starting import — ${m[1]} zones to process` })],
            [/^Using city_id=(.+)$/i, m => ({ status: 'info', text: `Using city ID ${m[1]}` })],
            [/^Reusing pre-authenticated session\.$/i, () => ({ status: 'info', text: 'Reusing existing login session' })],
            [/^Successfully authenticated to portal\.$/i, () => ({ status: 'success', text: 'Logged into portal successfully' })],
            [/^Fetching ALL existing zones from portal\.\.\.$/i, () => ({ status: 'info', text: 'Fetching existing zones from the portal…' })],
            [/^Found (\d+) existing zone\(s\) on portal\.$/i, m => ({ status: 'info', text: `Found ${m[1]} existing zones on the portal` })],
            [/^Built area deduplication map with (\d+) area\(s\)\.$/i, m => ({ status: 'info', text: `Checked ${m[1]} areas for duplicates` })],
            [/^DEDUP: (.+?) found in WRONG zone '(.+?)' \(fee=(.+?)\) → moving to '(.+?)' \(fee=(.+?)\)$/i, m => ({ status: 'warn', text: `'${m[1]}' found in wrong zone '${m[2]}' — moving to '${m[4]}'` })],
            [/^PRICE CHANGE: '(.+?)' fee: (.+?) → (.+?)$/i, m => ({ status: 'info', text: `Zone '${m[1]}' price changed: ${m[2]} → ${m[3]}` })],
            [/^DUPLICATE FOUND: (\d+) area\(s\) in '(.+?)' already: .+? → moving to '(.+?)'$/i, m => ({ status: 'warn', text: `Found ${m[1]} duplicate areas in '${m[2]}' — moving to '${m[3]}'` })],
            [/^REMOVING (\d+) area\(s\) from '(.+?)': .+? \(keeping (\d+)\)$/i, m => ({ status: 'warn', text: `Removing ${m[1]} duplicate areas from '${m[2]}' (keeping ${m[3]})` })],
            [/^⚠️?\s*SKIP: '(.+?)' would have 0 areas - not saving$/i, m => ({ status: 'warn', text: `Skipped '${m[1]}' — would be left with zero areas` })],
            [/^✓ Removed (\d+) area\(s\) from '(.+?)'$/i, m => ({ status: 'success', text: `Removed ${m[1]} duplicate areas from '${m[2]}'` })],
            [/^✗ Failed to remove from '(.+?)': (.+)$/i, m => ({ status: 'error', text: `Failed to update '${m[1]}': ${m[2]}` })],
            [/^SKIP '(.+?)' — zero valid mapped areas\.$/i, m => ({ status: 'warn', text: `Skipped '${m[1]}' — no matched areas` })],
            [/^SKIP '(.+?)' — already up-to-date \(fee=.+?, areas=(\d+)\)$/i, m => ({ status: 'info', text: `'${m[1]}' already up to date (${m[2]} areas)` })],
            [/^UPDATE '(.+?)' — added (\d+) area\(s\): .+? \(\d+ → (\d+) total\)$/i, m => ({ status: 'info', text: `Adding ${m[2]} areas to '${m[1]}' (now ${m[3]} areas total)` })],
            [/^UPDATE '(.+?)' — price change (.+?)→(.+?) \(\d+ areas\)$/i, m => ({ status: 'info', text: `Updating price for '${m[1]}': ${m[2]} → ${m[3]}` })],
            [/^✓ Updated '(.+?)'$/i, m => ({ status: 'success', text: `Updated zone '${m[1]}'` })],
            [/^✗ Failed '(.+?)' — (.+?) \(areas: .*\)$/i, m => ({ status: 'error', text: `Failed to update '${m[1]}': ${m[2]}` })],
            [/^CREATE '(.+?)' — (\d+) area\(s\), fee=(.+?) \| areas: .+$/i, m => ({ status: 'info', text: `Creating '${m[1]}' with ${m[2]} areas (fee: ${m[3]})` })],
            [/^✓ Created '(.+?)'$/i, m => ({ status: 'success', text: `Created zone '${m[1]}'` })],
            [/^✗ Failed to create '(.+?)': (.+)$/i, m => ({ status: 'error', text: `Failed to create '${m[1]}': ${m[2]}` })],
            [/^UNRESOLVED: '(.+?)' not found in area database for zone '(.+?)' — add it manually$/i, m => ({ status: 'warn', text: `'${m[1]}' not found in database (zone '${m[2]}') — add it manually on the portal` })],
            [/^CRITICAL ERROR/i, () => ({ status: 'error', text: 'A critical error occurred — check server logs for details' })],
        ];

        for (const [re, fn] of rules) {
            const m = s.match(re);
            if (m) return fn(m);
        }

        // Fallback — strip leading symbols/dashes, best-effort status guess
        const stripped = s.replace(/^[\s✓✔✗✘⚠️⚠ℹ️ℹ⟳─]+/u, '').trim();
        if (!stripped) return null;
        let status = 'info';
        if (/error|fail/i.test(s)) status = 'error';
        else if (/warn/i.test(s)) status = 'warn';
        else if (/success|created|done|updated|removed/i.test(s)) status = 'success';
        return { status, text: stripped };
    }

    /* ═══════════════════════════════════════════════
       1. DRAG & DROP
       ═══════════════════════════════════════════════ */
    dropzone.addEventListener('click', () => fileInput.click());

    dropzone.addEventListener('dragover', e => {
        e.preventDefault();
        dropzone.classList.add('dragover');
    });

    dropzone.addEventListener('dragleave', e => {
        e.preventDefault();
        dropzone.classList.remove('dragover');
    });

    dropzone.addEventListener('drop', e => {
        e.preventDefault();
        dropzone.classList.remove('dragover');
        if (e.dataTransfer.files.length) {
            setFile(e.dataTransfer.files[0]);
        }
    });

    fileInput.addEventListener('change', () => {
        if (fileInput.files.length) setFile(fileInput.files[0]);
    });

    removeBtn.addEventListener('click', e => {
        e.stopPropagation();
        clearFile();
    });

    function setFile(file) {
        selectedFile = file;
        fileNameEl.textContent = file.name;
        dropzoneIdle.classList.add('hidden');
        dropzoneFill.classList.remove('hidden');
    }

    function clearFile() {
        selectedFile = null;
        fileInput.value = '';
        dropzoneIdle.classList.remove('hidden');
        dropzoneFill.classList.add('hidden');
    }

    /* ═══════════════════════════════════════════════
       2. FORM SUBMIT
       ═══════════════════════════════════════════════ */
    form.addEventListener('submit', async e => {
        e.preventDefault();

        // Validate
        const username    = $('#username').value.trim();
        const password    = $('#password').value.trim();
        const merchantId  = $('#merchant_id').value.trim();
        const branchId    = $('#branch_id').value.trim();
        const cityName    = $('#city_name').value.trim();

        if (!username || !password || !merchantId || !branchId) {
            showToast('Please fill in all credential fields.');
            return;
        }
        if (!cityName) {
            showToast('Please select the branch\'s city.');
            return;
        }
        if (!selectedFile) {
            showToast('Please select a file to upload.');
            return;
        }

        // Show loader
        btnSubmit.disabled = true;
        btnLabel.classList.add('hidden');
        btnLoader.classList.remove('hidden');

        try {
            // Step A: Upload file + form data
            const formData = new FormData();
            formData.append('file', selectedFile);
            formData.append('username', username);
            formData.append('password', password);
            formData.append('merchant_id', merchantId);
            formData.append('branch_id', branchId);
            formData.append('city_name', cityName);

            const res = await fetch('/api/upload-file', {
                method: 'POST',
                body: formData,
            });

            if (!res.ok) {
                const err = await res.json().catch(() => ({ error: 'Upload failed' }));
                throw new Error(err.error || 'Upload failed');
            }

            const { session_id } = await res.json();

            // Step B: Switch to progress phase
            progressFileEl.textContent = `Processing "${selectedFile.name}"`;
            switchPhase('progress');
            resetStepper();
            resetLiveConsole();
            startTimer();

            // Step C: Open SSE
            openSSE(session_id);

        } catch (err) {
            showToast(err.message || 'Something went wrong.');
            btnSubmit.disabled = false;
            btnLabel.classList.remove('hidden');
            btnLoader.classList.add('hidden');
        }
    });

    /* ═══════════════════════════════════════════════
       3. SSE HANDLER
       ═══════════════════════════════════════════════ */
    function openSSE(sessionId) {
        const url = `/api/process?session_id=${encodeURIComponent(sessionId)}`;
        eventSource = new EventSource(url);

        eventSource.onmessage = (evt) => {
            let data;
            try {
                data = JSON.parse(evt.data);
            } catch {
                return;
            }

            // Numeric step update
            if (typeof data.step === 'number') {
                updateStep(data.step, data.status, data.detail);
                updateEstimate(data.step, data.status);
                updateOverallBar(data.step, data.status);
                addConsoleEntry(data.status, data.detail || data.title);
                return;
            }

            // Complete
            if (data.step === 'complete') {
                closeSSE();
                stopTimer();
                if (overallBarFill) overallBarFill.style.width = '100%';
                showResults(data.report);
                return;
            }

            // Error
            if (data.step === 'error') {
                closeSSE();
                stopTimer();
                addConsoleEntry('error', data.message);
                showGlobalError(data.message);
                return;
            }
        };

        eventSource.onerror = () => {
            closeSSE();
            stopTimer();
            showGlobalError('Connection to server lost.');
        };
    }

    function closeSSE() {
        if (eventSource) {
            eventSource.close();
            eventSource = null;
        }
    }

    /* ═══════════════════════════════════════════════
       4. STEPPER UI
       ═══════════════════════════════════════════════ */
    function resetStepper() {
        $$('.step', stepper).forEach(el => {
            el.classList.remove('active', 'done', 'error');
            const detail = $('.step__detail', el);
            if (detail) detail.textContent = 'Waiting…';
        });
        if (overallBarFill) overallBarFill.style.width = '0%';
    }

    function updateStep(stepNum, status, detail) {
        const stepEl = $(`.step[data-step="${stepNum}"]`, stepper);
        if (!stepEl) return;

        const detailEl = $('.step__detail', stepEl);
        if (detailEl && detail) detailEl.textContent = detail;

        // Remove old state
        stepEl.classList.remove('active', 'done', 'error');

        if (status === 'active') {
            stepEl.classList.add('active');
            // Mark all previous steps as done (safety)
            for (let i = 1; i < stepNum; i++) {
                const prev = $(`.step[data-step="${i}"]`, stepper);
                if (prev && !prev.classList.contains('done')) {
                    prev.classList.remove('active', 'error');
                    prev.classList.add('done');
                }
            }
        } else if (status === 'done') {
            stepEl.classList.add('done');
        } else if (status === 'error') {
            stepEl.classList.add('error');
        }

        // Scroll the active step into view
        stepEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    function updateOverallBar(stepNum, status) {
        if (!overallBarFill) return;
        let completed = status === 'done' ? stepNum : (stepNum - 1 + 0.5);
        completed = Math.max(0, Math.min(TOTAL_STEPS, completed));
        const pct = (completed / TOTAL_STEPS) * 100;
        overallBarFill.style.width = `${pct}%`;
    }

    /* ═══════════════════════════════════════════════
       4b. LIVE ACTIVITY CONSOLE (phase 2)
       ═══════════════════════════════════════════════ */
    function resetLiveConsole() {
        if (!liveConsoleList) return;
        liveConsoleList.innerHTML = '';
        const empty = document.createElement('p');
        empty.className = 'console__empty';
        empty.id = 'liveConsoleEmpty';
        empty.textContent = 'Waiting for the pipeline to start…';
        liveConsoleList.appendChild(empty);
    }

    const BADGE_MAP = {
        active: { cls: 'is-active', icon: 'ph-bold ph-circle-notch spinner' },
        success:{ cls: 'is-success', icon: 'ph-bold ph-check' },
        warn:   { cls: 'is-warn', icon: 'ph-bold ph-warning' },
        error:  { cls: 'is-error', icon: 'ph-bold ph-x' },
        info:   { cls: 'is-info', icon: 'ph-bold ph-info' },
    };

    function addConsoleEntry(rawStatus, rawText) {
        if (!liveConsoleList || !rawText) return;
        const emptyEl = $('#liveConsoleEmpty', liveConsoleList);
        if (emptyEl) emptyEl.remove();

        // A new event just arrived, so whatever was previously "live" (spinning)
        // is now finished — freeze it to a checkmark instead of leaving it
        // spinning forever, which is what made everything look like it was
        // loading at the same time.
        const prevActive = $('.console-item__badge.is-active', liveConsoleList);
        if (prevActive) {
            prevActive.classList.remove('is-active');
            prevActive.classList.add('is-success');
            prevActive.innerHTML = '<i class="ph-bold ph-check"></i>';
        }

        // Translate the raw backend text into a short, plain-English line
        // with an accurate per-message status (not just the coarse step status).
        const fallbackStatus = rawStatus === 'error' ? 'error' : (rawStatus === 'done' ? 'success' : 'active');
        const translated = translateLogLine(rawText) || { status: fallbackStatus, text: rawText };
        const badge = BADGE_MAP[translated.status] || BADGE_MAP.info;

        const item = document.createElement('div');
        item.className = 'console-item';
        item.innerHTML = `
            <div class="console-item__badge ${badge.cls}"><i class="${badge.icon}"></i></div>
            <div class="console-item__body">
                <p class="console-item__text"></p>
                <p class="console-item__time"></p>
            </div>
        `;
        $('.console-item__text', item).textContent = translated.text;
        $('.console-item__time', item).textContent = formatClock();
        liveConsoleList.appendChild(item);
        liveConsoleList.scrollTop = liveConsoleList.scrollHeight;
    }

    function formatClock() {
        const d = new Date();
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    }

    /* ═══════════════════════════════════════════════
       5. TIMER
       ═══════════════════════════════════════════════ */
    function startTimer() {
        startTime = Date.now();
        timerElapsed.textContent = '00:00';
        timerEstimate.textContent = `~${TOTAL_EST} seconds remaining`;
        timerInterval = setInterval(() => {
            const elapsed = Math.floor((Date.now() - startTime) / 1000);
            timerElapsed.textContent = formatTime(elapsed);
        }, 1000);
    }

    function stopTimer() {
        if (timerInterval) clearInterval(timerInterval);
        timerInterval = null;
        timerEstimate.textContent = 'Done!';
    }

    function updateEstimate(currentStep, status) {
        if (!startTime) return;
        // Sum remaining step estimates
        let remaining = 0;
        const startFrom = status === 'done' ? currentStep + 1 : currentStep;
        for (let i = startFrom; i <= 5; i++) {
            remaining += STEP_EST[i] || 5;
        }
        // If the current step is active, add ~half its estimate
        if (status === 'active') {
            remaining += Math.ceil((STEP_EST[currentStep] || 5) / 2);
        }

        if (remaining > 0) {
            timerEstimate.textContent = `~${remaining} seconds remaining`;
        } else {
            timerEstimate.textContent = 'Finishing up…';
        }
    }

    function formatTime(sec) {
        const m = String(Math.floor(sec / 60)).padStart(2, '0');
        const s = String(sec % 60).padStart(2, '0');
        return `${m}:${s}`;
    }

    /* ═══════════════════════════════════════════════
       6. RESULTS
       ═══════════════════════════════════════════════ */
    function showResults(report) {
        const r = report || {};

        // ── Stats ──
        $('#statTotal').textContent        = r.total_zones    ?? 0;
        $('#statCreated').textContent      = r.created        ?? 0;
        $('#statUpdated').textContent      = r.updated        ?? 0;
        $('#statUpdatedAreas').textContent = r.updated_areas  ?? 0;
        $('#statMoved').textContent        = r.moved          ?? 0;
        $('#statTotalAreas').textContent   = r.total_areas    ?? 0;
        $('#statSkipped').textContent      = r.skipped        ?? 0;
        $('#statFailed').textContent       = r.failed         ?? 0;
        statsGrid.style.display = '';

        // ── Success header ── (city_label shown if available, else generic message)
        resultHero.classList.remove('result-hero--error');
        resultTitle.textContent = 'Sync Complete!';
        resultSub.textContent = r.city_label
            ? `${r.city_label} branch processed successfully.`
            : 'All delivery zones have been processed successfully.';

        // Re-trigger SVG animation by cloning
        refreshCheckmarkAnimation();

        // ── Missing areas ──
        const missing = r.missing_areas || r.unresolved_areas || [];
        if (missing.length) {
            missingCard.style.display = '';
            if (missingCountBadge) missingCountBadge.textContent = `${missing.length} area${missing.length !== 1 ? 's' : ''}`;
            if (missingZonesCtr) {
                missingZonesCtr.innerHTML = '';
                // Group by zone prefix if format is "[ZoneName] AreaName"
                const grouped = {};
                missing.forEach(area => {
                    const raw = typeof area === 'string' ? area : (area.name || JSON.stringify(area));
                    const m = raw.match(/^\[(.+?)\] (.+)$/);
                    const zone = m ? m[1] : 'Unresolved';
                    const name = m ? m[2] : raw;
                    if (!grouped[zone]) grouped[zone] = [];
                    grouped[zone].push(name);
                });
                Object.entries(grouped).forEach(([zone, areas]) => {
                    const group = document.createElement('div');
                    group.className = 'missing-zone-group';
                    group.innerHTML = `<p class="missing-zone-label">${zone}</p>`;
                    const ul = document.createElement('ul');
                    ul.className = 'missing-area-list';
                    areas.forEach(areaName => {
                        const li = document.createElement('li');
                        li.textContent = areaName;
                        ul.appendChild(li);
                    });
                    group.appendChild(ul);
                    missingZonesCtr.appendChild(group);
                });
            }
        } else {
            missingCard.style.display = 'none';
        }

        // ── Copy All button ──
        const btnCopyMissing = $('#btnCopyMissing');
        if (btnCopyMissing) {
            btnCopyMissing.onclick = () => {
                const text = missing.map(a => typeof a === 'string' ? a : (a.name || '')).join('\n');
                navigator.clipboard.writeText(text).then(() => {
                    btnCopyMissing.textContent = '✓ Copied!';
                    setTimeout(() => { btnCopyMissing.innerHTML = '<i class="ph-bold ph-copy"></i> Copy All'; }, 2000);
                });
            };
        }

        // ── Logs → Operation Timeline ──
        renderLogsTimeline(r.logs || r.action_logs || []);

        switchPhase('results');
    }

    function renderLogsTimeline(logs) {
        logsContent.innerHTML = '';

        let rawLines = [];
        if (Array.isArray(logs)) rawLines = logs;
        else if (typeof logs === 'string' && logs.trim()) rawLines = logs.split('\n').filter(Boolean);

        // Some backend log entries contain embedded newlines (phase headers,
        // the old summary block) — flatten those out first.
        const flat = rawLines.flatMap(l => String(l).split('\n'));

        // Translate to plain English + drop decorative/redundant lines
        // (the raw numeric summary is skipped since those numbers now
        // live in the stat cards above).
        const entries = flat
            .map(translateLogLine)
            .filter(Boolean);

        if (!entries.length) {
            logsContent.innerHTML = '<p class="logs-empty">No logs available.</p>';
            return;
        }

        const dotIcon = { success: 'ph-bold ph-check', error: 'ph-bold ph-x', warn: 'ph-bold ph-warning', info: 'ph-bold ph-info', active: 'ph-bold ph-check' };
        const dotCls  = { success: 'is-success', error: 'is-error', warn: 'is-warn', info: 'is-info', active: 'is-success' };

        const timeline = document.createElement('div');
        timeline.className = 'timeline';

        entries.forEach((entry, idx) => {
            const cls  = dotCls[entry.status] || 'is-info';
            const icon = dotIcon[entry.status] || 'ph-bold ph-info';
            const item = document.createElement('div');
            item.className = 'timeline-item';
            item.innerHTML = `
                <div class="timeline-item__rail">
                    <div class="timeline-item__dot ${cls}"><i class="${icon}"></i></div>
                    ${idx < entries.length - 1 ? '<div class="timeline-item__line"></div>' : ''}
                </div>
                <div class="timeline-item__body">
                    <p class="timeline-item__text"></p>
                </div>
            `;
            $('.timeline-item__text', item).textContent = entry.text;
            timeline.appendChild(item);
        });

        logsContent.appendChild(timeline);
    }

    function showGlobalError(msg) {
        // Show results phase with error state
        resultHero.classList.add('result-hero--error');
        resultTitle.textContent = 'Processing Failed';
        resultSub.textContent = msg || 'An unexpected error occurred.';

        // Hide stats, missing
        statsGrid.style.display = 'none';
        missingCard.style.display = 'none';
        renderLogsTimeline([`✗ Error: ${msg || 'An unexpected error occurred.'}`]);

        refreshCheckmarkAnimation();
        switchPhase('results');
    }

    function refreshCheckmarkAnimation() {
        const oldSvg = $('.checkmark-svg', resultIcon);
        if (oldSvg) {
            const clone = oldSvg.cloneNode(true);
            oldSvg.parentNode.replaceChild(clone, oldSvg);
        }
    }

    /* ═══════════════════════════════════════════════
       7. RESET
       ═══════════════════════════════════════════════ */
    btnReset.addEventListener('click', () => {
        // Reset form
        form.reset();
        clearFile();
        btnSubmit.disabled = false;
        btnLabel.classList.remove('hidden');
        btnLoader.classList.add('hidden');

        // Reset stepper
        resetStepper();
        resetLiveConsole();

        // Reset results
        statsGrid.style.display = '';
        missingCard.style.display = 'none';
        missingCard.classList.remove('open');
        logsContent.innerHTML = '<p class="logs-empty">No logs available.</p>';

        // Go back
        switchPhase('form');
    });

    /* ═══════════════════════════════════════════════
       8. HELPERS
       ═══════════════════════════════════════════════ */
    function switchPhase(name) {
        [phaseForm, phaseProgress, phaseResults].forEach(el => el.classList.remove('phase--active'));
        if (name === 'form')     phaseForm.classList.add('phase--active');
        if (name === 'progress') phaseProgress.classList.add('phase--active');
        if (name === 'results')  phaseResults.classList.add('phase--active');
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    function showToast(msg) {
        errorToastMsg.textContent = msg;
        errorToast.classList.remove('hidden');
        setTimeout(() => errorToast.classList.add('hidden'), 5000);
    }

    closeToast.addEventListener('click', () => errorToast.classList.add('hidden'));

    // Collapsible missing-areas toggle
    toggleMissing.addEventListener('click', () => {
        missingCard.classList.toggle('open');
    });

})();