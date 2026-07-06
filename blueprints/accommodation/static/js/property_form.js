'use strict';

// ── Number steppers ─────────────────────────────────────────
document.querySelectorAll('.num-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const target = document.getElementById(btn.dataset.target);
    if (!target) return;
    const min = parseInt(target.min ?? 0);
    const max = parseInt(target.max ?? 9999);
    let val = parseInt(target.value) || 0;
    val = btn.classList.contains('num-plus') ? Math.min(val + 1, max) : Math.max(val - 1, min);
    target.value = val;

    // Keep available_rooms ≤ total_rooms
    const total = document.getElementById('total_rooms');
    const avail = document.getElementById('available_rooms');
    if (total && avail && parseInt(avail.value) > parseInt(total.value)) {
      avail.value = total.value;
    }
  });
});

// ── Character counter for description ───────────────────────
const descEl    = document.getElementById('description');
const descCount = document.getElementById('desc-count');
if (descEl && descCount) {
  descEl.addEventListener('input', () => { descCount.textContent = descEl.value.length; });
}

// ── Service card toggle ──────────────────────────────────────
function toggleServiceCard(checkbox) {
  const card = checkbox.closest('.service-card');
  if (card) card.classList.toggle('selected', checkbox.checked);
}

// ── Step indicator: highlight as user scrolls ───────────────
const sections = ['basic','rooms','services','location','contact','photos'];
const stepEls  = {};
sections.forEach(s => { stepEls[s] = document.querySelector(`.step[data-section="${s}"]`); });

const observer = new IntersectionObserver(entries => {
  entries.forEach(entry => {
    const id = entry.target.id.replace('section-', '');
    const step = stepEls[id];
    if (step) step.classList.toggle('active', entry.isIntersecting);
  });
}, { threshold: 0.3 });

sections.forEach(s => {
  const el = document.getElementById(`section-${s}`);
  if (el) observer.observe(el);
});

// Click step → scroll to section
document.querySelectorAll('.step').forEach(step => {
  step.addEventListener('click', () => {
    const sec = document.getElementById(`section-${step.dataset.section}`);
    if (sec) sec.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
});

// ── Form submit state ────────────────────────────────────────
const form    = document.getElementById('property-form');
const subBtn  = document.getElementById('submit-btn');
if (form && subBtn) {
  form.addEventListener('submit', () => {
    subBtn.querySelector('.btn-text').style.display    = 'none';
    subBtn.querySelector('.btn-spinner').style.display = 'flex';
    subBtn.disabled = true;
  });
}

// ── Client-side validation ───────────────────────────────────
if (form) {
  form.addEventListener('submit', function (e) {
    let valid = true;

    const title = document.getElementById('title');
    if (title && !title.value.trim()) {
      markError(title, 'Property title is required.');
      valid = false;
    } else if (title) clearError(title);

    const price = document.getElementById('price_per_month');
    if (price && (!price.value || isNaN(parseFloat(price.value)))) {
      markError(price, 'A valid monthly price is required.');
      valid = false;
    } else if (price) clearError(price);

    const address = document.getElementById('address');
    if (address && !address.value.trim()) {
      markError(address, 'Address is required.');
      valid = false;
    } else if (address) clearError(address);

    if (!valid) {
      e.preventDefault();
      // Restore button
      if (subBtn) {
        subBtn.querySelector('.btn-text').style.display    = '';
        subBtn.querySelector('.btn-spinner').style.display = 'none';
        subBtn.disabled = false;
      }
      // Scroll to first error
      const firstErr = document.querySelector('.has-error');
      if (firstErr) firstErr.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, true); // capture phase so we can cancel before the submit handler
}

function markError(input, msg) {
  const group = input.closest('.field-group');
  if (group) {
    group.classList.add('has-error');
    let errEl = group.querySelector('.field-error');
    if (!errEl) { errEl = document.createElement('span'); errEl.className = 'field-error'; group.appendChild(errEl); }
    errEl.textContent = msg;
  }
  input.classList.add('is-invalid');
}
function clearError(input) {
  const group = input.closest('.field-group');
  if (group) {
    group.classList.remove('has-error');
    const errEl = group.querySelector('.field-error');
    if (errEl) errEl.textContent = '';
  }
  input.classList.remove('is-invalid');
}

// ── Sidebar toggle ───────────────────────────────────────────
const toggleBtn = document.getElementById('sidebar-toggle');
const sidebar   = document.getElementById('sidebar');
if (toggleBtn && sidebar) {
  toggleBtn.addEventListener('click', () => {
    if (window.innerWidth <= 768) {
      sidebar.classList.toggle('mobile-open');
    } else {
      sidebar.classList.toggle('collapsed');
    }
  });
  document.addEventListener('click', e => {
    if (window.innerWidth <= 768 &&
        !sidebar.contains(e.target) &&
        !toggleBtn.contains(e.target)) {
      sidebar.classList.remove('mobile-open');
    }
  });
}


// ── Image upload (Section 6) ─────────────────────────────────

const MAX_IMAGES = 10;
const MAX_SIZE   = 5 * 1024 * 1024; // 5 MB per file

const uploadZone    = document.getElementById('upload-zone');
const imagesInput   = document.getElementById('images-input');
const previewGrid   = document.getElementById('img-preview-grid');

// Track new files in a DataTransfer so we can rebuild the file input
let fileQueue = new DataTransfer();

function refreshInput() {
  if (imagesInput) imagesInput.files = fileQueue.files;
}

function totalExistingCount() {
  const grid = document.getElementById('existing-thumb-grid');
  return grid ? grid.querySelectorAll('.img-thumb-item').length : 0;
}

function addFiles(newFiles) {
  const remaining = MAX_IMAGES - totalExistingCount() - fileQueue.files.length;
  let added = 0;
  Array.from(newFiles).forEach(file => {
    if (added >= remaining) return;
    if (!file.type.match(/^image\/(jpeg|png|webp)$/)) return;
    if (file.size > MAX_SIZE) {
      alert(`"${file.name}" exceeds 5 MB and was skipped.`);
      return;
    }
    fileQueue.items.add(file);
    renderPreview(file, fileQueue.files.length - 1);
    added++;
  });
  refreshInput();
  if (previewGrid) previewGrid.style.display = fileQueue.files.length ? '' : 'none';
}

function renderPreview(file, idx) {
  if (!previewGrid) return;
  const reader = new FileReader();
  reader.onload = e => {
    const item = document.createElement('div');
    item.className = 'img-preview-item';
    item.dataset.idx = idx;
    item.innerHTML = `
      <img src="${e.target.result}" alt="Preview" />
      <span class="img-new-badge">New</span>
      <button type="button" class="img-remove-new" title="Remove">×</button>
    `;
    item.querySelector('.img-remove-new').addEventListener('click', () => removePreview(idx));
    previewGrid.appendChild(item);
  };
  reader.readAsDataURL(file);
}

function removePreview(idx) {
  // Rebuild DataTransfer without removed file
  const newDT = new DataTransfer();
  Array.from(fileQueue.files).forEach((f, i) => {
    if (i !== idx) newDT.items.add(f);
  });
  fileQueue = newDT;
  refreshInput();

  // Re-render all previews
  if (!previewGrid) return;
  previewGrid.innerHTML = '';
  Array.from(fileQueue.files).forEach((f, i) => renderPreview(f, i));
  previewGrid.style.display = fileQueue.files.length ? '' : 'none';
}

// Drag-and-drop
if (uploadZone) {
  uploadZone.addEventListener('dragover', e => {
    e.preventDefault();
    uploadZone.classList.add('drag-over');
  });
  uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('drag-over'));
  uploadZone.addEventListener('drop', e => {
    e.preventDefault();
    uploadZone.classList.remove('drag-over');
    addFiles(e.dataTransfer.files);
  });
  uploadZone.addEventListener('click', e => {
    if (e.target.closest('.upload-browse-btn')) return; // handled by onclick
    imagesInput && imagesInput.click();
  });
}

if (imagesInput) {
  imagesInput.addEventListener('change', () => {
    const files = Array.from(imagesInput.files); // capture before any reset
    imagesInput.value = '';                       // reset so same file can be re-selected later
    addFiles(files);                              // adds to queue; refreshInput sets imagesInput.files last
  });
}

// Delete existing image (AJAX)
async function deleteExistingImage(imgId, propId) {
  if (!confirm('Delete this photo?')) return;
  try {
    const res = await fetch(`/accommodation/landlord/property/${propId}/image/${imgId}/delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    if (res.ok) {
      const el = document.getElementById(`img-${imgId}`);
      if (el) el.remove();
    } else {
      alert('Failed to delete photo. Please try again.');
    }
  } catch {
    alert('Network error. Please try again.');
  }
}

// Set cover image (AJAX)
async function setCover(imgId, propId) {
  try {
    const res = await fetch(`/accommodation/landlord/property/${propId}/image/${imgId}/set-cover`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    if (res.ok) {
      // Update UI: clear existing badges, add to this item, remove set-cover btn
      document.querySelectorAll('.img-cover-badge').forEach(b => b.remove());
      document.querySelectorAll('.img-set-cover-btn').forEach(b => b.remove());
      const item = document.getElementById(`img-${imgId}`);
      if (item) {
        const badge = document.createElement('span');
        badge.className = 'img-cover-badge';
        badge.textContent = 'Cover';
        item.appendChild(badge);
      }
    } else {
      alert('Failed to set cover. Please try again.');
    }
  } catch {
    alert('Network error. Please try again.');
  }
}
