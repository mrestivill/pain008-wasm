(() => {
  "use strict";
  const SAMPLE = `payment_id,amount,currency,mandate_id,mandate_signed_on,sequence_type,collection_date,debtor_name,debtor_iban,debtor_bic,remittance
DD-10001,49.90,EUR,MANDATE-1001,2026-10-07,FRST,2026-10-15,Acme Customer,DE89370400440532013000,COBADEFFXXX,Invoice 10001
DD-10002,125.00,EUR,MANDATE-1002,2026-10-07,RCUR,2026-10-15,Example Customer,FR1420041010050500013M02606,BNPAFRPPXXX,Invoice 10002
DD-10003,19.95,EUR,MANDATE-1003,2026-10-07,OOFF,2026-10-15,Demo Customer,ES9121000418450200051332,CAIXESBBXXX,Invoice 10003`;
  const PYODIDE_VERSION = "0.314.0.7";
  const PYODIDE_INDEX = `https://cdn.jsdelivr.net/pyodide/v314.0.7/full/`;
  const ids = {csv:"csvInput",file:"csvFile",sample:"sampleBtn",validate:"validateBtn",generate:"generateBtn",copy:"copyBtn",download:"downloadBtn",downloadQ1x:"downloadQ1xBtn",generateFindings:"generateFindings",status:"status",summary:"summary",findings:"findings",xml:"xmlOutput",csvError:"csvError",creditorName:"creditorName",creditorIban:"creditorIban",creditorBic:"creditorBic",creditorScheme:"creditorScheme",collectionDate:"collectionDate",initiatorName:"initiatorName",engineBadge:"engineBadge"};
  const els = Object.fromEntries(Object.entries(ids).map(([k,v]) => [k, document.getElementById(v)]));
  let pyodide = null, lastXml = "", lastValidationPayload = null;

  function parseCSV(text) {
    const rows=[]; let row=[], cell="", quoted=false;
    for(let i=0;i<text.length;i++){const c=text[i],n=text[i+1];if(c==='"'&&quoted&&n==='"'){cell+='"';i++;continue}if(c==='"'){quoted=!quoted;continue}if(c===','&&!quoted){row.push(cell);cell='';continue}if((c==='\n'||c==='\r')&&!quoted){if(c==='\r'&&n==='\n')i++;row.push(cell);cell='';if(row.some(v=>v.trim()))rows.push(row);row=[];continue}cell+=c}if(cell||row.length){row.push(cell);if(row.some(v=>v.trim()))rows.push(row)}if(!rows.length)return[];const h=rows[0].map(x=>x.trim().toLowerCase());return rows.slice(1).map(v=>Object.fromEntries(h.map((k,i)=>[k,(v[i]||'').trim()])));
  }
  document.addEventListener('DOMContentLoaded', () => {
    const collectionDate = document.getElementById('collectionDate');

    const date = new Date();
    date.setDate(date.getDate() + 7);

    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');

    collectionDate.value = `${year}-${month}-${day}`;
  });
  function payload(){return {rows:parseCSV(els.csv.value),config:{creditor_name:els.creditorName.value,creditor_iban:els.creditorIban.value,creditor_bic:els.creditorBic.value,creditor_scheme_id:els.creditorScheme.value,collection_date:els.collectionDate.value,initiator_name:els.initiatorName.value}}}
  function localSummary(rows){const total=rows.reduce((s,r)=>s+(Number((r.amount||'0').replace(',','.'))||0),0);els.summary.innerHTML=`<div class="metric"><b>${rows.length}</b><span>transactions</span></div><div class="metric"><b>${total.toFixed(2)}</b><span>control sum</span></div>`}
  function showError(e){els.csvError.textContent=e?.message||String(e);els.csvError.hidden=false;els.status.textContent="Error";els.status.className="status bad"}
  function invalidateValidation(message="Not validated") {
    lastValidationPayload = null;
    lastXml = "";
    els.copy.disabled = els.download.disabled = els.downloadQ1x.disabled = true;
    els.status.textContent = message;
    els.status.className = "status neutral";
    els.findings.innerHTML = `<div class="finding">${escapeHtml(message)}</div>`;
    els.generateFindings.innerHTML = `<div class="finding">${escapeHtml(message)}</div>`;
    els.xml.textContent = "Click Validate or Generate XML to run validation.";
  }
  function render(data){
    const violations=data.violations||[];
    els.findings.innerHTML=violations.length
      ? violations.map(v=>`<div class="finding">${escapeHtml(typeof v==='string'?v:(v.message||JSON.stringify(v)))}</div>`).join('')
      : '<div class="finding ok">✓ pain001 ha validat les dades.</div>';
    const valid=!!data.is_valid;
    els.status.textContent=valid?'Valid':'Invalid';
    els.status.className='status '+(valid?'good':'bad');
    els.generate.disabled=!valid;
    if(data.sequence_type_defaulted_to_ooff) els.findings.insertAdjacentHTML("afterbegin", "<div class=\"finding ok\">ℹ No hi havia columna <code>sequence_type</code>: s\'ha aplicat <strong>OOFF</strong>.</div>");
    return valid;
  }
  function escapeHtml(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
  async function pyCall(fn,obj){
    if(!pyodide) throw new Error('Python WASM encara no està carregat.');
    pyodide.globals.set('payload_json', JSON.stringify(obj));
    const result = await pyodide.runPythonAsync(`import pain008\npain008.${fn}(payload_json)`);
    return JSON.parse(String(result));
  }
  async function validate(){
    try{
      els.csvError.hidden=true;
      const rows=parseCSV(els.csv.value);
      localSummary(rows);
      const current=payload();
      els.status.textContent='Validating…';
      els.status.className='status neutral';
      const data=await pyCall('validate',current);
      render(data);
      lastValidationPayload=JSON.stringify(current);
      if(data.is_valid) els.xml.textContent='Validation successful. You can now generate the XML.';
      return data;
    }catch(e){showError(e);return null;}
  }
  function renderGenerateErrors(violations){
    const list = violations || [];
    els.generateFindings.innerHTML = list.length
      ? list.map(v=>`<div class="finding">${escapeHtml(typeof v==='string'?v:(v.message||JSON.stringify(v)))}</div>`).join('')
      : '<div class="finding ok">✓ Validació correcta. XML generat.</div>';
  }
  async function generate(){
    const current=payload();
    els.csvError.hidden=true;
    els.generate.disabled=true;
    els.generate.textContent='Validating & generating…';
    els.generateFindings.innerHTML='<div class="finding">Validant i generant XML…</div>';
    lastXml='';
    els.copy.disabled=els.download.disabled=els.downloadQ1x.disabled=true;
    try{
      const data=await pyCall('generate',current);
      if(!data.success){
        renderGenerateErrors(data.violations||['pain001 no ha generat XML.']);
        els.status.textContent='Invalid';
        els.status.className='status bad';
        if(data.xml_preview){
          els.xml.textContent=data.xml_preview;
          els.copy.disabled=els.download.disabled=els.downloadQ1x.disabled=true;
        } else {
          els.xml.textContent='No s’ha pogut renderitzar l’XML.';
        }
        return;
      }
      renderGenerateErrors([]);
      lastXml=data.xml;
      els.xml.textContent=lastXml;
      els.copy.disabled=els.download.disabled=els.downloadQ1x.disabled=false;
      lastValidationPayload=JSON.stringify(current);
      els.status.textContent='Valid';
      els.status.className='status good';
    }catch(e){
      renderGenerateErrors([e?.message||String(e)]);
      els.status.textContent='Error';
      els.status.className='status bad';
      els.xml.textContent='XML no generat.';
    }finally{
      els.generate.textContent='Generate XML';
      els.generate.disabled=false;
    }
  }
  function download(name){if(!lastXml)return;const blob=new Blob([lastXml],{type:'application/xml;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();URL.revokeObjectURL(url)}
  els.sample.onclick=()=>{els.csv.value=SAMPLE;localSummary(parseCSV(els.csv.value));invalidateValidation('Sample loaded · click Validate.');};
  els.validate.onclick=validate;
  els.generate.onclick=generate;
  els.file.onchange=async()=>{const f=els.file.files[0];if(f){els.csv.value=await f.text();localSummary(parseCSV(els.csv.value));invalidateValidation('CSV loaded · click Validate.');}};
  [els.csv,els.creditorName,els.creditorIban,els.creditorBic,els.creditorScheme,els.collectionDate,els.initiatorName].forEach(el=>el.addEventListener('input',()=>invalidateValidation('Changes pending validation · click Validate.')));
  els.copy.onclick=async()=>{await navigator.clipboard.writeText(lastXml);els.copy.textContent='Copied ✓';setTimeout(()=>els.copy.textContent='Copy',1200)};els.download.onclick=()=>download('pain.008.001.08.xml');els.downloadQ1x.onclick=()=>download('pain.008.001.08.Q1X');
  async function boot(){try{els.status.textContent='Loading Python…';const mod=await import('https://cdn.jsdelivr.net/pyodide/v314.0.7/full/pyodide.mjs');pyodide=await mod.loadPyodide({indexURL:PYODIDE_INDEX, args:[]});els.xml.textContent='Instal·lant pain001…';await pyodide.loadPackage('micropip');const micropip=pyodide.pyimport('micropip');await micropip.install('pain001==0.0.72');pyodide.FS.writeFile('/home/pyodide/pain008.py',await (await fetch('python/pain008.py')).text());await pyodide.runPythonAsync("import sys; sys.path.append('/home/pyodide'); import pain008");els.engineBadge.textContent=`Python WASM ${PYODIDE_VERSION} · pain001 ${'0.0.72'} · single-thread`;els.status.textContent='Ready · not validated';els.status.className='status neutral';els.validate.disabled=false;els.generate.disabled=false;els.xml.textContent='Click Validate or Generate XML to run validation.';localSummary(parseCSV(els.csv.value));invalidateValidation('Ready · click Validate to validate, or Generate XML to validate and generate.');}catch(e){showError(e);els.engineBadge.textContent='Python WASM · error';els.xml.textContent='No s’ha pogut carregar Python/pain001. Revisa la consola del navegador.'}}
  els.csv.value=SAMPLE;boot();
})();

const CONFIG_STORAGE_KEY = 'creditorConfiguration';

const configFields = [
  'creditorName',
  'creditorIban',
  'creditorBic',
  'creditorScheme',
  'collectionDate',
  'initiatorName'
];

function saveConfig() {
  const config = {};

  configFields.forEach(id => {
    config[id] = document.getElementById(id).value;
  });

  localStorage.setItem(CONFIG_STORAGE_KEY, JSON.stringify(config));
}

function loadConfig() {
  const saved = localStorage.getItem(CONFIG_STORAGE_KEY);

  if (!saved) {
    return;
  }

  try {
    const config = JSON.parse(saved);

    configFields.forEach(id => {
      const field = document.getElementById(id);

      if (field && config[id] !== undefined) {
        field.value = config[id];
      }
    });
  } catch (error) {
    console.error('Error loading configuration:', error);
  }
}

function clearConfig() {
  localStorage.removeItem(CONFIG_STORAGE_KEY);
  location.reload();
}

document.addEventListener('DOMContentLoaded', () => {
  // El DOM ja està pintat/construït
  loadConfig();

  document.getElementById('saveConfig')
    .addEventListener('click', saveConfig);
  
  document.getElementById('loadConfig')
    .addEventListener('click', loadConfig);

  document.getElementById('clearConfig')
    .addEventListener('click', clearConfig);
});
