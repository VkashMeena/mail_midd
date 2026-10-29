/**
 * AI Smart Mail Manager — AI Assistant UI & Loading States
 */

document.addEventListener('DOMContentLoaded', () => {
  // --------------------------------------------------------------------------
  // Summary Generation Simulated Loading State (Phase 1 UI demonstration)
  // --------------------------------------------------------------------------
  const generateSummaryBtn = document.getElementById('generateSummaryBtn');
  const summaryResultBox = document.getElementById('summaryResultBox');

  if (generateSummaryBtn && summaryResultBox) {
    generateSummaryBtn.addEventListener('click', (e) => {
      e.preventDefault();

      // Switch to Loading state
      generateSummaryBtn.disabled = true;
      const originalHtml = generateSummaryBtn.innerHTML;
      generateSummaryBtn.innerHTML = `
        <span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
        Generating Summary...
      `;

      setTimeout(() => {
        // Success state
        generateSummaryBtn.innerHTML = `<i class="bi bi-check-lg me-2"></i> Summary Updated`;
        generateSummaryBtn.classList.remove('btn-primary');
        generateSummaryBtn.classList.add('btn-success');

        if (window.showToast) {
          window.showToast('AI Summary Ready', 'Executive digest refreshed successfully (Phase 1 UI Preview).', 'success');
        }

        setTimeout(() => {
          generateSummaryBtn.disabled = false;
          generateSummaryBtn.innerHTML = originalHtml;
          generateSummaryBtn.classList.remove('btn-success');
          generateSummaryBtn.classList.add('btn-primary');
        }, 2500);
      }, 900);
    });
  }

  // --------------------------------------------------------------------------
  // AI Reply Tone Switcher & Preview Generator
  // --------------------------------------------------------------------------
  const tonePills = document.querySelectorAll('.tone-pill-btn');
  const replyOutput = document.getElementById('aiReplyOutput');
  const emailSelect = document.getElementById('aiReplyEmailSelect');
  const generateReplyBtn = document.getElementById('generateReplyBtn');

  async function updateReplyPreview(tone) {
    const emailId = emailSelect ? emailSelect.value : '';
    if (!replyOutput) return;

    if (generateReplyBtn) {
      generateReplyBtn.disabled = true;
      generateReplyBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-2"></span> Drafting...`;
    }

    try {
      const response = await fetch(`/ai/reply/preview/?email_id=${emailId}&tone=${tone}`);
      if (response.ok) {
        const data = await response.json();
        replyOutput.value = data.reply;
      }
    } catch (err) {
      console.warn('Reply preview fetch failed:', err);
    } finally {
      if (generateReplyBtn) {
        generateReplyBtn.disabled = false;
        generateReplyBtn.innerHTML = `<i class="bi bi-stars me-2"></i> Regenerate Reply`;
      }
    }
  }

  tonePills.forEach((pill) => {
    pill.addEventListener('click', () => {
      tonePills.forEach((p) => p.classList.remove('active', 'btn-primary'));
      tonePills.forEach((p) => p.classList.add('btn-outline-primary'));

      pill.classList.remove('btn-outline-primary');
      pill.classList.add('active', 'btn-primary');

      const selectedTone = pill.dataset.tone;
      updateReplyPreview(selectedTone);
    });
  });

  if (emailSelect) {
    emailSelect.addEventListener('change', () => {
      const activeToneBtn = document.querySelector('.tone-pill-btn.active');
      const currentTone = activeToneBtn ? activeToneBtn.dataset.tone : 'Professional';
      updateReplyPreview(currentTone);
    });
  }

  if (generateReplyBtn) {
    generateReplyBtn.addEventListener('click', (e) => {
      e.preventDefault();
      const activeToneBtn = document.querySelector('.tone-pill-btn.active');
      const currentTone = activeToneBtn ? activeToneBtn.dataset.tone : 'Professional';
      updateReplyPreview(currentTone);
    });
  }

  // Copy reply button
  const copyReplyBtn = document.getElementById('copyReplyBtn');
  if (copyReplyBtn && replyOutput) {
    copyReplyBtn.addEventListener('click', () => {
      replyOutput.select();
      navigator.clipboard.writeText(replyOutput.value).then(() => {
        if (window.showToast) {
          window.showToast('Copied!', 'Reply draft copied to clipboard.', 'success');
        }
      });
    });
  }

  // Quick Action Buttons (Phase 1 alert indicator)
  document.querySelectorAll('.phase1-demo-btn').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const feature = btn.dataset.feature || 'This action';
      if (window.showToast) {
        window.showToast(
          'Phase 1 Architecture Preview',
          `${feature} is scheduled for activation in future phases.`,
          'info'
        );
      }
    });
  });
});
