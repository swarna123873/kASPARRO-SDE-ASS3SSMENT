/**
 * AI Resume Screening System - Frontend Client
 * Phase 2: Multiple PDF Upload, Text Extraction & Verification
 */

// ============================================================================
// Configuration
// ============================================================================
const API_BASE_URL = 'http://127.0.0.1:8000';
const MAX_FILES_LIMIT = 50;
const MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024; // 10 MB

// ============================================================================
// DOM Elements - Health Check
// ============================================================================
const checkBtn = document.getElementById('check-connection-btn');
const btnSpinner = document.getElementById('btn-spinner');
const btnText = document.getElementById('btn-text');
const latencyDisplay = document.getElementById('latency-display');

const statusBadge = document.getElementById('status-badge');
const statusText = document.getElementById('status-text');

const feedbackBox = document.getElementById('connection-feedback');
const feedbackIcon = document.getElementById('feedback-icon');
const feedbackTitle = document.getElementById('feedback-title');
const feedbackMessage = document.getElementById('feedback-message');
const feedbackDetailsContainer = document.getElementById('feedback-details-container');
const feedbackRawJson = document.getElementById('feedback-raw-json');

// ============================================================================
// DOM Elements - Batch Upload & Results
// ============================================================================
const dropzone = document.getElementById('dropzone');
const pdfFileInput = document.getElementById('pdf-file-input');

const selectedFilesContainer = document.getElementById('selected-files-container');
const selectedFilesList = document.getElementById('selected-files-list');
const selectedCountText = document.getElementById('selected-count-text');
const clearFilesBtn = document.getElementById('clear-files-btn');

// Mode toggle buttons
const modeRankBtn = document.getElementById('mode-rank-btn');
const modeScreenBtn = document.getElementById('mode-screen-btn');

const uploadBtn = document.getElementById('upload-btn');
const uploadSpinner = document.getElementById('upload-spinner');
const uploadBtnText = document.getElementById('upload-btn-text');
const uploadStatusNote = document.getElementById('upload-status-note');

const uploadAlert = document.getElementById('upload-alert');
const uploadAlertTitle = document.getElementById('upload-alert-title');
const uploadAlertMessage = document.getElementById('upload-alert-message');

const resultsContainer = document.getElementById('results-container');
const clearResultsBtn = document.getElementById('clear-results-btn');
const summaryTotal = document.getElementById('summary-total');
const summarySuccess = document.getElementById('summary-success');
const summaryEligible = document.getElementById('summary-eligible');
const summaryIneligible = document.getElementById('summary-ineligible');
const summaryNoText = document.getElementById('summary-notext');
const summaryFailed = document.getElementById('summary-failed');
const perFileResultsList = document.getElementById('per-file-results-list');

// Phase 4: Ranked Report DOM elements
const rankedReportContainer = document.getElementById('ranked-report-container');
const reportStatsBar = document.getElementById('report-stats-bar');
const rankedCandidatesList = document.getElementById('ranked-candidates-list');
const rejectedSection = document.getElementById('rejected-section');
const rejectedCandidatesList = document.getElementById('rejected-candidates-list');
const failedSection = document.getElementById('failed-section');
const failedFilesList = document.getElementById('failed-files-list');
const duplicatesSection = document.getElementById('duplicates-section');
const duplicatesFilesList = document.getElementById('duplicates-files-list');
const clearRankedBtn = document.getElementById('clear-ranked-btn');

// State storage
let currentMode = 'rank'; // Default to Rank mode
let currentSelectedFiles = [];

// ============================================================================
// Health Check Functions (Preserved from Phase 1)
// ============================================================================

function setHealthLoadingState(isLoading) {
    if (isLoading) {
        checkBtn.disabled = true;
        btnSpinner.classList.remove('hidden');
        btnText.textContent = 'Connecting...';

        statusBadge.className = 'status-badge status-checking';
        statusText.textContent = 'Checking...';

        latencyDisplay.classList.add('hidden');
        feedbackBox.classList.add('hidden');
    } else {
        checkBtn.disabled = false;
        btnSpinner.classList.add('hidden');
        btnText.textContent = 'Check Backend Connection';
    }
}

function renderHealthSuccess(data, latencyMs) {
    statusBadge.className = 'status-badge status-connected';
    statusText.textContent = 'Connected';

    latencyDisplay.textContent = `Latency: ${latencyMs}ms`;
    latencyDisplay.classList.remove('hidden');

    feedbackBox.className = 'feedback-box success';
    feedbackIcon.textContent = '✓';
    feedbackTitle.textContent = 'Backend Connection Successful';
    feedbackMessage.textContent = `Successfully reached ${API_BASE_URL}/health. FastAPI server is live and responsive.`;

    feedbackRawJson.textContent = JSON.stringify(data, null, 2);
    feedbackDetailsContainer.classList.remove('hidden');
    feedbackBox.classList.remove('hidden');
}

function renderHealthError(errorMessage) {
    statusBadge.className = 'status-badge status-error';
    statusText.textContent = 'Disconnected';

    latencyDisplay.classList.add('hidden');

    feedbackBox.className = 'feedback-box error';
    feedbackIcon.textContent = '✗';
    feedbackTitle.textContent = 'Unable to Connect to Backend';
    feedbackMessage.textContent = `${errorMessage} Ensure the FastAPI server is running at ${API_BASE_URL} (e.g., via 'uvicorn backend.main:app --reload').`;

    feedbackDetailsContainer.classList.add('hidden');
    feedbackBox.classList.remove('hidden');
}

async function checkBackendHealth() {
    setHealthLoadingState(true);
    const startTime = performance.now();

    try {
        const response = await fetch(`${API_BASE_URL}/health`, {
            method: 'GET',
            headers: { 'Accept': 'application/json' },
        });

        const latencyMs = Math.round(performance.now() - startTime);

        if (!response.ok) {
            throw new Error(`Server returned HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();
        if (data.status === 'ok') {
            renderHealthSuccess(data, latencyMs);
        } else {
            renderHealthError(`Backend returned unexpected payload: ${JSON.stringify(data)}`);
        }
    } catch (err) {
        console.error('Backend health check error:', err);
        const reason = err instanceof TypeError
            ? 'Network request failed (server unreachable or CORS blocked).'
            : err.message;
        renderHealthError(reason);
    } finally {
        setHealthLoadingState(false);
    }
}

// ============================================================================
// File Selection & Drag-and-Drop Management
// ============================================================================

function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function updateSelectedFilesUI() {
    selectedFilesList.textContent = ''; // clear

    if (currentSelectedFiles.length === 0) {
        selectedFilesContainer.classList.add('hidden');
        uploadBtn.disabled = true;
        uploadBtnText.textContent = currentMode === 'rank' ? 'Screen & Rank Resumes' : 'Screen Resumes (Eligibility Only)';
        uploadStatusNote.textContent = 'Select one or more PDF files to begin';
        return;
    }

    selectedFilesContainer.classList.remove('hidden');
    uploadBtn.disabled = false;
    uploadBtnText.textContent = currentMode === 'rank' ? 'Screen & Rank Resumes' : 'Screen Resumes (Eligibility Only)';

    const totalBytes = currentSelectedFiles.reduce((acc, f) => acc + f.size, 0);
    selectedCountText.textContent = `${currentSelectedFiles.length} file(s) selected (${formatBytes(totalBytes)})`;
    uploadStatusNote.textContent = `Ready to process ${currentSelectedFiles.length} file(s)`;

    currentSelectedFiles.forEach((file, index) => {
        const li = document.createElement('li');
        li.className = 'selected-file-item';

        const nameSpan = document.createElement('span');
        nameSpan.className = 'selected-file-name';
        nameSpan.textContent = `📄 ${file.name}`;

        const sizeSpan = document.createElement('span');
        sizeSpan.className = 'selected-file-size';
        sizeSpan.textContent = `(${formatBytes(file.size)})`;
        nameSpan.appendChild(sizeSpan);

        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'btn-remove-file';
        removeBtn.textContent = '✕';
        removeBtn.title = 'Remove file';
        removeBtn.setAttribute('aria-label', `Remove ${file.name}`);
        removeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            currentSelectedFiles.splice(index, 1);
            updateSelectedFilesUI();
        });

        li.appendChild(nameSpan);
        li.appendChild(removeBtn);
        selectedFilesList.appendChild(li);
    });
}

function addFilesToSelection(newFiles) {
    uploadAlert.classList.add('hidden');
    const existingNames = new Set(currentSelectedFiles.map(f => f.name));
    let addedCount = 0;

    for (const file of newFiles) {
        if (currentSelectedFiles.length >= MAX_FILES_LIMIT) {
            showUploadError('Batch Limit Reached', `Maximum of ${MAX_FILES_LIMIT} files allowed per batch.`);
            break;
        }

        if (existingNames.has(file.name)) {
            continue; // Skip duplicates
        }

        // Basic client extension validation warning
        if (!file.name.toLowerCase().endsWith('.pdf')) {
            showUploadError('Invalid File Type', `File "${file.name}" is not a PDF.`);
        }

        currentSelectedFiles.push(file);
        existingNames.add(file.name);
        addedCount++;
    }

    updateSelectedFilesUI();
}

function clearSelection() {
    currentSelectedFiles = [];
    pdfFileInput.value = '';
    updateSelectedFilesUI();
    uploadAlert.classList.add('hidden');
}

// Drag & drop handlers
if (dropzone) {
    dropzone.addEventListener('click', () => pdfFileInput.click());
    dropzone.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            pdfFileInput.click();
        }
    });

    ['dragenter', 'dragover'].forEach(eventName => {
        dropzone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.add('drag-over');
        });
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropzone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.remove('drag-over');
        });
    });

    dropzone.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        if (dt && dt.files && dt.files.length > 0) {
            addFilesToSelection(Array.from(dt.files));
        }
    });
}

if (pdfFileInput) {
    pdfFileInput.addEventListener('change', (e) => {
        if (e.target.files && e.target.files.length > 0) {
            addFilesToSelection(Array.from(e.target.files));
        }
    });
}

if (clearFilesBtn) {
    clearFilesBtn.addEventListener('click', clearSelection);
}

// ============================================================================
// Batch Upload & Text Extraction
// ============================================================================

function showUploadError(title, message) {
    uploadAlertTitle.textContent = title;
    uploadAlertMessage.textContent = message;
    uploadAlert.classList.remove('hidden');
}

function setMode(mode) {
    currentMode = mode;
    if (mode === 'rank') {
        if (modeRankBtn) {
            modeRankBtn.classList.add('mode-btn-active', 'btn-primary');
            modeRankBtn.classList.remove('btn-secondary');
        }
        if (modeScreenBtn) {
            modeScreenBtn.classList.remove('mode-btn-active', 'btn-primary');
            modeScreenBtn.classList.add('btn-secondary');
        }
        if (uploadBtnText && uploadSpinner.classList.contains('hidden')) {
            uploadBtnText.textContent = 'Screen & Rank Resumes';
        }
    } else {
        if (modeScreenBtn) {
            modeScreenBtn.classList.add('mode-btn-active', 'btn-primary');
            modeScreenBtn.classList.remove('btn-secondary');
        }
        if (modeRankBtn) {
            modeRankBtn.classList.remove('mode-btn-active', 'btn-primary');
            modeRankBtn.classList.add('btn-secondary');
        }
        if (uploadBtnText && uploadSpinner.classList.contains('hidden')) {
            uploadBtnText.textContent = 'Screen Resumes (Eligibility Only)';
        }
    }
}

function setUploadLoadingState(isLoading) {
    if (isLoading) {
        uploadBtn.disabled = true;
        if (modeRankBtn) modeRankBtn.disabled = true;
        if (modeScreenBtn) modeScreenBtn.disabled = true;
        clearFilesBtn.disabled = true;
        uploadSpinner.classList.remove('hidden');
        if (currentMode === 'rank') {
            uploadBtnText.textContent = 'Scoring & Ranking Candidates...';
            uploadStatusNote.textContent = 'Evaluating candidates, scoring rubric, enriching GitHub, and ranking...';
        } else {
            uploadBtnText.textContent = 'Extracting & Screening...';
            uploadStatusNote.textContent = 'Uploading files and parsing with PyMuPDF...';
        }
        uploadAlert.classList.add('hidden');
    } else {
        uploadBtn.disabled = currentSelectedFiles.length === 0;
        if (modeRankBtn) modeRankBtn.disabled = false;
        if (modeScreenBtn) modeScreenBtn.disabled = false;
        clearFilesBtn.disabled = false;
        uploadSpinner.classList.add('hidden');
        if (currentMode === 'rank') {
            uploadBtnText.textContent = 'Screen & Rank Resumes';
        } else {
            uploadBtnText.textContent = 'Screen Resumes (Eligibility Only)';
        }
        uploadStatusNote.textContent = currentSelectedFiles.length > 0
            ? `Ready to process ${currentSelectedFiles.length} file(s)`
            : 'Select one or more PDF files to begin';
    }
}

/**
 * Safely render batch extraction results into the DOM.
 * Treats all extracted text and filenames as plain text (no unescaped innerHTML).
 */
function renderExtractionResults(data) {
    resultsContainer.classList.remove('hidden');

    // Update summary counts
    summaryTotal.textContent = data.total_files || 0;
    summarySuccess.textContent = data.successful_files || 0;
    if (summaryEligible) summaryEligible.textContent = data.eligible_candidates || 0;
    if (summaryIneligible) summaryIneligible.textContent = data.ineligible_candidates || 0;
    summaryNoText.textContent = data.no_text_files || 0;
    summaryFailed.textContent = data.failed_files || 0;

    perFileResultsList.textContent = ''; // clear previous results

    if (!data.results || data.results.length === 0) {
        const emptyMsg = document.createElement('p');
        emptyMsg.textContent = 'No file results returned.';
        emptyMsg.className = 'status-note';
        perFileResultsList.appendChild(emptyMsg);
        return;
    }

    data.results.forEach((file) => {
        const card = document.createElement('div');
        card.className = `file-result-card card-${file.status}`;

        // Card Header
        const header = document.createElement('div');
        header.className = 'file-result-header';

        const titleDiv = document.createElement('div');
        titleDiv.className = 'file-result-title';
        titleDiv.textContent = `📄 ${file.filename}`;

        const badgesDiv = document.createElement('div');
        badgesDiv.className = 'file-meta-badges';

        if (file.page_count !== null && file.page_count !== undefined) {
            const pagePill = document.createElement('span');
            pagePill.className = 'meta-pill';
            pagePill.textContent = `${file.page_count} page${file.page_count === 1 ? '' : 's'}`;
            badgesDiv.appendChild(pagePill);
        }

        if (file.text_length > 0) {
            const charsPill = document.createElement('span');
            charsPill.className = 'meta-pill';
            charsPill.textContent = `${file.text_length.toLocaleString()} chars`;
            badgesDiv.appendChild(charsPill);
        }

        // Add Eligibility Pill if determined
        if (file.eligible === true) {
            const eligPill = document.createElement('span');
            eligPill.className = 'status-pill pill-success';
            eligPill.textContent = 'Eligible';
            badgesDiv.appendChild(eligPill);
        } else if (file.eligible === false) {
            const ineligPill = document.createElement('span');
            ineligPill.className = 'status-pill pill-failed';
            ineligPill.textContent = 'Ineligible';
            badgesDiv.appendChild(ineligPill);
        } else {
            const statusPill = document.createElement('span');
            statusPill.className = `status-pill pill-${file.status}`;
            statusPill.textContent = file.status === 'no_text' ? 'No Text' : file.status;
            badgesDiv.appendChild(statusPill);
        }

        header.appendChild(titleDiv);
        header.appendChild(badgesDiv);
        card.appendChild(header);

        // Error message if present
        if (file.error_message) {
            const errorBlock = document.createElement('div');
            errorBlock.className = 'file-error-text';
            errorBlock.textContent = file.error_message;
            card.appendChild(errorBlock);
        }

        // Phase 3: Structured Candidate Profile & Eligibility Block
        if (file.candidate_profile) {
            const profile = file.candidate_profile;
            const profileBlock = document.createElement('div');
            profileBlock.className = 'candidate-profile-block';

            // 1. Eligibility Banner
            if (file.eligible !== null && file.eligible !== undefined) {
                const eligBanner = document.createElement('div');
                eligBanner.className = `eligibility-banner banner-${file.eligible ? 'eligible' : 'ineligible'}`;
                eligBanner.textContent = file.eligible
                    ? '✓ Meets Hard Eligibility Rules (Python & AI/Agentic Evidence Verified)'
                    : '✗ Ineligible for SDE Intern Role';
                profileBlock.appendChild(eligBanner);

                // Rejection reasons callout if ineligible
                if (!file.eligible && file.rejection_reasons && file.rejection_reasons.length > 0) {
                    const rejBox = document.createElement('div');
                    rejBox.className = 'rejection-reasons-list';
                    file.rejection_reasons.forEach((reason) => {
                        const rejItem = document.createElement('div');
                        rejItem.className = 'rejection-item';
                        rejItem.textContent = `⚠ ${reason}`;
                        rejBox.appendChild(rejItem);
                    });
                    profileBlock.appendChild(rejBox);
                }
            }

            // 2. Profile Header (Name & Contact)
            const profileHeader = document.createElement('div');
            profileHeader.className = 'candidate-profile-header';

            const nameEl = document.createElement('div');
            nameEl.className = 'candidate-name';
            nameEl.textContent = `👤 ${profile.candidate_name || file.candidate_name || 'Candidate'}`;
            profileHeader.appendChild(nameEl);

            const contactBar = document.createElement('div');
            contactBar.className = 'candidate-contact-bar';

            if (profile.email) {
                const emailSpan = document.createElement('span');
                emailSpan.className = 'contact-item';
                emailSpan.textContent = `✉ ${profile.email}`;
                contactBar.appendChild(emailSpan);
            }

            if (profile.phone) {
                const phoneSpan = document.createElement('span');
                phoneSpan.className = 'contact-item';
                phoneSpan.textContent = `📞 ${profile.phone}`;
                contactBar.appendChild(phoneSpan);
            }

            if (profile.github_url) {
                const ghSpan = document.createElement('span');
                ghSpan.className = 'contact-item';
                const ghLink = document.createElement('a');
                ghLink.href = profile.github_url;
                ghLink.target = '_blank';
                ghLink.rel = 'noopener noreferrer';
                ghLink.textContent = `🔗 GitHub: ${profile.github_url.replace('https://github.com/', '')}`;
                ghSpan.appendChild(ghLink);
                contactBar.appendChild(ghSpan);
            }

            profileHeader.appendChild(contactBar);
            profileBlock.appendChild(profileHeader);

            // Education Section
            if (profile.education && profile.education.length > 0) {
                const eduSec = document.createElement('div');
                eduSec.className = 'candidate-section';
                const eduLabel = document.createElement('span');
                eduLabel.className = 'candidate-section-label';
                eduLabel.textContent = 'Education';
                eduSec.appendChild(eduLabel);

                const eduP = document.createElement('div');
                eduP.className = 'candidate-project-desc';
                eduP.textContent = profile.education.join(' • ');
                eduSec.appendChild(eduP);
                profileBlock.appendChild(eduSec);
            }

            // Skills & Technologies Section
            const hasLangs = profile.programming_languages && profile.programming_languages.length > 0;
            const hasSkills = profile.technical_skills && profile.technical_skills.length > 0;
            const hasAi = profile.frameworks_and_tools && profile.frameworks_and_tools.length > 0;

            if (hasLangs || hasSkills || hasAi) {
                const skillsSec = document.createElement('div');
                skillsSec.className = 'candidate-section';

                const skillsLabel = document.createElement('span');
                skillsLabel.className = 'candidate-section-label';
                skillsLabel.textContent = 'Skills & Technologies';
                skillsSec.appendChild(skillsLabel);

                const pillsGroup = document.createElement('div');
                pillsGroup.className = 'skills-pill-group';

                if (hasLangs) {
                    profile.programming_languages.forEach((lang) => {
                        const pill = document.createElement('span');
                        pill.className = 'skill-pill skill-lang';
                        pill.textContent = lang;
                        pillsGroup.appendChild(pill);
                    });
                }

                if (hasSkills) {
                    profile.technical_skills.forEach((skill) => {
                        const pill = document.createElement('span');
                        pill.className = 'skill-pill skill-tool';
                        pill.textContent = skill;
                        pillsGroup.appendChild(pill);
                    });
                }

                if (hasAi) {
                    profile.frameworks_and_tools.forEach((aiTool) => {
                        const pill = document.createElement('span');
                        pill.className = 'skill-pill skill-ai';
                        pill.textContent = aiTool;
                        pillsGroup.appendChild(pill);
                    });
                }

                skillsSec.appendChild(pillsGroup);
                profileBlock.appendChild(skillsSec);
            }

            // Extracted Projects Section
            if (profile.projects && profile.projects.length > 0) {
                const projSec = document.createElement('div');
                projSec.className = 'candidate-section';

                const projLabel = document.createElement('span');
                projLabel.className = 'candidate-section-label';
                projLabel.textContent = `Technical Projects (${profile.projects.length})`;
                projSec.appendChild(projLabel);

                const projList = document.createElement('div');
                projList.className = 'candidate-projects-list';

                profile.projects.forEach((proj) => {
                    const projItem = document.createElement('div');
                    projItem.className = 'candidate-project-item';

                    const projTitle = document.createElement('div');
                    projTitle.className = 'candidate-project-title';
                    projTitle.textContent = proj.name;
                    projItem.appendChild(projTitle);

                    if (proj.description) {
                        const projDesc = document.createElement('div');
                        projDesc.className = 'candidate-project-desc';
                        projDesc.textContent = proj.description;
                        projItem.appendChild(projDesc);
                    }

                    if (proj.technologies && proj.technologies.length > 0) {
                        const techPills = document.createElement('div');
                        techPills.className = 'skills-pill-group';
                        techPills.style.marginTop = '0.35rem';
                        proj.technologies.forEach((t) => {
                            const pill = document.createElement('span');
                            pill.className = 'skill-pill skill-tool';
                            pill.textContent = t;
                            techPills.appendChild(pill);
                        });
                        projItem.appendChild(techPills);
                    }

                    projList.appendChild(projItem);
                });

                projSec.appendChild(projList);
                profileBlock.appendChild(projSec);
            }

            // Evidence Citations (Python & AI/Agentic)
            const hasPyEv = file.python_evidence && file.python_evidence.length > 0;
            const hasAiEv = file.ai_evidence && file.ai_evidence.length > 0;

            if (hasPyEv || hasAiEv) {
                const evSec = document.createElement('div');
                evSec.className = 'candidate-section';

                const evLabel = document.createElement('span');
                evLabel.className = 'candidate-section-label';
                evLabel.textContent = 'Hard Eligibility Evidence Citations';
                evSec.appendChild(evLabel);

                const evGroup = document.createElement('div');
                evGroup.className = 'evidence-group';

                if (hasPyEv) {
                    file.python_evidence.forEach((cit) => {
                        const citDiv = document.createElement('div');
                        citDiv.className = 'evidence-item evidence-python';
                        citDiv.textContent = `🐍 Python Evidence: ${cit}`;
                        evGroup.appendChild(citDiv);
                    });
                }

                if (hasAiEv) {
                    file.ai_evidence.forEach((cit) => {
                        const citDiv = document.createElement('div');
                        citDiv.className = 'evidence-item evidence-ai';
                        citDiv.textContent = `🤖 AI/Agentic Evidence: ${cit}`;
                        evGroup.appendChild(citDiv);
                    });
                }

                evSec.appendChild(evGroup);
                profileBlock.appendChild(evSec);
            }

            // Warnings if any
            if (profile.extraction_warnings && profile.extraction_warnings.length > 0) {
                const warnDiv = document.createElement('div');
                warnDiv.className = 'candidate-warning-badge';
                warnDiv.textContent = `ℹ Note: ${profile.extraction_warnings.join(' ')}`;
                profileBlock.appendChild(warnDiv);
            }

            card.appendChild(profileBlock);
        }

        // Extracted Text Collapsible Viewer
        if (file.status === 'success' && file.extracted_text) {
            const toggleBtn = document.createElement('button');
            toggleBtn.type = 'button';
            toggleBtn.className = 'text-viewer-toggle';
            toggleBtn.textContent = 'View Extracted Text';

            const textBox = document.createElement('pre');
            textBox.className = 'text-content-box hidden';
            // Safely set textContent to prevent HTML injection
            textBox.textContent = file.extracted_text;

            toggleBtn.addEventListener('click', () => {
                const isHidden = textBox.classList.contains('hidden');
                if (isHidden) {
                    textBox.classList.remove('hidden');
                    toggleBtn.classList.add('open');
                    toggleBtn.textContent = 'Hide Extracted Text';
                } else {
                    textBox.classList.add('hidden');
                    toggleBtn.classList.remove('open');
                    toggleBtn.textContent = 'View Extracted Text';
                }
            });

            card.appendChild(toggleBtn);
            card.appendChild(textBox);
        }

        perFileResultsList.appendChild(card);
    });
}

// ============================================================================
// Phase 4: Ranked Candidate Report Rendering
// ============================================================================

function renderRankedReport(data) {
    if (!rankedReportContainer) return;
    rankedReportContainer.classList.remove('hidden');

    // 1. Batch Summary Stats Bar
    if (reportStatsBar) {
        reportStatsBar.textContent = '';
        const sum = data.batch_summary || {};

        const totalPill = document.createElement('span');
        totalPill.className = 'report-stat-pill';
        totalPill.textContent = `Total: ${sum.total_resumes || 0}`;
        reportStatsBar.appendChild(totalPill);

        const eligiblePill = document.createElement('span');
        eligiblePill.className = 'report-stat-pill pill-eligible';
        eligiblePill.textContent = `Eligible & Ranked: ${sum.eligible || 0}`;
        reportStatsBar.appendChild(eligiblePill);

        const rejectedPill = document.createElement('span');
        rejectedPill.className = 'report-stat-pill pill-ineligible';
        rejectedPill.textContent = `Rejected: ${sum.rejected || 0}`;
        reportStatsBar.appendChild(rejectedPill);

        if (sum.failed_or_unreadable > 0) {
            const failedPill = document.createElement('span');
            failedPill.className = 'report-stat-pill pill-failed';
            failedPill.textContent = `Failed: ${sum.failed_or_unreadable}`;
            reportStatsBar.appendChild(failedPill);
        }

        if (sum.duplicates > 0) {
            const dupPill = document.createElement('span');
            dupPill.className = 'report-stat-pill';
            dupPill.textContent = `Duplicates: ${sum.duplicates}`;
            reportStatsBar.appendChild(dupPill);
        }

        if (sum.average_score !== null && sum.average_score !== undefined) {
            const avgPill = document.createElement('span');
            avgPill.className = 'report-stat-pill pill-avg';
            avgPill.textContent = `Avg Score: ${Number(sum.average_score).toFixed(1)}/100`;
            reportStatsBar.appendChild(avgPill);
        }

        if (sum.highest_score !== null && sum.highest_score !== undefined) {
            const topPill = document.createElement('span');
            topPill.className = 'report-stat-pill pill-eligible';
            topPill.textContent = `Top Score: ${sum.highest_score}/100`;
            reportStatsBar.appendChild(topPill);
        }
    }

    // 2. Ranked Candidates Leaderboard
    if (rankedCandidatesList) {
        rankedCandidatesList.textContent = '';

        const candidates = data.ranked_eligible_candidates || [];
        if (candidates.length === 0) {
            const emptyNotice = document.createElement('div');
            emptyNotice.className = 'file-error-text';
            emptyNotice.style.padding = '1rem';
            emptyNotice.textContent = 'No candidates met the mandatory Python and AI/Agentic eligibility requirements in this batch.';
            rankedCandidatesList.appendChild(emptyNotice);
        } else {
            candidates.forEach((cand) => {
                const rankNum = cand.rank;
                const rankClass = rankNum === 1 ? 'rank-1' : (rankNum === 2 ? 'rank-2' : (rankNum === 3 ? 'rank-3' : ''));

                const card = document.createElement('div');
                card.className = `ranked-candidate-card ${rankClass}`.trim();

                // Top container
                const cardTop = document.createElement('div');
                cardTop.className = 'ranked-card-top';

                // Score Ring
                const totalScore = Math.max(0, Math.min(100, Math.round(cand.total_score || 0)));
                const scoreColor = totalScore >= 70 ? 'high' : (totalScore >= 40 ? 'mid' : 'low');
                const maxOffset = 201;
                const offset = Math.max(0, Math.round(maxOffset - (totalScore / 100) * maxOffset));

                const ringWrap = document.createElement('div');
                ringWrap.className = 'score-ring-wrap';

                const ringDiv = document.createElement('div');
                ringDiv.className = 'score-ring';
                ringDiv.innerHTML = `
                    <svg viewBox="0 0 72 72" width="80" height="80">
                        <circle class="score-ring-track" cx="36" cy="36" r="32"></circle>
                        <circle class="score-ring-fill ${scoreColor}" cx="36" cy="36" r="32"
                                style="stroke-dasharray: 201; stroke-dashoffset: ${offset};"></circle>
                    </svg>
                    <div class="score-ring-text">
                        <span>${totalScore}</span>
                        <small>/ 100</small>
                    </div>
                `;
                ringWrap.appendChild(ringDiv);

                const rankBadge = document.createElement('span');
                const badgeModifier = rankNum === 1 ? 'rank-1-badge' : (rankNum === 2 ? 'rank-2-badge' : (rankNum === 3 ? 'rank-3-badge' : ''));
                rankBadge.className = `rank-badge ${badgeModifier}`.trim();
                rankBadge.textContent = rankNum === 1 ? '🥇 Rank #1' : (rankNum === 2 ? '🥈 Rank #2' : (rankNum === 3 ? '🥉 Rank #3' : `Rank #${rankNum}`));
                ringWrap.appendChild(rankBadge);

                cardTop.appendChild(ringWrap);

                // Candidate Info
                const infoDiv = document.createElement('div');
                infoDiv.className = 'ranked-info';

                const nameDiv = document.createElement('div');
                nameDiv.className = 'ranked-name';
                nameDiv.textContent = `👤 ${cand.candidate_name || cand.filename}`;
                infoDiv.appendChild(nameDiv);

                const metaDiv = document.createElement('div');
                metaDiv.className = 'ranked-meta';

                const fileSpan = document.createElement('span');
                fileSpan.className = 'ranked-meta-item';
                fileSpan.textContent = `📄 ${cand.filename}`;
                metaDiv.appendChild(fileSpan);

                if (cand.email) {
                    const emailSpan = document.createElement('span');
                    emailSpan.className = 'ranked-meta-item';
                    emailSpan.textContent = `✉ ${cand.email}`;
                    metaDiv.appendChild(emailSpan);
                }

                if (cand.github_url) {
                    const ghSpan = document.createElement('span');
                    ghSpan.className = 'ranked-meta-item';
                    const ghLink = document.createElement('a');
                    ghLink.href = cand.github_url;
                    ghLink.target = '_blank';
                    ghLink.rel = 'noopener noreferrer';
                    ghLink.textContent = `🔗 GitHub: ${cand.github_url.replace('https://github.com/', '@')}`;
                    ghSpan.appendChild(ghLink);
                    metaDiv.appendChild(ghSpan);
                }

                infoDiv.appendChild(metaDiv);

                // Matched Skills
                if (cand.matched_skills && cand.matched_skills.length > 0) {
                    const skillsGroup = document.createElement('div');
                    skillsGroup.className = 'skills-pill-group';
                    skillsGroup.style.margin = '0.5rem 0';
                    cand.matched_skills.forEach((skill) => {
                        const pill = document.createElement('span');
                        pill.className = 'skill-pill skill-lang';
                        pill.textContent = skill;
                        skillsGroup.appendChild(pill);
                    });
                    infoDiv.appendChild(skillsGroup);
                }

                // Strengths & Concerns
                const hasStrengths = cand.strengths && cand.strengths.length > 0;
                const hasConcerns = cand.concerns && cand.concerns.length > 0;
                if (hasStrengths || hasConcerns) {
                    const badgesRow = document.createElement('div');
                    badgesRow.style.display = 'flex';
                    badgesRow.style.flexWrap = 'wrap';
                    badgesRow.style.gap = '0.4rem';
                    badgesRow.style.marginBottom = '0.5rem';

                    if (hasStrengths) {
                        cand.strengths.forEach((s) => {
                            const pill = document.createElement('span');
                            pill.className = 'status-pill pill-success';
                            pill.style.fontSize = '0.72rem';
                            pill.textContent = `✓ ${s}`;
                            badgesRow.appendChild(pill);
                        });
                    }

                    if (hasConcerns) {
                        cand.concerns.forEach((c) => {
                            const pill = document.createElement('span');
                            pill.className = 'status-pill pill-failed';
                            pill.style.fontSize = '0.72rem';
                            pill.textContent = `⚠ ${c}`;
                            badgesRow.appendChild(pill);
                        });
                    }

                    infoDiv.appendChild(badgesRow);
                }

                // Project Summaries
                const projectList = cand.project_summary || cand.project_summaries || [];
                if (projectList.length > 0) {
                    const projBox = document.createElement('div');
                    projBox.style.marginBottom = '0.5rem';
                    projectList.forEach((proj) => {
                        const projDesc = document.createElement('div');
                        projDesc.className = 'candidate-project-desc';
                        projDesc.style.fontSize = '0.8rem';
                        projDesc.style.marginTop = '0.2rem';
                        projDesc.textContent = `⚡ ${proj}`;
                        projBox.appendChild(projDesc);
                    });
                    infoDiv.appendChild(projBox);
                }

                // GitHub Enrichment
                if (cand.github_enrichment || cand.github_summary) {
                    const ghDiv = document.createElement('div');
                    ghDiv.className = 'github-enrichment';

                    const gh = cand.github_enrichment || {};
                    if (gh.status === 'success') {
                        if (gh.public_repos !== undefined && gh.public_repos !== null) {
                            const rSpan = document.createElement('span');
                            rSpan.className = 'github-stat';
                            rSpan.innerHTML = `Repos: <span class="gh-val">${gh.public_repos}</span>`;
                            ghDiv.appendChild(rSpan);
                        }
                        if (gh.followers !== undefined && gh.followers !== null) {
                            const fSpan = document.createElement('span');
                            fSpan.className = 'github-stat';
                            fSpan.innerHTML = `Followers: <span class="gh-val">${gh.followers}</span>`;
                            ghDiv.appendChild(fSpan);
                        }
                        const scoreSpan = document.createElement('span');
                        scoreSpan.className = 'github-stat';
                        scoreSpan.innerHTML = `GitHub Activity: <span class="gh-val">${gh.score || 0}/10 pts</span>`;
                        ghDiv.appendChild(scoreSpan);

                        if (gh.has_pinned_ai_project) {
                            const aiBadge = document.createElement('span');
                            aiBadge.className = 'github-ai-badge';
                            aiBadge.textContent = '★ AI Repos Detected';
                            ghDiv.appendChild(aiBadge);
                        }
                    } else if (cand.github_summary) {
                        const sumSpan = document.createElement('span');
                        sumSpan.className = 'github-stat';
                        sumSpan.textContent = cand.github_summary;
                        ghDiv.appendChild(sumSpan);
                    } else if (gh.status && gh.status !== 'no_github') {
                        const noData = document.createElement('span');
                        noData.className = 'github-no-data';
                        noData.textContent = `GitHub status: ${gh.status}${gh.error_message ? ' (' + gh.error_message + ')' : ''}`;
                        ghDiv.appendChild(noData);
                    }

                    if (ghDiv.children.length > 0) {
                        infoDiv.appendChild(ghDiv);
                    }
                }

                cardTop.appendChild(infoDiv);
                card.appendChild(cardTop);

                // Score Breakdown (100-Point Rubric)
                const sb = cand.score_breakdown || {};
                const breakdownDiv = document.createElement('div');
                breakdownDiv.className = 'score-breakdown';

                const bTitle = document.createElement('div');
                bTitle.className = 'score-breakdown-title';
                bTitle.textContent = 'Score Breakdown (100-Point Rubric)';
                breakdownDiv.appendChild(bTitle);

                const categories = [
                    { label: 'AI / Agentic / RAG Project Depth', key: 'ai_project_depth', max: 40, barClass: 'bar-ai' },
                    { label: 'Python & Backend Engineering', key: 'python_backend', max: 30, barClass: 'bar-python' },
                    { label: 'Cloud / Deployment / Full Stack', key: 'cloud_fullstack', max: 15, barClass: 'bar-deploy' },
                    { label: 'GitHub Activity', key: 'github', max: 10, barClass: 'bar-github' },
                    { label: 'Engineering Depth Signals', key: 'engineering_depth', max: 5, barClass: 'bar-fund' },
                ];

                categories.forEach((cat) => {
                    const pts = sb[cat.key] !== undefined ? sb[cat.key] : (cand[cat.key] || 0);
                    const pct = Math.min(100, Math.round((pts / cat.max) * 100));

                    const row = document.createElement('div');
                    row.className = 'score-bar-row';

                    const label = document.createElement('span');
                    label.className = 'score-bar-label';
                    label.textContent = cat.label;
                    label.title = cat.label;

                    const track = document.createElement('div');
                    track.className = 'score-bar-track';

                    const fill = document.createElement('div');
                    fill.className = `score-bar-fill ${cat.barClass}`;
                    fill.style.width = `${pct}%`;
                    track.appendChild(fill);

                    const ptsText = document.createElement('span');
                    ptsText.className = 'score-bar-pts';
                    ptsText.textContent = `${pts} / ${cat.max}`;

                    row.appendChild(label);
                    row.appendChild(track);
                    row.appendChild(ptsText);
                    breakdownDiv.appendChild(row);
                });

                // Quality Penalty Badge
                const penalty = cand.project_quality_penalty || sb.project_quality_penalty || 0;
                if (penalty > 0) {
                    const penaltyDiv = document.createElement('div');
                    penaltyDiv.className = 'penalty-badge';
                    const reasons = sb.project_quality_penalty_reasons || [];
                    penaltyDiv.textContent = `⚠ Project Quality Penalty: -${penalty} pts ${reasons.length > 0 ? '(' + reasons.join(', ') + ')' : ''}`;
                    breakdownDiv.appendChild(penaltyDiv);
                }

                card.appendChild(breakdownDiv);

                // Evidence Accordion
                const evidenceList = [];
                if (cand.score_evidence && cand.score_evidence.length > 0) {
                    cand.score_evidence.forEach((item) => {
                        const cName = item.category_name || item.category || 'Category';
                        if (item.evidence_citations && item.evidence_citations.length > 0) {
                            item.evidence_citations.forEach((cit) => {
                                evidenceList.push(`[${cName}] ${cit}`);
                            });
                        }
                    });
                }
                if (cand.python_evidence && cand.python_evidence.length > 0) {
                    cand.python_evidence.forEach((cit) => {
                        evidenceList.push(`[Python Evidence] ${cit}`);
                    });
                }
                if (cand.ai_evidence && cand.ai_evidence.length > 0) {
                    cand.ai_evidence.forEach((cit) => {
                        evidenceList.push(`[AI / Agentic Evidence] ${cit}`);
                    });
                }

                if (evidenceList.length > 0) {
                    const accDiv = document.createElement('div');
                    accDiv.className = 'evidence-accordion';

                    const details = document.createElement('details');
                    const summary = document.createElement('summary');
                    summary.textContent = `🔎 View Scoring Evidence & Citations (${evidenceList.length})`;
                    details.appendChild(summary);

                    const ul = document.createElement('ul');
                    ul.className = 'evidence-list';
                    evidenceList.forEach((evText) => {
                        const li = document.createElement('li');
                        li.textContent = evText;
                        ul.appendChild(li);
                    });
                    details.appendChild(ul);
                    accDiv.appendChild(details);
                    card.appendChild(accDiv);
                }

                rankedCandidatesList.appendChild(card);
            });
        }
    }

    // 3. Rejected Candidates
    if (rejectedSection && rejectedCandidatesList) {
        const rejected = data.rejected_candidates || [];
        if (rejected.length > 0) {
            rejectedSection.classList.remove('hidden');
            rejectedCandidatesList.textContent = '';
            rejected.forEach((rej) => {
                const rejCard = document.createElement('div');
                rejCard.className = 'rejected-candidate-card';

                const nameEl = document.createElement('div');
                nameEl.className = 'rejected-name';
                nameEl.textContent = `👤 ${rej.candidate_name || rej.filename} (📄 ${rej.filename})`;
                rejCard.appendChild(nameEl);

                if (rej.rejection_reasons && rej.rejection_reasons.length > 0) {
                    const ul = document.createElement('ul');
                    ul.className = 'rejected-reasons';
                    rej.rejection_reasons.forEach((r) => {
                        const li = document.createElement('li');
                        li.textContent = r;
                        ul.appendChild(li);
                    });
                    rejCard.appendChild(ul);
                }
                rejectedCandidatesList.appendChild(rejCard);
            });
        } else {
            rejectedSection.classList.add('hidden');
        }
    }

    // 4. Failed Resumes
    if (failedSection && failedFilesList) {
        const failed = data.failed_resumes || [];
        if (failed.length > 0) {
            failedSection.classList.remove('hidden');
            failedFilesList.textContent = '';
            failed.forEach((f) => {
                const fCard = document.createElement('div');
                fCard.className = 'failed-file-card';

                const nameEl = document.createElement('span');
                nameEl.className = 'failed-file-name';
                nameEl.textContent = `📄 ${f.filename}`;
                fCard.appendChild(nameEl);

                const reasonEl = document.createElement('span');
                reasonEl.className = 'failed-file-reason';
                reasonEl.textContent = f.error_message || f.failure_stage || f.status || 'Failed to parse';
                fCard.appendChild(reasonEl);

                failedFilesList.appendChild(fCard);
            });
        } else {
            failedSection.classList.add('hidden');
        }
    }

    // 5. Duplicates
    if (duplicatesSection && duplicatesFilesList) {
        const dups = data.duplicates || [];
        if (dups.length > 0) {
            duplicatesSection.classList.remove('hidden');
            duplicatesFilesList.textContent = '';
            dups.forEach((d) => {
                const dCard = document.createElement('div');
                dCard.className = 'failed-file-card';
                dCard.innerHTML = `<span class="failed-file-name">📄 ${d.filename}</span><span class="failed-file-reason">Identical byte duplicate of <strong>${d.original_filename}</strong> (SHA-256 matched, quarantined)</span>`;
                duplicatesFilesList.appendChild(dCard);
            });
        } else {
            duplicatesSection.classList.add('hidden');
        }
    }
}

// ============================================================================
// Batch Upload Action Handler
// ============================================================================

async function handleBatchUpload() {
    if (currentSelectedFiles.length === 0) {
        showUploadError('No Files Selected', 'Please select at least one PDF resume to upload.');
        return;
    }

    setUploadLoadingState(true);
    const formData = new FormData();

    // Append files under field name 'files' expected by FastAPI
    currentSelectedFiles.forEach((file) => {
        formData.append('files', file);
    });

    const endpoint = currentMode === 'rank' ? `${API_BASE_URL}/report` : `${API_BASE_URL}/screen`;

    try {
        const response = await fetch(endpoint, {
            method: 'POST',
            body: formData,
        });

        if (!response.ok) {
            let errorDetail = `HTTP ${response.status}: ${response.statusText}`;
            try {
                const errorJson = await response.json();
                if (errorJson.detail) {
                    errorDetail = typeof errorJson.detail === 'string'
                        ? errorJson.detail
                        : JSON.stringify(errorJson.detail);
                }
            } catch (_) { }
            throw new Error(errorDetail);
        }

        const data = await response.json();

        if (currentMode === 'rank') {
            if (resultsContainer) resultsContainer.classList.add('hidden');
            renderRankedReport(data);
            if (rankedReportContainer) {
                rankedReportContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        } else {
            if (rankedReportContainer) rankedReportContainer.classList.add('hidden');
            renderExtractionResults(data);
            if (resultsContainer) {
                resultsContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        }

    } catch (err) {
        console.error('Batch upload error:', err);
        const reason = err instanceof TypeError
            ? 'Network error: could not connect to FastAPI server. Ensure backend is running.'
            : err.message;
        showUploadError(currentMode === 'rank' ? 'Ranking Failed' : 'Screening Failed', reason);
    } finally {
        setUploadLoadingState(false);
    }
}

// ============================================================================
// Event Listeners
// ============================================================================

if (uploadBtn) {
    uploadBtn.addEventListener('click', handleBatchUpload);
}

if (modeRankBtn) {
    modeRankBtn.addEventListener('click', () => {
        setMode('rank');
        if (currentSelectedFiles.length > 0) {
            handleBatchUpload();
        } else {
            pdfFileInput.click();
        }
    });
}

if (modeScreenBtn) {
    modeScreenBtn.addEventListener('click', () => {
        setMode('screen');
        if (currentSelectedFiles.length > 0) {
            handleBatchUpload();
        } else {
            pdfFileInput.click();
        }
    });
}

if (clearResultsBtn) {
    clearResultsBtn.addEventListener('click', () => {
        resultsContainer.classList.add('hidden');
        perFileResultsList.textContent = '';
    });
}

if (clearRankedBtn) {
    clearRankedBtn.addEventListener('click', () => {
        if (rankedReportContainer) rankedReportContainer.classList.add('hidden');
        if (rankedCandidatesList) rankedCandidatesList.textContent = '';
        if (rejectedCandidatesList) rejectedCandidatesList.textContent = '';
        if (failedFilesList) failedFilesList.textContent = '';
        if (duplicatesFilesList) duplicatesFilesList.textContent = '';
    });
}

// Health Check
if (checkBtn) {
    checkBtn.addEventListener('click', checkBackendHealth);
}
