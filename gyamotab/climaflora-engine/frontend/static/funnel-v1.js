(() => {
  'use strict';

  function card(title, step, className) {
    const section = document.createElement('section');
    section.className = `search-card ${className}`;
    section.innerHTML = `<div class="card-title-row"><strong>${title}</strong><span>${step}</span></div>`;
    return section;
  }

  function installFunnelLayout() {
    const grid = document.querySelector('.search-grid');
    const mapCard = grid?.querySelector('.map-search-card');
    const typeCard = grid?.querySelector('.type-card');
    const climateCard = grid?.querySelector('.climate-card');
    const functions = document.getElementById('functions');
    const functionDetails = typeCard?.querySelector('.function-filter-details');
    const advanced = typeCard?.querySelector('.advanced-controls');
    if (!grid || !mapCard || !typeCard || !climateCard || !functions || !advanced) return;
    if (grid.dataset.funnelV1 === '1') return;
    grid.dataset.funnelV1 = '1';

    const progress = document.querySelector('.progress-row');
    if (progress) {
      progress.innerHTML = `
        <div class="progress-step"><span>1</span>Localisation</div><i></i>
        <div class="progress-step"><span>2</span>Type de végétaux</div><i></i>
        <div class="progress-step"><span>3</span>Fonction documentée</div><i></i>
        <div class="progress-step"><span>4</span>Climat</div><i></i>
        <div class="progress-step"><span>5</span>Sol</div>`;
      progress.classList.add('progress-row-five');
    }

    const typeStep = typeCard.querySelector('.card-title-row span');
    if (typeStep) typeStep.textContent = '2';
    const typeHelp = typeCard.querySelector('.field-help');
    if (typeHelp) typeHelp.textContent = 'Premier filtre d’éligibilité : seules les formes biologiques sélectionnées passent à l’étape suivante.';

    const functionCard = card('Fonction documentée', '3', 'function-card');
    const functionHelp = document.createElement('p');
    functionHelp.className = 'field-help';
    functionHelp.textContent = 'Deuxième filtre d’éligibilité. Les usages restent descriptifs et ne modifient jamais le score scientifique.';
    functionCard.appendChild(functionHelp);
    functionCard.appendChild(functions);
    if (functionDetails) functionDetails.remove();

    const climateStep = climateCard.querySelector('.card-title-row span');
    if (climateStep) climateStep.textContent = '4';
    const climateTitle = climateCard.querySelector('.card-title-row strong');
    if (climateTitle) climateTitle.textContent = 'Climat actuel / futur';

    const soilCard = card('Sol local', '5', 'soil-card');
    const soilIntro = document.createElement('p');
    soilIntro.className = 'field-help';
    soilIntro.textContent = 'Dernier axe de classement : le sol local peut être estimé puis corrigé avec vos valeurs. Il ne peut pas rendre compatible un climat incompatible.';
    soilCard.appendChild(soilIntro);
    const advancedInner = advanced.querySelector('.advanced-inner');
    if (advancedInner) soilCard.appendChild(advancedInner);
    advanced.remove();

    // Location is context. The scientific funnel then reads left-to-right/top-to-bottom:
    // Type -> Function -> Climate -> Soil.
    grid.replaceChildren(mapCard, typeCard, functionCard, climateCard, soilCard);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', installFunnelLayout);
  else installFunnelLayout();
})();
