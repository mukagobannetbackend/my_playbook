document.addEventListener('DOMContentLoaded', () => {
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
  const fileInput = document.querySelector('#screenshot');
  if (fileInput) fileInput.addEventListener('change', () => {
    const name = fileInput.files?.[0]?.name;
    const prompt = fileInput.closest('.file-drop')?.querySelector('.file-prompt b');
    if (name && prompt) prompt.textContent = name;
  });

  const selectAll = document.querySelector('#select-all');
  if (selectAll) selectAll.addEventListener('change', () => {
    document.querySelectorAll('input[name="entry_ids"]').forEach((input) => { input.checked = selectAll.checked; });
  });

  const editor = document.querySelector('#reflection-text');
  if (editor) {
    const status = document.querySelector('#save-indicator');
    const counter = document.querySelector('#character-count');
    let timer;
    let inFlight = false;
    let retryDelay = 1000;
    let lastSaved = editor.value;
    const save = async () => {
      if (inFlight || editor.value === lastSaved) return;
      const snapshot = editor.value;
      inFlight = true;
      status?.classList.add('saving');
      if (status) status.lastChild.textContent = ' Saving…';
      try {
        const response = await fetch(editor.dataset.saveUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, 'Accept': 'application/json' },
          body: JSON.stringify({ reflection: snapshot })
        });
        if (!response.ok) throw new Error('save failed');
        lastSaved = snapshot;
        retryDelay = 1000;
        if (editor.value === snapshot) {
          if (status) { status.classList.remove('saving', 'save-error'); status.lastChild.textContent = ' Saved'; }
        } else {
          if (status) status.lastChild.textContent = ' Saving newer changes…';
          clearTimeout(timer); timer = setTimeout(save, 250);
        }
      } catch (_) {
        if (status) { status.classList.remove('saving'); status.classList.add('save-error'); status.lastChild.textContent = ' Not saved · retrying soon'; }
        clearTimeout(timer); timer = setTimeout(save, retryDelay);
        retryDelay = Math.min(retryDelay * 2, 15000);
      } finally {
        inFlight = false;
      }
    };
    editor.addEventListener('input', () => {
      if (counter) counter.textContent = String(editor.value.length);
      if (status) { status.classList.remove('save-error'); status.lastChild.textContent = ' Unsaved changes'; }
      clearTimeout(timer); timer = setTimeout(save, 650);
    });
    editor.addEventListener('blur', save);
  }

  document.querySelectorAll('[data-confirm]').forEach((button) => button.addEventListener('click', (event) => {
    if (!window.confirm(button.dataset.confirm)) event.preventDefault();
  }));

  const readForm = document.querySelector('.mark-read-form');
  if (readForm) readForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = new FormData(readForm);
    try {
      const response = await fetch(readForm.action, { method: 'POST', headers: { 'X-CSRFToken': data.get('csrf_token'), 'Accept': 'application/json' } });
      if (response.ok) document.querySelectorAll('.notification-item.unread').forEach((item) => item.classList.remove('unread'));
      else readForm.submit();
    } catch (_) { readForm.submit(); }
  });

  const details = document.querySelector('#metadata-form');
  if (details) details.addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(details).entries());
    try {
      const response = await fetch(details.action, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, 'Accept': 'application/json' }, body: JSON.stringify(data) });
      if (response.ok) { const label = details.querySelector('button'); label.textContent = 'Details saved'; setTimeout(() => label.textContent = 'Save details', 1500); }
      else details.submit();
    } catch (_) { details.submit(); }
  });
});
