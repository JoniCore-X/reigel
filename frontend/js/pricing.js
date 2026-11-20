(() => {
  'use strict';

  const vendors = document.getElementById('pricing-vendors');
  const teams = document.getElementById('pricing-teams');
  const vendorsValue = document.getElementById('pricing-vendors-value');
  const teamsValue = document.getElementById('pricing-teams-value');
  const totalVendors = document.getElementById('pricing-total-vendors');
  const plan = document.getElementById('pricing-plan');
  const monthly = document.getElementById('pricing-monthly');
  const annual = document.getElementById('pricing-annual');
  const formulaLabel = document.getElementById('pricing-formula-label');
  const perTeam = document.getElementById('pricing-per-team');
  const teamsResult = document.getElementById('pricing-teams-result');
  const reset = document.getElementById('pricing-reset');

  if (!vendors || !teams || !monthly || !annual) return;

  const BASE = 149;
  const INCLUDED = 5;
  const EXTRA = 20;
  const PRO = 299;
  const PRO_FROM = 13;
  const MAX_VENDORS = 15;

  const money = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0
  });

  function teamPrice(count) {
    if (count >= PRO_FROM) {
      return { name: 'Team Pro', price: PRO, extras: 0, label: 'Team Pro · tarifa fija' };
    }
    if (count <= INCLUDED) {
      return { name: 'Team Caguas', price: BASE, extras: 0, label: 'Team Caguas · base' };
    }
    const extras = count - INCLUDED;
    return {
      name: 'Team Caguas',
      price: BASE + extras * EXTRA,
      extras,
      label: `Team Caguas + ${extras} adicional${extras === 1 ? '' : 'es'}`
    };
  }

  function describe(count, max) {
    const pct = ((count - 1) / (max - 1)) * 100;
    return `${pct}%`;
  }

  function update() {
    const count = Math.min(MAX_VENDORS, Math.max(1, Number(vendors.value) || 1));
    const teamCount = Math.max(1, Number(teams.value) || 1);
    const team = teamPrice(count);
    const total = team.price * teamCount;

    vendors.value = String(count);
    teams.value = String(teamCount);
    vendorsValue.textContent = String(count);
    teamsValue.textContent = String(teamCount);
    totalVendors.textContent = String(count * teamCount);
    plan.textContent = `Plan ${team.name}`;
    monthly.textContent = money.format(total);
    annual.textContent = money.format(total * 12);
    formulaLabel.textContent = team.label;
    perTeam.textContent = `${money.format(team.price)} por equipo`;
    teamsResult.textContent = String(teamCount);
    vendors.setAttribute('aria-valuetext', `${count} vendedores por equipo`);
    teams.setAttribute('aria-valuetext', `${teamCount} equipo${teamCount === 1 ? '' : 's'}`);
    vendors.style.setProperty('--pricing-fill', describe(count, MAX_VENDORS));
    teams.style.setProperty('--pricing-fill', describe(teamCount, 10));
  }

  vendors.addEventListener('input', update);
  teams.addEventListener('input', update);
  if (reset) {
    reset.addEventListener('click', () => {
      vendors.value = '8';
      teams.value = '1';
      update();
      vendors.focus();
    });
  }

  update();
})();
