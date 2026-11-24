const statusLine = document.querySelector('#operation');

async function submit(path, payload) {
  const response = await fetch(path, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.message || '服务暂不可用');
  return result;
}

function handle(form, action) {
  form?.addEventListener('submit', async event => {
    event.preventDefault();
    const button = form.querySelector('button');
    button.disabled = true;
    statusLine.textContent = '正在核验…';
    try { await action(); }
    catch (error) { statusLine.textContent = error.message; }
    finally { button.disabled = false; }
  });
}

const save = document.querySelector('#save-run');
handle(save, async () => {
  const text = document.querySelector('#csv').value;
  const result = await submit('/api/runs', text ? {csv: text} : {sample: save.dataset.sample});
  const address = new URL('/work/issue', location.origin);
  address.search = new URLSearchParams({run: result.run_id, sample: save.dataset.sample});
  location.assign(address);
});

const issue = document.querySelector('#issue-run');
const download = document.querySelector('#download');
const picker = document.querySelector('#run');
picker?.addEventListener('change', () => {
  download.hidden = true;
  document.querySelector('#seal').textContent = '';
});
handle(issue, async () => {
  const run = picker.value;
  const result = await submit(`/api/runs/${run}/issue`, {});
  if (run !== picker.value) return;
  download.href = `/api/runs/${run}/export`;
  download.hidden = false;
  document.querySelector('#seal').textContent = result.seal;
  statusLine.textContent = result.reused ? '已取回原签发件' : '巡检证据已签发';
});

const dispatchForm = document.querySelector('#dispatch-form');
const chainPicker = document.querySelector('#dispatch-chain');
const stationInput = document.querySelector('#dispatch-station');
const dispatchOut = document.querySelector('#dispatch-result');

function syncStationBounds() {
  const option = chainPicker?.selectedOptions[0];
  if (!option) return;
  stationInput.placeholder = `${option.dataset.start} – ${option.dataset.end} mm`;
}
chainPicker?.addEventListener('change', syncStationBounds);
syncStationBounds();

handle(dispatchForm, async () => {
  const run = document.querySelector('#dispatch-run').value;
  const payload = {
    start: {chain: chainPicker.value, station_mm: Number(stationInput.value)},
    budget_mm: Number(document.querySelector('#dispatch-budget').value),
  };
  const batch = document.querySelector('#dispatch-batch').value.trim();
  if (batch) payload.batch_csv = batch;
  const result = await submit(`/api/runs/${run}/dispatch`, payload);
  const rows = result.route.map(step =>
    `<li>${step.chain} · ${step.start_mm}→${step.end_mm} mm${step.near_defect ? ' · <b>缺陷旁</b>' : ''}</li>`).join('');
  const left = result.unassigned_gaps.map(item =>
    `<li>${item.chain} · ${item.start_mm}→${item.end_mm} mm（${item.state === 'UNREACHABLE' ? '断链不可达' : '车程不足'}）</li>`).join('');
  dispatchOut.hidden = false;
  dispatchOut.innerHTML = `
    <p>${result.reused ? '已取回原派车计划（重试未重复派车）' : (result.refreshed ? '新批次已冲减缺口并完成重算' : '补巡计划已生成')}</p>
    <p>行驶 <b>${result.driven_mm}</b> / ${result.budget_mm} mm，剩余车程 ${result.remaining_budget_mm} mm；规划补巡 ${result.planned_mm} mm（不计入实测）</p>
    <ul>${rows || '<li>本趟无可补缺口</li>'}</ul>
    ${left ? `<p>留待下一班：</p><ul>${left}</ul>` : ''}`;
  statusLine.textContent = result.reused ? '派车计划已存在，原样取回' : '补巡派车已安排';
});
