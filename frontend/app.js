const API = '/api';
const labels = {
  users: ['users', 'users'], daily_events: ['daily events', 'events/day'], peak_factor: ['peak traffic factor', 'x'],
  retention_days: ['retention', 'days'], avg_event_size_kb: ['average event size', 'KB'], response_time_ms: ['response-time target', 'ms'],
  budget: ['monthly budget', 'USD/month'], launch_weeks: ['launch timeline', 'weeks'], availability_target: ['availability target', 'target'],
  database_type: ['database', 'choice'], deployment_region: ['deployment region', 'region'], cache_enabled: ['cache enabled', 'boolean'], queue_enabled: ['queue enabled', 'boolean'],
  compute_instances: ['application instances', 'instances'], compute_unit_cost: ['compute cost per instance', 'USD/month'], database_monthly_cost: ['database cost', 'USD/month'],
  cache_monthly_cost: ['cache cost', 'USD/month'], queue_monthly_cost: ['queue cost', 'USD/month'], storage_cost_per_gb: ['storage unit cost', 'USD/GB/month'], network_monthly_cost: ['networking allowance', 'USD/month'],
};
let projectId = null;
let costChart = null;
const $ = (id) => document.getElementById(id);

async function request(path, options = {}) {
  const response = await fetch(API + path, {headers: {'Content-Type': 'application/json'}, ...options});
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`);
  return body;
}
function notify(message, error = false) {
  const el = $('notice'); el.textContent = message; el.classList.toggle('error', error); el.classList.remove('hidden');
  clearTimeout(notify.timer); notify.timer = setTimeout(() => el.classList.add('hidden'), 5000);
}
function setView(view) {
  $('welcome').classList.toggle('hidden', view !== 'welcome');
  $('entry-view').classList.toggle('hidden', view !== 'entry');
  $('results-view').classList.toggle('hidden', view !== 'results');
}
function readFormValues() {
  return [...document.querySelectorAll('#requirements-form [data-key]')].map((input) => {
    const key = input.dataset.key;
    const value = input.type === 'checkbox' ? String(input.checked) : input.value.trim();
    if (value === '') return null;
    const [label, unit] = labels[key] || [key, ''];
    return {category: key.includes('cost') || key === 'budget' ? 'budget' : key.includes('enabled') || key.includes('type') || key.includes('region') ? 'architecture' : 'system', key, value, unit, source_text: `${label} entered in the web form`, confidence: 'high', confirmed: true};
  }).filter(Boolean);
}
function loadValues(requirements) {
  const map = new Map(requirements.map((item) => [item.key, item.value]));
  document.querySelectorAll('#requirements-form [data-key]').forEach((input) => {
    const value = map.get(input.dataset.key);
    if (input.type === 'checkbox') input.checked = value === 'true';
    else input.value = value ?? '';
  });
}
async function refreshProjectList() {
  const projects = await request('/projects');
  const nav = $('project-list'); nav.replaceChildren();
  for (const project of projects) {
    const button = document.createElement('button'); button.type = 'button'; button.className = `project-button${project.id === projectId ? ' active' : ''}`; button.textContent = project.name;
    button.onclick = () => openProject(project.id); nav.append(button);
  }
}
function putList(id, items, fallback) {
  const list = $(id); list.replaceChildren();
  const entries = items?.length ? items : [fallback];
  for (const item of entries) { const li = document.createElement('li'); li.textContent = item; if (!items?.length) li.className = 'muted'; list.append(li); }
}
function number(value, suffix = '') { return value === null || value === undefined ? '—' : `${Number(value).toLocaleString(undefined, {maximumFractionDigits: 2})}${suffix}`; }
function drawCostChart(data) {
  const entries = Object.entries(data.cost_breakdown || {});
  $('chart-empty').classList.toggle('hidden', entries.length > 0);
  if (costChart) { costChart.destroy(); costChart = null; }
  if (!entries.length || typeof Chart === 'undefined') return;
  costChart = new Chart($('cost-chart'), {
    type: 'doughnut',
    data: {labels: entries.map(([name]) => name), datasets: [{data: entries.map(([, value]) => value), backgroundColor: ['#73e0b0','#8ba8ff','#f0c878','#d18bff','#ff9295','#50c6d8'], borderColor: '#151c28', borderWidth: 3}]},
    options: {responsive: true, maintainAspectRatio: false, plugins: {legend: {position: 'bottom', labels: {color: '#c4cfde', padding: 18}}, tooltip: {callbacks: {label: (context) => `${context.label}: $${Number(context.raw).toFixed(2)}/month`}}}},
  });
}
function renderResults(data, project) {
  $('result-title').textContent = `${project.name} · results`;
  $('result-description').textContent = project.description || 'Backend-generated estimates from the inputs you entered.';
  $('metric-average').textContent = number(data.average_rps);
  $('metric-peak').textContent = number(data.peak_rps);
  $('metric-storage').textContent = number(data.storage_gb);
  $('metric-cost').textContent = number(data.estimated_monthly_cost_usd, data.estimated_monthly_cost_usd == null ? '' : ' USD');
  $('metric-budget').textContent = number(data.budget_remaining_usd, data.budget_remaining_usd == null ? '' : ' USD');
  $('summary').textContent = data.summary;
  putList('warnings', data.warnings, 'No warnings from the current inputs.');
  putList('assumptions', data.assumptions, 'No default assumptions were applied.');
  putList('architecture', data.architecture, 'No architecture selections entered.');
  drawCostChart(data);
}
async function saveAndProcess(event) {
  event.preventDefault();
  const name = $('project-name').value.trim();
  if (!name) return;
  const description = $('project-description').value.trim();
  const notes = $('requirements-notes').value.trim();
  const requirements = readFormValues();
  try {
    let project;
    if (projectId) {
      project = await request(`/projects/${projectId}`);
    } else {
      project = await request('/projects', {method: 'POST', body: JSON.stringify({name, description: description || null, original_requirements: notes || null})});
      projectId = project.id;
    }
    await request(`/projects/${projectId}/requirements`, {method: 'PUT', body: JSON.stringify(requirements)});
    const result = await request(`/projects/${projectId}/simulate`, {method: 'POST'});
    project.name = name; project.description = description || null;
    renderResults(result, project);
    $('page-title').textContent = 'MVP results'; setView('results'); await refreshProjectList();
    notify('Requirements saved and processed by the backend.');
  } catch (error) { notify(error.message, true); }
}
async function openProject(id) {
  try {
    const project = await request(`/projects/${id}`); projectId = id;
    $('project-name').value = project.name; $('project-description').value = project.description || ''; $('requirements-notes').value = project.original_requirements || '';
    loadValues(project.requirements || []);
    const result = await request(`/projects/${id}/simulate`, {method: 'POST'});
    renderResults(result, project); $('page-title').textContent = 'MVP results'; setView('results'); await refreshProjectList();
  } catch (error) { notify(error.message, true); }
}
function startNew() {
  projectId = null; $('requirements-form').reset(); $('page-title').textContent = 'Enter your MVP requirements'; setView('entry');
}
$('start-project').addEventListener('click', startNew);
$('new-project').addEventListener('click', startNew);
$('edit-inputs').addEventListener('click', () => { $('page-title').textContent = 'Edit MVP requirements'; setView('entry'); });
$('requirements-form').addEventListener('submit', saveAndProcess);
(async () => {
  try { await refreshProjectList(); const projects = await request('/projects'); if (projects.length) await openProject(projects[0].id); else setView('welcome'); }
  catch (error) { setView('welcome'); notify(`Unable to load the workspace: ${error.message}`, true); }
})();
