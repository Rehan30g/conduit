// dashboard.js - Core JavaScript logic for the Conduit Web Dashboard
// This logic runs independently of the HTML/CSS presentation layer.

function copyPrompt() {
  navigator.clipboard.writeText(CONFIG.copyPrompt).then(() => {
    const btn = document.getElementById('copy-btn');
    const orig = btn.innerHTML;
    btn.textContent = '✓ Copied!';
    btn.className = 'btn btn-ok';
    setTimeout(() => {
      btn.innerHTML = orig;
      btn.className = 'btn btn-p';
    }, 2500);
  });
}

function copyToken() {
  navigator.clipboard.writeText(CONFIG.token).then(() => {
    const btn = document.getElementById('tok-btn');
    const orig = btn.textContent;
    btn.textContent = '✓ Copied!';
    setTimeout(() => {
      btn.textContent = orig;
    }, 2000);
  });
}

function fmtUptime(s) {
  if (s < 60) return s + 's';
  if (s < 3600) return Math.floor(s/60) + 'm ' + (s%60) + 's';
  return Math.floor(s/3600) + 'h ' + Math.floor((s%3600)/60) + 'm';
}

function refresh() {
  fetch('/status')
    .then(r => r.json())
    .then(d => {
      document.getElementById('uptime').textContent = fmtUptime(d.uptime_seconds);
      document.getElementById('queue').textContent = d.queue_depth;
      const banner = document.getElementById('danger-banner');
      if (d.always_allow_active) {
        banner.style.display = 'block';
      } else {
        banner.style.display = 'none';
      }
    })
    .catch(() => {
      // Fallback: display the offline/disconnected screen overlay
      const overlay = document.getElementById('offline-overlay');
      if (overlay) {
        overlay.style.display = 'flex';
      }
    });
}

// Initial pull on load, then poll every 2 seconds
refresh();
setInterval(refresh, 2000);
