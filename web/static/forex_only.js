/* Active product mode: Real Forex only. */
(() => {
  const mode = document.getElementById('mode');
  const pair = document.getElementById('pair');
  if (!mode || !pair) return;

  mode.value = 'real';

  document.querySelectorAll('.mode-btn').forEach(button => {
    if (button.dataset.mode === 'crypto') {
      button.remove();
    } else if (button.dataset.mode === 'real') {
      button.classList.add('active');
    }
  });

  Array.from(pair.options).forEach(option => {
    if (option.dataset.market === 'crypto') option.remove();
  });

  const selected = pair.options[pair.selectedIndex];
  if (!selected || selected.dataset.market !== 'real') {
    pair.value = '';
  }

  localStorage.removeItem('mmc_selected_mode');
  localStorage.removeItem('mmc_selected_crypto_pair');
})();
