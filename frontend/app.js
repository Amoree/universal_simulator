const API = '/api';
let activeProjectId = null;
let activeProject = null;
let baselineResult = null;
let scenarios = [];

const labelMap = {
  users: 'Users',
  daily_events: 'Daily events',
  retention_days: 'Retention days',
  peak_factor: 'Peak factor',
  budget: 'Budget',
  avg_event_size_kb: 'Avg event size (KB)',
  response_time_ms: 'Response time (ms)',
  launch_weeks: 'Launch weeks',
  description: 'Description',
};

const byId = (id) => document.getElementById(id);

function showNotice(message, isError = false) {
  const notice = byId('notice');
  notice.textContent = message;
  notice.classList.toggle('error', isError);
  notice.classList.remove('hidden');
  clearTimeout(showNotice.timer);
  showNotice.timer = setTimeout(() => notice.classList.add('hidden'), 4000);
}

function renderProjectList(projects) {
  const list = byId('project-list');
  list.innerHTML = '';
  projects.forEach((project) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'project-item' + (project.id === activeProjectId ? ' active' : '');
    button.textContent = project.name;
    button.addEventListener('click', () => openProject(project.id));
    list.appendChild(button);
  });
}

async function loadProjects() {
  const projects = await fetchJson('/projects');
  renderProjectList(projects);
}

async function fetchJson(path, options = {}) {
  const response = await fetch(API + path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || 'Request failed');
  return body;
}

function setView(mode) {
  const showWelcome = mode === 'welcome';
  const showCreate = mode === 'create';
  const showDashboard = mode === 'dashboard';
  byId('welcome').classList.toggle('hidden', !showWelcome);
  byId('create-form-panel').classList.toggle('hidden', !showCreate);
  byId('dashboard').classList.toggle('hidden', !showDashboard);
}

async function openProject(projectId) {
  activeProjectId = projectId;
  const project = await fetchJson(`/projects/${projectId}`);
  activeProject = project;
  byId('project-title').textContent = project.name;
  byId('source-text').value = project.original_requirements || '';
  renderRequirements(project.requirements || []);
  baselineResult = null;
  scenarios = [];
  await loadProjects();
  renderResult(null);
  renderScenarios();
  setView('dashboard');
}

function renderRequirements(requirements) {
  const list = byId('requirements-list');
  list.innerHTML = '';
  if (!requirements.length) {
    const empty = document.createElement('div');
    empty.textContent = 'No extracted requirements yet.';
    empty.style.color = '#8ea3ba';
    list.appendChild(empty);
    return;
  }
  requirements.forEach((req) => {
    const row = document.createElement('div');
    row.className = 'requirement-row';
    const key = document.createElement('div');
    key.className = 'key';
    key.textContent = labelMap[req.key] || req.key;
    const input = document.createElement('input');
    input.value = req.value || '';
    input.addEventListener('input', () => {
      req.value = input.value;
      req.confirmed = true;
    });
    const unit = document.createElement('div');
    unit.textContent = req.unit || '';
    unit.style.color = '#8ea3ba';
    unit.style.fontSize = '11px';
    row.append(key, input, unit);
    list.appendChild(row);
  });
}

async function extractRequirements() {
  if (!activeProjectId) return;
  const text = byId('source-text').value.trim();
  if (!text) {
    showNotice('Paste some requirements first.', true);
    return;
  }
  const result = await fetchJson(`/projects/${activeProjectId}/requirements/extract`, {
    method: 'POST',
    body: JSON.stringify({ text }),
  });
  const existing = new Map((activeProject.requirements || []).map((item) => [item.key, item]));
  for (const item of result.extracted) {
    if (!existing.has(item.key)) {
      existing.set(item.key, item);
    }
  }
  activeProject.requirements = Array.from(existing.values());
  renderRequirements(activeProject.requirements);
  showNotice(`${result.extracted.length} extraction candidates added. Review and save.`);
}

async function saveRequirements() {
  if (!activeProjectId) return;
  const payload = (activeProject.requirements || []).map((item) => ({
    category: item.category || 'system',
    key: item.key,
    value: item.value ?? '',
    unit: item.unit ?? null,
    source_text: item.source_text ?? null,
    confidence: item.confidence || 'medium',
    confirmed: !!item.confirmed,
  }));

  const saved = await fetchJson(`/projects/${activeProjectId}/requirements`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
  activeProject.requirements = saved;
  renderRequirements(saved);
  showNotice('Requirements saved.');
}

async function runBaseline() {
  if (!activeProjectId) return;
  const result = await fetchJson(`/projects/${activeProjectId}/simulate`, { method: 'POST' });
  baselineResult = result;
  renderResult(result);
  showNotice('Baseline simulation complete.');
}

function renderResult(result) {
  byId('metric-average').textContent = result && result.average_rps !== null ? Number(result.average_rps).toFixed(3) : '—';
  byId('metric-peak').textContent = result && result.peak_rps !== null ? Number(result.peak_rps).toFixed(3) : '—';
  byId('metric-storage').textContent = result && result.storage_gb !== null ? Number(result.storage_gb).toFixed(2) : '—';
  byId('metric-budget').textContent = result && result.monthly_budget_usd !== null ? '$' + Number(result.monthly_budget_usd).toFixed(2) : '—';
  byId('result-summary').textContent = result ? result.summary : 'No simulation run yet.';
  const assumptions = byId('assumptions-list');
  const warnings = byId('warnings-list');
  assumptions.innerHTML = result && result.assumptions?.length ? result.assumptions.map((s) => `<li>${s}</li>`).join('') : '<li>None</li>';
  warnings.innerHTML = result && result.warnings?.length ? result.warnings.map((s) => `<li>${s}</li>`).join('') : '<li>None</li>';
}

async function createScenario(event) {
  event.preventDefault();
  if (!activeProjectId) return;
  const overrides = {};
  const dailyEvents = byId('scenario-events').value.trim();
  const peakFactor = byId('scenario-peak').value.trim();
  const retention = byId('scenario-retention').value.trim();
  if (dailyEvents) overrides.daily_events = Number(dailyEvents);
  if (peakFactor) overrides.peak_factor = Number(peakFactor);
  if (retention) overrides.retention_days = Number(retention);
  if (!Object.keys(overrides).length) {
    showNotice('Enter at least one override to create a scenario.', true);
    return;
  }
  const payload = {
    name: byId('scenario-name').value.trim(),
    description: 'Scenario created from the dashboard',
    overrides,
  };
  const created = await fetchJson(`/projects/${activeProjectId}/scenarios`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  const result = await fetchJson(`/projects/${activeProjectId}/scenarios/${created.id}/simulate`, { method: 'POST' });
  scenarios.push({ ...created, result });
  byId('scenario-form').reset();
  renderScenarios();
  showNotice('Scenario created and simulated.');
}

function renderScenarios() {
  const root = byId('scenario-results');
  root.innerHTML = '';
  if (!scenarios.length) {
    root.innerHTML = '<div class="muted">No scenarios yet.</div>';
    drawChart();
    return;
  }

  scenarios.forEach((s) => {
    const row = document.createElement('div');
    row.className = 'scenario-row';
    const name = document.createElement('div');
    name.innerHTML = `<strong>${s.name}</strong><small>${Object.entries(s.overrides).map(([k, v]) => `${labelMap[k] || k}: ${v}`).join(' • ')}</small>`;
    const avg = document.createElement('div');
    avg.innerHTML = `<strong>${s.result?.average_rps !== null ? Number(s.result.average_rps).toFixed(3) : '—'}</strong><small>avg rps</small>`;
    const peak = document.createElement('div');
    peak.innerHTML = `<strong>${s.result?.peak_rps !== null ? Number(s.result.peak_rps).toFixed(3) : '—'}</strong><small>peak rps</small>`;
    const storage = document.createElement('div');
    storage.innerHTML = `<strong>${s.result?.storage_gb !== null ? Number(s.result.storage_gb).toFixed(2) : '—'}</strong><small>GB</small>`;
    row.append(name, avg, peak, storage);
    root.appendChild(row);
  });

  drawChart();
}

function drawChart() {
  const root = byId('comparison-chart');
  root.innerHTML = '';
  if (!baselineResult) {
    root.innerHTML = '<div class="muted">Run the baseline before comparing scenarios.</div>';
    return;
  }
  const series = [{ name: 'Baseline', result: baselineResult, alt: false }, ...scenarios.map((s) => ({ name: s.name, result: s.result, alt: true }))];
  const max = Math.max(...series.map((item) => Number(item.result?.peak_rps || 0)), 1);

  series.forEach((item) => {
    const row = document.createElement('div');
    row.className = 'bar-row';
    const label = document.createElement('span');
    label.textContent = item.name;
    const track = document.createElement('div');
    track.className = 'bar-track';
    const fill = document.createElement('div');
    fill.className = 'bar-fill' + (item.alt ? ' alt' : '');
    const value = Number(item.result?.peak_rps || 0);
    fill.style.width = `${(value / max) * 100}%`;
    track.appendChild(fill);
    const valueText = document.createElement('span');
    valueText.textContent = value ? `${value.toFixed(2)} rps` : '—';
    row.append(label, track, valueText);
    root.appendChild(row);
  });
}

async function init() {
  try {
    const projects = await fetchJson('/projects');
    renderProjectList(projects);
    if (projects.length) {
      await openProject(projects[0].id);
    } else {
      setView('welcome');
    }
  } catch (error) {
    showNotice(`Could not connect to the API: ${error.message}`, true);
    setView('welcome');
  }
}

byId('new-project').addEventListener('click', () => {
  activeProjectId = null;
  setView('create');
  byId('project-form').reset();
});
byId('start-project').addEventListener('click', () => {
  activeProjectId = null;
  setView('create');
});
byId('cancel-create').addEventListener('click', () => {
  if (activeProjectId) {
    setView('dashboard');
  } else {
    setView('welcome');
  }
});

byId('project-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const payload = {
    name: byId('project-name').value.trim(),
    description: byId('project-description').value.trim() || null,
    original_requirements: byId('project-text').value.trim() || null,
  };
  try {
    const project = await fetchJson('/projects', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    await openProject(project.id);
    showNotice('Project created.');
  } catch (error) {
    showNotice(error.message, true);
  }
});

byId('extract-btn').addEventListener('click', extractRequirements);
byId('save-requirements').addEventListener('click', saveRequirements);
byId('run-baseline').addEventListener('click', runBaseline);
byId('scenario-form').addEventListener('submit', createScenario);

init();
