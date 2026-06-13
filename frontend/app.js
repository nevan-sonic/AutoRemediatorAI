// Configuration
const API_BASE_URL = ""; // Relative path to API

// Global State
let incidents = [];
let selectedIncidentId = null;
let healthPollInterval = null;
let incidentPollInterval = null;

// Clock updates
function updateUTCClock() {
    const clock = document.getElementById("utc-clock");
    if (clock) {
        const now = new Date();
        clock.textContent = now.toISOString().split("T")[1].slice(0, 8) + " UTC";
    }
}
setInterval(updateUTCClock, 1000);

// Helper for status badge class
function getStatusBadgeClass(status) {
    switch(status) {
        case "OPEN":
        case "EXECUTION_IN_PROGRESS":
            return "badge-open";
        case "PENDING_APPROVAL":
            return "badge-pending";
        case "RESOLVED":
            return "badge-resolved";
        case "FAILED":
        case "TIMEOUT":
            return "badge-failed";
        case "BLOCKED":
            return "badge-blocked";
        default:
            return "badge-blocked";
    }
}

// Fetch System metrics (/agent-health)
async function loadAgentHealth() {
    try {
        const response = await fetch(`${API_BASE_URL}/agent-health`);
        if (!response.ok) throw new Error("Agent health response not ok");
        const data = await response.json();

        // Update Gauge ring (stroke-dashoffset range is 439.8 for full circle to 0)
        const healthScore = parseFloat(data.health_score || 0).toFixed(1);
        const dashOffset = 439.8 - (439.8 * parseFloat(healthScore)) / 100;
        
        const ring = document.getElementById("health-ring");
        const valText = document.getElementById("health-value");
        if (ring) ring.style.strokeDashoffset = dashOffset;
        if (valText) valText.textContent = healthScore;

        // Color coding ring based on health score
        if (ring) {
            if (healthScore >= 85) ring.style.stroke = "var(--color-green)";
            else if (healthScore >= 60) ring.style.stroke = "var(--color-amber)";
            else ring.style.stroke = "var(--color-rose)";
        }

        // Sidebar and stats list
        document.getElementById("sys-health").textContent = `${healthScore}%`;
        document.getElementById("sys-autonomy").textContent = data.autonomy_level || "UNKNOWN";
        document.getElementById("sys-decisions").textContent = data.total_decisions || 0;

        document.getElementById("stat-success").textContent = `${((data.success_rate || 0) * 100).toFixed(0)}%`;
        document.getElementById("stat-confidence").textContent = `${((data.avg_confidence || 0) * 100).toFixed(0)}%`;
        document.getElementById("stat-drift").textContent = data.drift_score ? data.drift_score.toFixed(3) : "0.000";
        document.getElementById("stat-decisions").textContent = data.total_decisions || 0;
    } catch(e) {
        console.error("Failed to load agent health stats:", e);
    }
}

// Fetch all incidents
async function loadIncidents() {
    try {
        const response = await fetch(`${API_BASE_URL}/incidents`);
        if (!response.ok) throw new Error("Incidents list response not ok");
        incidents = await response.json();

        const container = document.getElementById("incidents-container");
        if (!container) return;

        if (incidents.length === 0) {
            container.innerHTML = `<div class="text-center py-12 text-zinc-500 font-mono text-xs">NO_ACTIVE_INCIDENTS_LOGGED</div>`;
            return;
        }

        container.innerHTML = "";
        incidents.forEach(inc => {
            const card = document.createElement("div");
            card.className = `incident-card font-mono text-xs ${selectedIncidentId === inc.id ? "selected" : ""}`;
            card.onclick = () => selectIncident(inc.id);

            const badgeClass = getStatusBadgeClass(inc.status);
            const relativeTime = new Date(inc.created_at).toLocaleTimeString();

            card.innerHTML = `
                <div class="flex flex-col gap-1">
                    <span class="text-zinc-400 font-bold">${inc.service}</span>
                    <span class="text-[10px] text-zinc-500 uppercase">${inc.issue_type} | ${relativeTime}</span>
                </div>
                <span class="badge ${badgeClass}">${inc.status}</span>
            `;
            container.appendChild(card);
        });

        // Refresh details if the currently viewed incident has updated state
        if (selectedIncidentId) {
            const currentSelected = incidents.find(i => i.id === selectedIncidentId);
            if (currentSelected) {
                renderIncidentDetails(currentSelected);
            }
        }
    } catch(e) {
        console.error("Failed to poll incidents feed:", e);
    }
}

// Inspect details of specific incident
async function selectIncident(id) {
    selectedIncidentId = id;
    
    // Rerender incident list to highlight selection
    const cards = document.querySelectorAll(".incident-card");
    cards.forEach(card => card.classList.remove("selected"));
    
    // Poll database for individual document details
    try {
        const response = await fetch(`${API_BASE_URL}/incidents/${id}`);
        if (!response.ok) throw new Error("Incident detail response not ok");
        const incident = await response.json();
        
        renderIncidentDetails(incident);
        
        // Auto scroll details panel into view
        document.getElementById("details-section").scrollIntoView({ behavior: 'smooth' });
    } catch(e) {
        console.error(`Failed to fetch incident detail for ${id}:`, e);
    }
}

// Render incident details on screen
function renderIncidentDetails(incident) {
    document.getElementById("details-empty").classList.add("hidden");
    document.getElementById("details-content").classList.remove("hidden");

    // Head details
    document.getElementById("det-service").textContent = incident.service;
    document.getElementById("det-id").textContent = `UUID: ${incident.id}`;
    document.getElementById("det-issue-type").textContent = incident.issue_type;

    const badge = document.getElementById("det-status-badge");
    badge.className = `badge font-mono text-xs uppercase ${getStatusBadgeClass(incident.status)}`;
    badge.textContent = incident.status;

    // 4 Subagents mock details
    // Logs (canned or populated)
    const sublogs = document.getElementById("subagent-logs");
    if (incident.root_cause && incident.root_cause !== "Unknown anomaly") {
        sublogs.textContent = `Root patterns identified: ${incident.root_cause}`;
    } else {
        sublogs.textContent = "Logs empty. Telemetry fallback active.";
    }

    // Traces
    const subtraces = document.getElementById("subagent-traces");
    subtraces.textContent = incident.evidence && incident.evidence.length > 0 
        ? incident.evidence.join("\n") 
        : "No tracing bottlenecks found. Empty Jaeger traces.";

    // Deploy
    const subdeploy = document.getElementById("subagent-deploy");
    subdeploy.textContent = incident.issue_type === "high_latency" 
        ? "Correlating container limits. Zero deployments in last 2h."
        : "Healthy container boundaries. No restarts detected.";

    // Memory
    const submem = document.getElementById("subagent-memory");
    submem.textContent = incident.memory_match_used
        ? "Active match found (confidence > 90%). Reused rollback action."
        : "No similar incident database fingerprints match. Empty memory.";

    // Reasoning Chain
    const reasoningContainer = document.getElementById("det-reasoning");
    reasoningContainer.innerHTML = "";
    if (incident.reasoning_chain && incident.reasoning_chain.length > 0) {
        incident.reasoning_chain.forEach(r => {
            const li = document.createElement("li");
            li.textContent = r;
            reasoningContainer.appendChild(li);
        });
    } else {
        reasoningContainer.innerHTML = `<li>No active swarm reasoning logs available.</li>`;
    }

    // Decisions card
    document.getElementById("det-root-cause").textContent = incident.root_cause || "UNKNOWN";
    document.getElementById("det-confidence").textContent = incident.confidence ? `${(incident.confidence * 100).toFixed(0)}%` : "0%";

    const action = incident.recommended_action || incident.action || "NONE";
    document.getElementById("det-action").textContent = action;
    document.getElementById("det-rationale").textContent = incident.rationale || "No remediation action proposed.";
    document.getElementById("det-blast").textContent = incident.blast_radius || "-";
    document.getElementById("det-memory-reused").textContent = incident.memory_match_used ? "TRUE" : "FALSE";

    // Safety Gate Card
    document.getElementById("det-zone").textContent = incident.zone || "BLACK";
    document.getElementById("det-safety-status").textContent = incident.approved ? "APPROVED" : (incident.blocked ? "BLOCKED" : "GATED");
    
    // Safety details colors
    const zoneText = document.getElementById("det-zone");
    if (incident.zone === "GREEN") zoneText.style.color = "var(--color-green)";
    else if (incident.zone?.startsWith("YELLOW")) zoneText.style.color = "var(--color-amber)";
    else zoneText.style.color = "var(--color-rose)";

    // Block reason handling
    const blockContainer = document.getElementById("det-block-reason-container");
    const blockSpan = document.getElementById("det-block-reason");
    if (incident.blocked && incident.block_reason) {
        blockContainer.classList.remove("hidden");
        blockSpan.textContent = incident.block_reason;
    } else {
        blockContainer.classList.add("hidden");
    }

    // Approval Panel handling
    const appPanel = document.getElementById("approval-panel");
    if (incident.status === "PENDING_APPROVAL") {
        appPanel.classList.remove("hidden");
    } else {
        appPanel.classList.add("hidden");
    }

    // RCA Postmortem Panel handling
    const rcaPanel = document.getElementById("rca-panel");
    const genRcaBtn = document.getElementById("gen-rca-btn");
    const rcaContent = document.getElementById("rca-content");

    if (incident.status === "RESOLVED") {
        rcaPanel.classList.remove("hidden");
        if (incident.rca) {
            renderRcaReport(incident.rca);
        } else {
            rcaContent.classList.add("hidden");
            genRcaBtn.classList.remove("hidden");
        }
    } else {
        rcaPanel.classList.add("hidden");
    }
}

// Render postmortem RCA view card
function renderRcaReport(rca) {
    document.getElementById("gen-rca-btn").classList.add("hidden");
    const content = document.getElementById("rca-content");
    content.classList.remove("hidden");

    document.getElementById("rca-summary").textContent = rca.summary;
    document.getElementById("rca-analysis").textContent = rca.root_cause_analysis;
    document.getElementById("rca-resolution").textContent = rca.resolution_taken;

    const list = document.getElementById("rca-prevention");
    list.innerHTML = "";
    if (rca.prevention_recommendations) {
        rca.prevention_recommendations.forEach(rec => {
            const li = document.createElement("li");
            li.textContent = rec;
            list.appendChild(li);
        });
    }
}

// Inject failure anomaly
async function injectFailure() {
    const service = document.getElementById("inject-service").value;
    const type = document.getElementById("inject-type").value;
    const btn = document.getElementById("inject-btn");
    const statusText = document.getElementById("inject-status");

    btn.disabled = true;
    statusText.classList.remove("hidden");
    statusText.style.color = "var(--terminal-muted)";
    statusText.textContent = "TRANSMITTING_INJECT_COMMAND...";

    try {
        const response = await fetch(`${API_BASE_URL}/inject`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ service: service, issue_type: type })
        });

        if (response.status === 429) {
            statusText.style.color = "var(--color-rose)";
            statusText.textContent = "TRANSMISSION_ERROR: RATE_LIMIT_ACTIVE";
        } else if (response.ok) {
            const data = await response.json();
            statusText.style.color = "var(--color-green)";
            statusText.textContent = `PIPELINE_STARTED: inc-${data.incident_id.slice(0, 8)}`;
            loadIncidents();
        } else {
            statusText.style.color = "var(--color-rose)";
            statusText.textContent = "TRANSMISSION_FAILED: SYSTEM_ERROR";
        }
    } catch(e) {
        statusText.style.color = "var(--color-rose)";
        statusText.textContent = "CONNECTION_REFUSED";
    } finally {
        setTimeout(() => {
            btn.disabled = false;
            statusText.classList.add("hidden");
        }, 5000);
    }
}

// Approve pending incident action
async function approveIncident() {
    if (!selectedIncidentId) return;
    const btn = document.getElementById("approve-btn");
    btn.disabled = true;
    btn.textContent = "TRANSMITTING_APPROVAL_STATE...";

    try {
        const response = await fetch(`${API_BASE_URL}/incidents/${selectedIncidentId}/approve`, {
            method: "POST"
        });
        if (response.ok) {
            btn.textContent = "APPROVAL_GRANTED_SUCCESS";
            btn.style.backgroundColor = "var(--color-green)";
            await loadIncidents();
            await selectIncident(selectedIncidentId);
        } else {
            btn.textContent = "APPROVAL_REJECTED: BAD_REQUEST";
            btn.style.backgroundColor = "var(--color-rose)";
        }
    } catch(e) {
        btn.textContent = "CONNECTION_FAIL";
        btn.style.backgroundColor = "var(--color-rose)";
    } finally {
        setTimeout(() => {
            btn.disabled = false;
            btn.textContent = "CONFIRM_AND_EXECUTE";
            btn.style.backgroundColor = "";
        }, 3000);
    }
}

// Generate RCA trigger
async function triggerGenerateRca() {
    if (!selectedIncidentId) return;
    const btn = document.getElementById("gen-rca-btn");
    btn.disabled = true;
    btn.textContent = "GENERATING_REPORT...";

    try {
        const response = await fetch(`${API_BASE_URL}/incidents/${selectedIncidentId}/rca`);
        if (response.ok) {
            const rca = await response.json();
            renderRcaReport(rca);
        } else {
            btn.textContent = "GENERATION_ERROR";
        }
    } catch(e) {
        btn.textContent = "CONNECTION_REFUSED";
    } finally {
        btn.disabled = false;
        btn.textContent = "GENERATE_POSTMORTEM";
    }
}

// Download postmortem as txt file
function downloadRcaTxt() {
    if (!selectedIncidentId) return;
    const incident = incidents.find(i => i.id === selectedIncidentId);
    if (!incident || !incident.rca) return;

    const rca = incident.rca;
    const content = `==================================================
AUTO-REMEDIATOR AI - POSTMORTEM INCIDENT REPORT
Incident ID: ${selectedIncidentId}
Service: ${incident.service}
Issue Type: ${incident.issue_type}
Status: RESOLVED
Date Generated: ${new Date().toISOString()}
==================================================

1. SUMMARY
${rca.summary}

2. TIMELINE HISTORY
${rca.timeline ? rca.timeline.join("\n") : "None"}

3. ROOT CAUSE ANALYSIS
${rca.root_cause_analysis}

4. RESOLUTION ACTIONS TAKEN
${rca.resolution_taken}

5. PREVENTION RECOMMENDATIONS
${rca.prevention_recommendations ? rca.prevention_recommendations.map((r, i) => `[${i+1}] ${r}`).join("\n") : "None"}
`;

    const blob = new Blob([content], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `rca_report_${selectedIncidentId.slice(0, 8)}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

// Initialization and event bindings
document.addEventListener("DOMContentLoaded", () => {
    // Poll metric dials immediately and every 15 seconds
    loadAgentHealth();
    healthPollInterval = setInterval(loadAgentHealth, 15000);

    // Poll incidents immediately and every 5 seconds
    loadIncidents();
    incidentPollInterval = setInterval(loadIncidents, 5000);

    // Event list bindings
    document.getElementById("inject-btn").onclick = injectFailure;
    document.getElementById("approve-btn").onclick = approveIncident;
    document.getElementById("gen-rca-btn").onclick = triggerGenerateRca;
    document.getElementById("download-rca-btn").onclick = downloadRcaTxt;
    document.getElementById("refresh-btn").onclick = () => {
        loadIncidents();
        loadAgentHealth();
    };
});
