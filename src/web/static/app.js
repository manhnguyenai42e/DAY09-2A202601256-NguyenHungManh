document.addEventListener('DOMContentLoaded', () => {
  // Custom Select Elements
  const customSelect = document.getElementById('custom-select');
  const customSelectTrigger = document.getElementById('custom-select-trigger');
  const customSelectLabel = document.getElementById('custom-select-label');
  const customSelectOptions = document.getElementById('custom-select-options');

  // Preview & Input Elements
  const samplePreview = document.getElementById('sample-preview');
  const prevCaseId = document.getElementById('prev-case-id');
  const prevOrderId = document.getElementById('prev-order-id');
  const prevMessage = document.getElementById('prev-message');

  const dropzone = document.getElementById('dropzone');
  const fileInput = document.getElementById('file-input');
  const fileNameBadge = document.getElementById('file-name-badge');
  const fileNameText = document.getElementById('file-name-text');

  const rawJsonEditor = document.getElementById('raw-json-editor');
  const btnRun = document.getElementById('btn-run');
  const stepperTimer = document.getElementById('stepper-timer');

  const outputPlaceholder = document.getElementById('output-placeholder');
  const outputResults = document.getElementById('output-results');

  const btnCopyJson = document.getElementById('btn-copy-json');
  const btnDownloadJson = document.getElementById('btn-download-json');
  const toggleJsonBtn = document.getElementById('toggle-json-btn');
  const rawJsonOutput = document.getElementById('raw-json-output');

  let activeTab = 'sample';
  let loadedSampleCases = [];
  let uploadedJsonData = null;
  let currentOutputJson = null;
  let selectedCaseId = null;

  // Initialize
  fetchSampleCases();
  setupTabs();
  setupDragAndDrop();
  setupEventListeners();

  // ----------------------------------------------------
  // 1. Fetch & Populate 50 Sample Cases (Custom Select)
  // ----------------------------------------------------
  async function fetchSampleCases() {
    try {
      const res = await fetch('/api/sample_cases');
      const data = await res.json();
      loadedSampleCases = data.cases || [];

      customSelectOptions.innerHTML = '';
      if (loadedSampleCases.length === 0) {
        customSelectLabel.textContent = 'Không tìm thấy case mẫu';
        return;
      }

      loadedSampleCases.forEach((c, idx) => {
        const shortOrder = c.claimed_order_id ? c.claimed_order_id.substring(0, 8) : '';
        const labelText = shortOrder ? `${c.case_id} (${shortOrder})` : c.case_id;

        const optDiv = document.createElement('div');
        optDiv.className = `custom-select-option ${idx === 0 ? 'selected' : ''}`;
        optDiv.textContent = labelText;
        optDiv.dataset.value = c.case_id;

        optDiv.addEventListener('click', (e) => {
          e.stopPropagation();
          selectCase(c.case_id, labelText, optDiv);
        });

        customSelectOptions.appendChild(optDiv);
      });

      // Default select EC_001
      const firstCase = loadedSampleCases[0];
      const firstLabel = firstCase.claimed_order_id ? `${firstCase.case_id} (${firstCase.claimed_order_id.substring(0, 8)})` : firstCase.case_id;
      selectedCaseId = firstCase.case_id;
      customSelectLabel.textContent = firstLabel;
      updateSamplePreview(firstCase.case_id);

    } catch (err) {
      console.error('Failed to load sample cases:', err);
    }
  }

  // Toggle custom dropdown
  customSelectTrigger.addEventListener('click', (e) => {
    e.stopPropagation();
    const isOpen = !customSelectOptions.classList.contains('hidden');
    if (isOpen) {
      customSelectOptions.classList.add('hidden');
      customSelect.classList.remove('open');
    } else {
      customSelectOptions.classList.remove('hidden');
      customSelect.classList.add('open');
    }
  });

  // Close dropdown when clicking outside
  document.addEventListener('click', () => {
    if (customSelectOptions) {
      customSelectOptions.classList.add('hidden');
      customSelect.classList.remove('open');
    }
  });

  function selectCase(caseId, labelText, targetOptDiv) {
    selectedCaseId = caseId;
    customSelectLabel.textContent = labelText;
    
    document.querySelectorAll('.custom-select-option').forEach(el => el.classList.remove('selected'));
    if (targetOptDiv) targetOptDiv.classList.add('selected');

    customSelectOptions.classList.add('hidden');
    customSelect.classList.remove('open');

    updateSamplePreview(caseId);
  }

  async function updateSamplePreview(caseId) {
    try {
      const res = await fetch(`/api/case/${caseId}`);
      const data = await res.json();
      if (data.input_json) {
        const req = data.input_json.customer_request || {};
        prevCaseId.textContent = data.input_json.case_id || caseId;
        prevOrderId.textContent = req.claimed_order_id || '-';
        prevMessage.textContent = req.message || '-';
      }
    } catch (err) {
      console.error(err);
    }
  }

  // ----------------------------------------------------
  // 2. Tab Navigation
  // ----------------------------------------------------
  function setupTabs() {
    const tabBtns = document.querySelectorAll('.tab-btn');
    tabBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        tabBtns.forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

        btn.classList.add('active');
        activeTab = btn.dataset.tab;
        document.getElementById(`tab-${activeTab}`).classList.add('active');
      });
    });
  }

  // ----------------------------------------------------
  // 3. Drag & Drop File Upload
  // ----------------------------------------------------
  function setupDragAndDrop() {
    dropzone.addEventListener('click', () => fileInput.click());

    dropzone.addEventListener('dragover', (e) => {
      e.preventDefault();
      dropzone.classList.add('dragover');
    });

    dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));

    dropzone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropzone.classList.remove('dragover');
      if (e.dataTransfer.files.length > 0) {
        handleFile(e.dataTransfer.files[0]);
      }
    });

    fileInput.addEventListener('change', (e) => {
      if (e.target.files.length > 0) {
        handleFile(e.target.files[0]);
      }
    });
  }

  function handleFile(file) {
    if (!file.name.endsWith('.json')) {
      alert('Vui lòng chọn file dạng .json');
      return;
    }

    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        uploadedJsonData = JSON.parse(e.target.result);
        fileNameText.textContent = file.name;
        fileNameBadge.classList.remove('hidden');
      } catch (err) {
        alert('File JSON không hợp lệ: ' + err.message);
      }
    };
    reader.readAsText(file);
  }

  // ----------------------------------------------------
  // 4. Run Investigation Action
  // ----------------------------------------------------
  function setupEventListeners() {
    btnRun.addEventListener('click', runInvestigation);

    btnCopyJson.addEventListener('click', () => {
      if (!currentOutputJson) return;
      navigator.clipboard.writeText(JSON.stringify(currentOutputJson, null, 2));
      alert('Đã sao chép Output JSON vào clipboard!');
    });

    btnDownloadJson.addEventListener('click', () => {
      if (!currentOutputJson) return;
      const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(currentOutputJson, null, 2));
      const downloadAnchor = document.createElement('a');
      downloadAnchor.setAttribute("href", dataStr);
      downloadAnchor.setAttribute("download", `${currentOutputJson.case_id || 'case_output'}.json`);
      document.body.appendChild(downloadAnchor);
      downloadAnchor.click();
      downloadAnchor.remove();
    });

    toggleJsonBtn.addEventListener('click', () => {
      rawJsonOutput.classList.toggle('hidden');
    });
  }

  async function runInvestigation() {
    let payload = null;

    if (activeTab === 'sample') {
      if (!selectedCaseId) {
        alert('Vui lòng chọn 1 case mẫu.');
        return;
      }
      const res = await fetch(`/api/case/${selectedCaseId}`);
      const data = await res.json();
      payload = data.input_json;

    } else if (activeTab === 'dragdrop') {
      if (!uploadedJsonData) {
        alert('Vui lòng kéo thả hoặc tải file JSON lên trước.');
        return;
      }
      payload = uploadedJsonData;

    } else if (activeTab === 'raw') {
      const rawText = rawJsonEditor.value.trim();
      if (!rawText) {
        alert('Vui lòng dán mã JSON vào ô soạn thảo.');
        return;
      }
      try {
        payload = JSON.parse(rawText);
      } catch (err) {
        alert('Cú pháp JSON không hợp lệ: ' + err.message);
        return;
      }
    }

    if (!payload) return;

    // Start UI execution visualizer
    btnRun.disabled = true;
    btnRun.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Đang chạy điều tra Multi-Agent...';
    outputPlaceholder.classList.remove('hidden');
    outputResults.classList.add('hidden');

    const startTime = performance.now();

    try {
      const response = await fetch('/api/investigate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      const resData = await response.json();
      const elapsed = ((performance.now() - startTime) / 1000).toFixed(2);
      stepperTimer.textContent = `${elapsed}s`;

      if (!response.ok || !resData.success) {
        alert('Lỗi điều tra: ' + (resData.error || 'Unknown error'));
        return;
      }

      await animateAgentStepper(resData.trace_steps || []);

      currentOutputJson = resData.case_output;
      renderResults(currentOutputJson);

    } catch (err) {
      alert('Không thể kết nối đến Dashboard API Server: ' + err.message);
    } finally {
      btnRun.disabled = false;
      btnRun.innerHTML = '<i class="fa-solid fa-bolt"></i> CHẠY ĐIỀU TRA MULTI-AGENT';
    }
  }

  // ----------------------------------------------------
  // 5. Agent Stepper Animation & Trace Log Terminal
  // ----------------------------------------------------
  const terminalBody = document.getElementById('trace-terminal-body');
  let currentTraceLogs = [];

  // Terminal Filter Handlers
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      renderTerminalLogs(btn.dataset.filter);
    });
  });

  async function animateAgentStepper(traceSteps) {
    const agents = ['coordinator', 'customer', 'order_product', 'payment', 'delivery', 'policy', 'verifier'];
    currentTraceLogs = traceSteps;
    terminalBody.innerHTML = '';
    
    // Reset all nodes
    agents.forEach(agent => {
      const el = document.getElementById(`node-${agent}`);
      if (el) {
        el.className = 'agent-node';
        el.querySelector('.node-status').textContent = 'Idle';
      }
    });

    for (let i = 0; i < traceSteps.length; i++) {
      const step = traceSteps[i];
      const agentKey = step.agent.toLowerCase().replace(/ & /g, '_').replace(/ agent/g, '').trim();
      const el = document.getElementById(`node-${agentKey}`);

      if (el) {
        el.className = 'agent-node running';
        el.querySelector('.node-status').textContent = 'Processing...';
      }

      appendTerminalLog(step);
      await new Promise(r => setTimeout(r, 70)); // smooth step delay

      if (el) {
        el.className = 'agent-node completed';
        el.querySelector('.node-status').textContent = 'Done';
      }
    }
  }

  function appendTerminalLog(step) {
    const div = document.createElement('div');
    div.className = `log-line ${step.type.toLowerCase()}`;
    div.dataset.type = step.type;

    let tagHtml = '';
    if (step.type === 'A2A_DISPATCH') {
      tagHtml = `<span class="tag-a2a">[A2A DISPATCH :${step.port}]</span>`;
    } else if (step.mcp_tool) {
      tagHtml = `<span class="tag-mcp">[MCP CALL :${step.port} ➔ ${step.mcp_tool}]</span>`;
    } else {
      tagHtml = `<span class="tag-policy">[${step.agent}]</span>`;
    }

    let detailStr = step.action;
    if (step.mcp_params) {
      detailStr += ` | params=${JSON.stringify(step.mcp_params)}`;
    }
    if (step.a2a_handoff) {
      detailStr += ` | handoff=${JSON.stringify(step.a2a_handoff)}`;
    }

    div.innerHTML = `<span class="ts">${step.timestamp}</span> ${tagHtml} ${detailStr}`;
    terminalBody.appendChild(div);
    terminalBody.scrollTop = terminalBody.scrollHeight;
  }

  function renderTerminalLogs(filter) {
    terminalBody.innerHTML = '';
    currentTraceLogs.forEach(step => {
      if (filter === 'a2a' && step.type !== 'A2A_DISPATCH') return;
      if (filter === 'mcp' && !step.mcp_tool) return;
      appendTerminalLog(step);
    });
  }

  // ----------------------------------------------------
  // 6. Render Output Results Dashboard
  // ----------------------------------------------------
  function renderResults(caseData) {
    outputPlaceholder.classList.add('hidden');
    outputResults.classList.remove('hidden');

    const assessment = caseData.case_assessment || {};
    const delivery = caseData.delivery_analysis || {};
    const payment = caseData.payment_reconciliation || {};
    const rootCause = caseData.root_cause_analysis || {};
    const financial = caseData.financial_resolution || {};

    // Hero Summary
    const statusBadge = document.getElementById('res-status-badge');
    if (assessment.case_status === 'no_action') {
      statusBadge.className = 'status-badge-large no-action';
      statusBadge.innerHTML = '<i class="fa-solid fa-circle-check"></i> NO ACTION REQUIRED';
    } else {
      statusBadge.className = 'status-badge-large';
      statusBadge.innerHTML = '<i class="fa-solid fa-circle-exclamation"></i> ACTION REQUIRED';
    }

    document.getElementById('res-primary-issue').textContent = assessment.primary_issue || '-';
    document.getElementById('res-confidence').textContent = assessment.confidence !== undefined ? assessment.confidence : '1.0';
    document.getElementById('res-refund-amount').textContent = `R$ ${financial.recommended_refund_brl !== undefined ? financial.recommended_refund_brl.toFixed(2) : '0.00'}`;

    // Secondary Issues
    const secondaryContainer = document.getElementById('res-secondary-issues');
    secondaryContainer.innerHTML = '';
    const secIssues = assessment.secondary_issues || [];
    if (secIssues.length === 0) {
      secondaryContainer.textContent = 'None';
    } else {
      secIssues.forEach(sec => {
        const tag = document.createElement('span');
        tag.className = 'tag';
        tag.textContent = sec;
        secondaryContainer.appendChild(tag);
      });
    }

    // Root Cause & Responsible Party
    const ranked = rootCause.ranked_causes || [];
    document.getElementById('res-root-cause').textContent = ranked.length > 0 ? `${ranked[0].cause_code} (Rank ${ranked[0].rank})` : 'None';
    
    const parties = rootCause.responsible_parties || [];
    if (parties.length === 0) {
      document.getElementById('res-responsible-party').textContent = 'None';
    } else {
      document.getElementById('res-responsible-party').textContent = parties.map(p => `${p.party_type.toUpperCase()} (${p.party_id})`).join(', ');
    }

    // Delivery Analysis
    document.getElementById('res-delivered-at').textContent = delivery.delivered_at || 'N/A';
    document.getElementById('res-estimated-at').textContent = delivery.estimated_delivery_at || 'N/A';
    document.getElementById('res-delivery-var').textContent = delivery.delivery_variance_hours !== null && delivery.delivery_variance_hours !== undefined ? `${delivery.delivery_variance_hours}h` : 'N/A';

    const lateSellersContainer = document.getElementById('res-late-sellers');
    lateSellersContainer.innerHTML = '';
    const lateSellers = delivery.late_handoff_seller_ids || [];
    if (lateSellers.length === 0) {
      lateSellersContainer.textContent = 'None';
    } else {
      lateSellers.forEach(s => {
        const tag = document.createElement('span');
        tag.className = 'tag';
        tag.textContent = s;
        lateSellersContainer.appendChild(tag);
      });
    }

    // Payment Reconciliation
    document.getElementById('res-item-total').textContent = payment.item_total_brl !== null && payment.item_total_brl !== undefined ? `R$ ${payment.item_total_brl.toFixed(2)}` : 'N/A';
    document.getElementById('res-freight-total').textContent = payment.freight_total_brl !== null && payment.freight_total_brl !== undefined ? `R$ ${payment.freight_total_brl.toFixed(2)}` : 'N/A';
    document.getElementById('res-expected-total').textContent = payment.expected_total_brl !== null && payment.expected_total_brl !== undefined ? `R$ ${payment.expected_total_brl.toFixed(2)}` : 'N/A';
    document.getElementById('res-paid-total').textContent = payment.payment_total_brl !== null && payment.payment_total_brl !== undefined ? `R$ ${payment.payment_total_brl.toFixed(2)}` : 'N/A';

    const recBadge = document.getElementById('res-reconciled-badge');
    if (payment.reconciled === true) {
      recBadge.innerHTML = '<span class="status-pill"><i class="fa-solid fa-check"></i> True (Matched ≤ 0.10 BRL)</span>';
    } else if (payment.reconciled === false) {
      recBadge.innerHTML = '<span class="status-pill danger"><i class="fa-solid fa-xmark"></i> False (Mismatched)</span>';
    } else {
      recBadge.textContent = 'N/A';
    }

    // Resolution Actions
    const actionsList = document.getElementById('res-actions-list');
    actionsList.innerHTML = '';
    const actions = caseData.resolution_actions || [];
    actions.forEach(act => {
      const li = document.createElement('li');
      li.textContent = act;
      actionsList.appendChild(li);
    });

    // Evidence IDs
    const evidenceTags = document.getElementById('res-evidence-tags');
    evidenceTags.innerHTML = '';
    const evidences = caseData.evidence_ids || [];
    document.getElementById('res-evidence-count').textContent = evidences.length;

    evidences.forEach(ev => {
      const tag = document.createElement('span');
      tag.className = 'tag evidence';
      tag.textContent = ev;
      evidenceTags.appendChild(tag);
    });

    // Raw JSON Viewer
    rawJsonOutput.querySelector('code').textContent = JSON.stringify(caseData, null, 2);
  }
});
