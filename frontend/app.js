// Configuration
const API_BASE_URL = ""; // Relative path to API

// Global State
let incidents = [];
let selectedIncidentId = null;
let healthPollInterval = null;
let incidentPollInterval = null;
let sseSource = null;

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
        case "ESCALATED":
            return "badge-blocked";
        default:
            return "badge-blocked";
    }
}

// ---------------------------------------------------------
// Navigation Tabs
// ---------------------------------------------------------
function initTabs() {
    const navItems = document.querySelectorAll(".nav-item");
    const panels = document.querySelectorAll(".nav-panel");

    navItems.forEach(item => {
        item.addEventListener("click", () => {
            navItems.forEach(n => n.classList.remove("active"));
            item.classList.add("active");
            
            const targetId = item.getAttribute("data-panel");
            panels.forEach(p => {
                if(p.id === targetId) p.classList.add("active");
                else p.classList.remove("active");
            });

            // Trigger specific loads based on panel
            if(targetId === "command-center") {
                loadSystemOverview();
                loadIncidentsFallback(); // force refresh
            } else if(targetId === "agent-health-panel") {
                loadAgentHealthDashboard();
            } else if(targetId === "governance-panel") {
                loadGovernancePanel();
            }
        });
    });
}

// ---------------------------------------------------------
// Feature 8: System Overview
// ---------------------------------------------------------
async function loadSystemOverview() {
    try {
        const res = await fetch(`${API_BASE_URL}/system-overview`);
        if(!res.ok) throw new Error("Overview failed");
        const data = await res.json();
        
        document.getElementById("kpi-healthy-val").textContent = `${data.healthy_services}/${data.total_services}`;
        document.getElementById("kpi-open-val").textContent = data.open_incidents;
        document.getElementById("kpi-resolved-val").textContent = data.resolved_today;
        document.getElementById("kpi-mttr-val").textContent = data.avg_mttr_minutes;
        document.getElementById("kpi-agent-val").textContent = `${data.agent_health_score.toFixed(1)}%`;
        document.getElementById("kpi-autonomy-val").textContent = data.autonomy_mode;
    } catch(e) {
        console.error("Failed to load system overview:", e);
    }
}

// ---------------------------------------------------------
// Feature 1: Live Incident Dashboard (SSE)
// ---------------------------------------------------------
function initSSEFeed() {
    const sseDot = document.getElementById("sse-dot");
    const sseLabel = document.getElementById("sse-label");

    if (window.EventSource) {
        sseSource = new EventSource(`${API_BASE_URL}/incidents/stream`);
        
        sseSource.onopen = () => {
            sseDot.className = "sse-dot connected";
            sseLabel.textContent = "LIVE_STREAM";
            // Clear polling fallback if SSE connects
            if(incidentPollInterval) {
                clearInterval(incidentPollInterval);
                incidentPollInterval = null;
            }
        };

        sseSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                incidents = data;
                renderIncidentsList();
                if(selectedIncidentId) {
                    const currentSelected = incidents.find(i => i.id === selectedIncidentId);
                    if (currentSelected) renderIncidentDetails(currentSelected);
                }
            } catch(e) {
                console.error("SSE parse error:", e);
            }
        };

        sseSource.onerror = () => {
            sseDot.className = "sse-dot error";
            sseLabel.textContent = "SSE_ERROR";
            sseSource.close();
            // Fallback to polling
            if(!incidentPollInterval) {
                incidentPollInterval = setInterval(loadIncidentsFallback, 5000);
            }
        };
    } else {
        sseDot.className = "sse-dot polling";
        sseLabel.textContent = "POLLING";
        incidentPollInterval = setInterval(loadIncidentsFallback, 5000);
    }
}

async function loadIncidentsFallback() {
    try {
        const response = await fetch(`${API_BASE_URL}/incidents`);
        if (!response.ok) throw new Error("Incidents list response not ok");
        incidents = await response.json();
        renderIncidentsList();
        
        if (selectedIncidentId) {
            const currentSelected = incidents.find(i => i.id === selectedIncidentId);
            if (currentSelected) renderIncidentDetails(currentSelected);
        }
    } catch(e) {
        console.error("Failed to poll incidents feed:", e);
    }
}

function renderIncidentsList() {
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
}

// ---------------------------------------------------------
// Incident Selection & Details
// ---------------------------------------------------------
async function selectIncident(id) {
    selectedIncidentId = id;
    
    // Rerender list to highlight selection
    renderIncidentsList();
    
    try {
        const response = await fetch(`${API_BASE_URL}/incidents/${id}`);
        if (!response.ok) throw new Error("Incident detail response not ok");
        const incident = await response.json();
        
        renderIncidentDetails(incident);
        loadIncidentTimeline(id);
        renderExecutionLogs(incident);
        
        document.getElementById("details-section").scrollIntoView({ behavior: 'smooth' });
    } catch(e) {
        console.error(`Failed to fetch incident detail for ${id}:`, e);
    }
}

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

    // Subagents mock details
    const sublogs = document.getElementById("subagent-logs");
    if (incident.root_cause && incident.root_cause !== "Unknown anomaly") {
        sublogs.textContent = `Root patterns identified: ${incident.root_cause}`;
    } else {
        sublogs.textContent = "Logs empty. Telemetry fallback active.";
    }

    const subtraces = document.getElementById("subagent-traces");
    subtraces.textContent = incident.evidence && incident.evidence.length > 0 
        ? incident.evidence.join("\n") 
        : "No tracing bottlenecks found. Empty Jaeger traces.";

    const subdeploy = document.getElementById("subagent-deploy");
    subdeploy.textContent = incident.issue_type === "high_latency" 
        ? "Correlating container limits. Zero deployments in last 2h."
        : "Healthy container boundaries. No restarts detected.";

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

    // Feature 3: Approval Action Panel
    const appPanel = document.getElementById("approval-panel");
    if (incident.status === "PENDING_APPROVAL") {
        appPanel.classList.remove("hidden");
    } else {
        appPanel.classList.add("hidden");
    }

    // Postmortem RCA Panel
    const rcaPanel = document.getElementById("rca-panel");
    const genRcaBtn = document.getElementById("gen-rca-btn");
    const copyRcaBtn = document.getElementById("copy-rca-btn");
    const rcaContent = document.getElementById("rca-content");

    if (incident.status === "RESOLVED") {
        rcaPanel.classList.remove("hidden");
        if (incident.rca) {
            renderRcaReport(incident.rca);
        } else {
            rcaContent.classList.add("hidden");
            genRcaBtn.classList.remove("hidden");
            copyRcaBtn.classList.add("hidden");
        }
    } else {
        rcaPanel.classList.add("hidden");
    }
}

// ---------------------------------------------------------
// Feature 2: Incident Timeline
// ---------------------------------------------------------
async function loadIncidentTimeline(id) {
    const container = document.getElementById("timeline-container");
    if(!container) return;
    
    try {
        const res = await fetch(`${API_BASE_URL}/incidents/${id}/timeline`);
        if(!res.ok) throw new Error("Timeline fetch failed");
        const data = await res.json();
        
        container.innerHTML = "";
        data.stages.forEach(stage => {
            const timeStr = stage.timestamp ? new Date(stage.timestamp).toLocaleTimeString() : "--:--:--";
            
            const el = document.createElement("div");
            el.className = `timeline-stage ${stage.status}`;
            el.innerHTML = `
                <div class="timeline-dot ${stage.status}">
                    <div class="timeline-dot-inner"></div>
                </div>
                <div class="timeline-body">
                    <div class="timeline-header">
                        <span class="timeline-label">${stage.label}</span>
                        <span class="timeline-status-tag ${stage.status}">${stage.status}</span>
                        <span class="timeline-time">${timeStr}</span>
                    </div>
                    <div class="timeline-desc">${stage.description}</div>
                </div>
            `;
            container.appendChild(el);
        });
    } catch(e) {
        console.error("Failed to load timeline", e);
        container.innerHTML = `<div class="text-xs text-rose-500 font-mono py-2">Error loading timeline</div>`;
    }
}

// Timeline expand/collapse logic
document.getElementById("timeline-toggle")?.addEventListener("click", () => {
    const container = document.getElementById("timeline-container");
    const icon = document.getElementById("timeline-toggle-icon");
    if(container.classList.contains("hidden")) {
        container.classList.remove("hidden");
        icon.textContent = "▼";
    } else {
        container.classList.add("hidden");
        icon.textContent = "▶";
    }
});

// ---------------------------------------------------------
// Feature 7: Execution Logs
// ---------------------------------------------------------
function renderExecutionLogs(incident) {
    const container = document.getElementById("exec-logs-container");
    if(!container) return;
    
    if(!incident.audit_trail || incident.audit_trail.length === 0) {
        container.innerHTML = `<div class="text-xs text-zinc-500">No execution logs available.</div>`;
        return;
    }
    
    container.innerHTML = "";
    incident.audit_trail.forEach(entry => {
        const timeStr = new Date(entry.timestamp).toLocaleTimeString();
        const statusClass = entry.success ? "success" : "failed";
        const badgeClass = entry.success ? "ok" : "err";
        const badgeText = entry.success ? "SUCCESS" : "FAILED";
        
        const el = document.createElement("div");
        el.className = `exec-log-entry ${statusClass}`;
        el.innerHTML = `
            <span class="exec-log-time">${timeStr}</span>
            <span class="exec-log-badge ${badgeClass}">${badgeText}</span>
            <span class="exec-log-text">Executed <strong>${entry.action}</strong>: ${entry.success ? entry.stdout : entry.stderr || "No output"}</span>
        `;
        container.appendChild(el);
    });
}


// ---------------------------------------------------------
// Feature 4: Agent Health Dashboard
// ---------------------------------------------------------
async function loadAgentHealthDashboard() {
    try {
        const res = await fetch(`${API_BASE_URL}/agent-health/agents`);
        if(!res.ok) throw new Error("Agent health fetch failed");
        const data = await res.json();
        
        // Update top-level metrics on that panel
        const sum = data.summary;
        document.getElementById("ah-total-decisions").textContent = sum.total_decisions;
        document.getElementById("ah-avg-confidence").textContent = `${(sum.avg_confidence*100).toFixed(1)}%`;
        document.getElementById("ah-success-rate").textContent = `${(sum.success_rate*100).toFixed(1)}%`;
        document.getElementById("ah-health-score").textContent = `${sum.health_score.toFixed(1)}%`;
        document.getElementById("ah-drift-score").textContent = sum.drift_score.toFixed(3);
        document.getElementById("ah-autonomy").textContent = sum.autonomy_level;
        document.getElementById("agent-health-updated").textContent = `UPDATED: ${new Date().toLocaleTimeString()}`;

        // Render rows
        const container = document.getElementById("agent-rows-container");
        container.innerHTML = "";
        
        data.agents.forEach(ag => {
            const dotClass = ag.status === "NOMINAL" ? "nominal" : (ag.status === "DEGRADED" ? "degraded" : "critical");
            const barClass = ag.health_score >= 85 ? "green" : (ag.health_score >= 60 ? "amber" : "rose");
            const statusColor = ag.status === "NOMINAL" ? "var(--color-green)" : (ag.status === "DEGRADED" ? "var(--color-amber)" : "var(--color-rose)");
            
            const el = document.createElement("div");
            el.className = "agent-row";
            el.innerHTML = `
                <div class="flex flex-col gap-1">
                    <span class="font-mono text-xs font-bold text-terminal-light">${ag.name}</span>
                    <span class="font-mono text-[9px] text-zinc-500 uppercase tracking-widest">${ag.role}</span>
                </div>
                <div class="agent-col" style="text-align: left;">
                    <span class="font-bold text-terminal-light">${ag.health_score.toFixed(1)}%</span>
                    <div class="health-bar-container"><div class="health-bar-fill ${barClass}" style="width: ${ag.health_score}%"></div></div>
                </div>
                <div class="agent-col font-bold text-terminal-light">${(ag.avg_confidence*100).toFixed(1)}%</div>
                <div class="agent-col font-bold text-terminal-light">${ag.avg_latency_ms}ms</div>
                <div class="agent-col font-bold text-terminal-light">${(ag.success_rate*100).toFixed(1)}%</div>
                <div class="agent-col flex items-center justify-end gap-2" style="color: ${statusColor}; font-weight: 700;">
                    ${ag.status}
                    <div class="agent-status-dot ${dotClass}"></div>
                </div>
            `;
            container.appendChild(el);
        });

    } catch(e) {
        console.error("Failed to load agent health dashboard:", e);
    }
}

// ---------------------------------------------------------
// Feature 5: AI Governance Panel
// ---------------------------------------------------------
async function loadGovernancePanel() {
    try {
        const res = await fetch(`${API_BASE_URL}/agent-health`);
        if(!res.ok) throw new Error("Governance fetch failed");
        const data = await res.json();
        
        document.getElementById("governance-updated").textContent = `UPDATED: ${new Date().toLocaleTimeString()}`;
        
        document.getElementById("gov-health-score").textContent = `${data.health_score.toFixed(1)}%`;
        document.getElementById("gov-decision-accuracy").textContent = `${(data.avg_confidence*100).toFixed(1)}%`;
        document.getElementById("gov-drift").textContent = data.drift_score.toFixed(3);
        document.getElementById("gov-total-decisions").textContent = data.total_decisions;
        document.getElementById("gov-success-rate").textContent = `${(data.success_rate*100).toFixed(1)}%`;
        
        const badge = document.getElementById("gov-autonomy-badge");
        const desc = document.getElementById("gov-autonomy-desc");
        const bannerContainer = document.getElementById("governance-banner-container");
        
        badge.textContent = data.autonomy_level;
        badge.className = "autonomy-badge";
        
        if (data.autonomy_level === "FULL") {
            badge.classList.add("full");
            desc.textContent = "Pipeline operating autonomously.";
            document.getElementById("gov-status").textContent = "NOMINAL";
            bannerContainer.innerHTML = `
                <div class="governance-banner ok">
                    <svg class="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                    <span><strong>SYSTEM OPTIMAL:</strong> All operations are running with full autonomy.</span>
                </div>
            `;
        } else if (data.autonomy_level === "ASSISTED") {
            badge.classList.add("assisted");
            desc.textContent = "High-risk actions require human approval.";
            document.getElementById("gov-status").textContent = "DEGRADED";
            bannerContainer.innerHTML = `
                <div class="governance-banner warning">
                    <svg class="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" /></svg>
                    <span><strong>AUTONOMY DEGRADED:</strong> System health has fallen below 85%. Human oversight mandated for high-risk actions.</span>
                </div>
            `;
        } else {
            badge.classList.add("escalate");
            desc.textContent = "All actions require human approval.";
            document.getElementById("gov-status").textContent = "CRITICAL";
            bannerContainer.innerHTML = `
                <div class="governance-banner critical">
                    <svg class="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" /></svg>
                    <span><strong>CRITICAL ALERT:</strong> System health below 60%. Full ESCALATE_ALL protocol engaged. Autonomy suspended.</span>
                </div>
            `;
        }
        
    } catch(e) {
        console.error("Failed to load governance panel:", e);
    }
}


// ---------------------------------------------------------
// Original Command Center Logic & Metric Fetches
// ---------------------------------------------------------
async function loadAgentHealth() {
    try {
        const response = await fetch(`${API_BASE_URL}/agent-health`);
        if (!response.ok) throw new Error("Agent health response not ok");
        const data = await response.json();

        const healthScore = parseFloat(data.health_score || 0).toFixed(1);
        const dashOffset = 439.8 - (439.8 * parseFloat(healthScore)) / 100;
        
        const ring = document.getElementById("health-ring");
        const valText = document.getElementById("health-value");
        if (ring) ring.style.strokeDashoffset = dashOffset;
        if (valText) valText.textContent = healthScore;

        if (ring) {
            if (healthScore >= 85) ring.style.stroke = "var(--color-green)";
            else if (healthScore >= 60) ring.style.stroke = "var(--color-amber)";
            else ring.style.stroke = "var(--color-rose)";
        }

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

// ---------------------------------------------------------
// Actions: Inject, Approve, Reject, RCA
// ---------------------------------------------------------
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
            if(!sseSource) loadIncidentsFallback();
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

async function approveIncident() {
    if (!selectedIncidentId) return;
    const btn = document.getElementById("approve-btn");
    btn.disabled = true;
    btn.textContent = "TRANSMITTING_APPROVAL...";

    try {
        const response = await fetch(`${API_BASE_URL}/incidents/${selectedIncidentId}/approve`, {
            method: "POST"
        });
        if (response.ok) {
            btn.textContent = "APPROVAL_GRANTED";
            btn.style.backgroundColor = "var(--color-green)";
            if(!sseSource) await loadIncidentsFallback();
        } else {
            btn.textContent = "REJECTED: BAD_REQUEST";
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

async function rejectIncident() {
    if (!selectedIncidentId) return;
    const btn = document.getElementById("reject-btn");
    btn.disabled = true;
    btn.textContent = "TRANSMITTING_REJECTION...";

    try {
        const response = await fetch(`${API_BASE_URL}/incidents/${selectedIncidentId}/reject`, {
            method: "POST"
        });
        if (response.ok) {
            btn.textContent = "MITIGATION_REJECTED";
            if(!sseSource) await loadIncidentsFallback();
        } else {
            btn.textContent = "ERROR: BAD_REQUEST";
        }
    } catch(e) {
        btn.textContent = "CONNECTION_FAIL";
    } finally {
        setTimeout(() => {
            btn.disabled = false;
            btn.textContent = "REJECT_MITIGATION";
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

function renderRcaReport(rca) {
    document.getElementById("gen-rca-btn").classList.add("hidden");
    const copyBtn = document.getElementById("copy-rca-btn");
    copyBtn.classList.remove("hidden");
    copyBtn.classList.remove("copied");
    copyBtn.textContent = "COPY";
    
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

function getRcaTextFormat(incident, rca) {
    return `==================================================
AUTO-REMEDIATOR AI - POSTMORTEM INCIDENT REPORT
Incident ID: ${incident.id}
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
}

function copyRcaToClipboard() {
    if (!selectedIncidentId) return;
    const incident = incidents.find(i => i.id === selectedIncidentId);
    if (!incident || !incident.rca) return;

    const content = getRcaTextFormat(incident, incident.rca);
    navigator.clipboard.writeText(content).then(() => {
        const btn = document.getElementById("copy-rca-btn");
        btn.classList.add("copied");
        btn.textContent = "COPIED!";
        setTimeout(() => {
            btn.classList.remove("copied");
            btn.textContent = "COPY";
        }, 2000);
    });
}

function downloadRcaTxt() {
    if (!selectedIncidentId) return;
    const incident = incidents.find(i => i.id === selectedIncidentId);
    if (!incident || !incident.rca) return;

    const content = getRcaTextFormat(incident, incident.rca);
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

// ---------------------------------------------------------
// Initialization
// ---------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
    initTabs();
    
    // Initial fetch of metrics & overview
    loadAgentHealth();
    loadSystemOverview();
    
    // Poll non-SSE metrics every 15 seconds
    healthPollInterval = setInterval(() => {
        loadAgentHealth();
        loadSystemOverview();
    }, 15000);

    // Try SSE for live incident stream
    initSSEFeed();

    // Event list bindings
    document.getElementById("inject-btn").onclick = injectFailure;
    document.getElementById("approve-btn").onclick = approveIncident;
    document.getElementById("reject-btn").onclick = rejectIncident;
    document.getElementById("gen-rca-btn").onclick = triggerGenerateRca;
    document.getElementById("copy-rca-btn").onclick = copyRcaToClipboard;
    document.getElementById("download-rca-btn").onclick = downloadRcaTxt;
    document.getElementById("refresh-btn").onclick = () => {
        loadIncidentsFallback();
        loadAgentHealth();
        loadSystemOverview();
    };
});
