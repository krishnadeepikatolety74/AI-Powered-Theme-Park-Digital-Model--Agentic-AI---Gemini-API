/**
 * ParkOps Theme Park Digital Model - Frontend JavaScript
 */

document.addEventListener('DOMContentLoaded', () => {
  initPasswordToggles();
  initForgotPasswordModal();
  initWhatIfSimulator();
});

/* ==========================================
   1. PASSWORD VISIBILITY TOGGLE
   ========================================== */
function initPasswordToggles() {
  const toggleButtons = document.querySelectorAll('.password-toggle-btn');
  toggleButtons.forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const targetId = btn.getAttribute('data-target');
      const input = document.getElementById(targetId);
      if (!input) return;

      if (input.type === 'password') {
        input.type = 'text';
        btn.innerHTML = `
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
            <line x1="1" y1="1" x2="23" y2="23"></line>
          </svg>`;
      } else {
        input.type = 'password';
        btn.innerHTML = `
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
            <circle cx="12" cy="12" r="3"></circle>
          </svg>`;
      }
    });
  });
}

/* ==========================================
   2. FORGOT PASSWORD MODAL FLOW
   ========================================== */
function initForgotPasswordModal() {
  const trigger = document.getElementById('forgotPasswordTrigger');
  const modal = document.getElementById('forgotPasswordModal');
  const closeBtn = document.getElementById('closeForgotModal');
  const form = document.getElementById('forgotPasswordForm');
  const feedback = document.getElementById('forgotModalFeedback');

  if (trigger && modal) {
    trigger.addEventListener('click', (e) => {
      e.preventDefault();
      modal.classList.add('active');
    });
  }

  if (closeBtn && modal) {
    closeBtn.addEventListener('click', () => {
      modal.classList.remove('active');
    });
  }

  if (modal) {
    modal.addEventListener('click', (e) => {
      if (e.target === modal) {
        modal.classList.remove('active');
      }
    });
  }

  if (form && feedback) {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const emailInput = document.getElementById('forgotEmailInput');
      const email = emailInput ? emailInput.value.trim() : '';

      if (!email) {
        feedback.className = 'alert-box alert-danger';
        feedback.textContent = 'Please enter a valid email address.';
        feedback.style.display = 'block';
        return;
      }

      feedback.className = 'alert-box alert-success';
      feedback.textContent = 'Verifying account...';
      feedback.style.display = 'block';

      try {
        const formData = new FormData();
        formData.append('email', email);

        const response = await fetch('/forgot-password', {
          method: 'POST',
          body: formData
        });
        const result = await response.json();

        if (result.success) {
          feedback.className = 'alert-box alert-success';
          feedback.textContent = result.message;
          if (emailInput) emailInput.value = '';
        } else {
          feedback.className = 'alert-box alert-danger';
          feedback.textContent = result.message || 'Error checking email.';
        }
      } catch (err) {
        feedback.className = 'alert-box alert-danger';
        feedback.textContent = 'Connection error. Please try again.';
      }
    });
  }
}

/* ==========================================
   3. WHAT-IF DIGITAL MODEL SIMULATOR
   ========================================== */
function initWhatIfSimulator() {
  const simForm = document.getElementById('whatIfForm');
  const runBtn = document.getElementById('runSimBtn');

  if (!simForm) return;

  simForm.addEventListener('submit', async (e) => {
    e.preventDefault();

    const additionalVisitors = parseInt(document.getElementById('simVisitors').value) || 0;
    const timePeriod = document.getElementById('simTimePeriod').value;
    const rideAvailability = document.getElementById('simRideStatus').value;
    const weatherCondition = document.getElementById('simWeather').value;

    if (runBtn) {
      runBtn.disabled = true;
      runBtn.innerHTML = '<span>⚡ Simulating Model...</span>';
    }

    try {
      const response = await fetch('/api/simulate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          additional_visitors: additionalVisitors,
          time_period: timePeriod,
          ride_availability: rideAvailability,
          weather_condition: weatherCondition
        })
      });

      const result = await response.json();

      const summaryEl = document.getElementById('resSituationSummary');
      const recEl = document.getElementById('resRecommendationText');
      const badgeEl = document.getElementById('resAiEngineBadge');

      if (summaryEl && result.situation_summary) {
        summaryEl.textContent = result.situation_summary;
      }
      if (recEl && result.recommendation) {
        recEl.textContent = result.recommendation;
      }
      if (badgeEl && result.ai_source) {
        badgeEl.textContent = `Powered by ${result.ai_source}`;
      }
    } catch (err) {
      alert('Error running simulation. Please check server logs.');
    } finally {
      if (runBtn) {
        runBtn.disabled = false;
        runBtn.innerHTML = 'Run Simulation';
      }
    }
  });
}
