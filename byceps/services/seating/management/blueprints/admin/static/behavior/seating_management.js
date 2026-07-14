(() => {
  function initializeSeatManagement() {
    const root = document.getElementById('seat-management');
    if (root === null) {
      return;
    }

    const seats = Array.from(root.querySelectorAll('.seat-management-seat'));
    const status = document.getElementById('seat-management-status');
    const resetButton = document.getElementById('seat-management-reset');
    const tooltip = document.getElementById('seat-management-tooltip');
    const tooltipLabel = document.getElementById('seat-management-tooltip-label');
    const tooltipParticipant = document.getElementById('seat-management-tooltip-participant');
    const tooltipAvatar = document.getElementById('seat-management-tooltip-avatar');
    const tooltipName = document.getElementById('seat-management-tooltip-name');
    const participantSearch = document.getElementById('seat-management-participant-search');
    const participantSearchInput = document.getElementById('seat-management-participant-search-input');
    const participantSearchStatus = document.getElementById('seat-management-participant-search-status');
    const participantSearchResults = document.getElementById('seat-management-participant-search-results');
    const searchableSeats = seats.filter(seat => (
      seat.dataset.canMoveSource === 'true'
      && seat.dataset.occupierName !== undefined
    ));
    let sourceSeat = null;
    let targetSeat = null;
    let activeTooltipSeat = null;
    let focusedTooltipSeat = null;
    let hoveredTooltipSeat = null;
    let tooltipHideTimeout = null;

    function clearTooltipHideTimeout() {
      if (tooltipHideTimeout !== null) {
        window.clearTimeout(tooltipHideTimeout);
        tooltipHideTimeout = null;
      }
    }

    function positionTooltip() {
      if (activeTooltipSeat === null || tooltip.hidden) {
        return;
      }

      const viewportMargin = 8;
      const gap = 4;
      const seatRect = activeTooltipSeat.getBoundingClientRect();
      const tooltipRect = tooltip.getBoundingClientRect();
      let left = seatRect.left + (seatRect.width - tooltipRect.width) / 2;
      left = Math.max(
        viewportMargin,
        Math.min(left, window.innerWidth - tooltipRect.width - viewportMargin),
      );

      let top = seatRect.top - tooltipRect.height - gap;
      if (top < viewportMargin) {
        top = seatRect.bottom + gap;
      }
      top = Math.max(
        viewportMargin,
        Math.min(top, window.innerHeight - tooltipRect.height - viewportMargin),
      );

      tooltip.style.left = `${left}px`;
      tooltip.style.top = `${top}px`;
    }

    function showTooltip(seat) {
      clearTooltipHideTimeout();
      activeTooltipSeat = seat;
      tooltipLabel.textContent = seat.dataset.seatLabel;

      const occupierName = seat.dataset.occupierName;
      const occupierAvatar = seat.dataset.occupierAvatar;
      if (occupierName === undefined || occupierAvatar === undefined) {
        tooltipParticipant.hidden = true;
        tooltipAvatar.removeAttribute('src');
        tooltipName.textContent = '';
      } else {
        tooltipAvatar.src = occupierAvatar;
        tooltipName.textContent = occupierName;
        tooltipParticipant.hidden = false;
      }

      tooltip.hidden = false;
      positionTooltip();
    }

    function hideTooltip() {
      clearTooltipHideTimeout();
      activeTooltipSeat = null;
      tooltip.hidden = true;
    }

    function scheduleTooltipTransition() {
      clearTooltipHideTimeout();
      tooltipHideTimeout = window.setTimeout(() => {
        tooltipHideTimeout = null;
        const fallbackSeat = hoveredTooltipSeat ?? focusedTooltipSeat;
        if (fallbackSeat === null) {
          hideTooltip();
        } else {
          showTooltip(fallbackSeat);
        }
      }, 100);
    }

    function repositionActiveTooltip() {
      if (activeTooltipSeat !== null) {
        window.requestAnimationFrame(positionTooltip);
      }
    }

    function formatStatus(template, seat) {
      return template.replace('{label}', () => seat.dataset.seatLabel);
    }

    function announce(templateName, seat) {
      status.textContent = formatStatus(root.dataset[templateName], seat);
    }

    function setSelectValue(selectId, value) {
      const select = document.getElementById(selectId);
      if (select === null) {
        return false;
      }

      const option = Array.from(select.options)
        .find(candidate => candidate.value === value);
      if (option === undefined) {
        return false;
      }

      select.value = value;
      return true;
    }

    function updateGraphicalSelection() {
      seats.forEach(seat => {
        const isSource = seat === sourceSeat;
        const isTarget = seat === targetSeat;
        seat.classList.toggle('seat-management-seat--source', isSource);
        seat.classList.toggle('seat-management-seat--target', isTarget);
        seat.setAttribute('aria-pressed', String(isSource || isTarget));
      });
    }

    function clearSelects(selectIds) {
      selectIds.forEach(selectId => setSelectValue(selectId, ''));
    }

    function selectSource(seat) {
      clearSelects([
        'move-source-seat-id',
        'move-target-seat-id',
        'swap-source-seat-id',
        'swap-target-seat-id',
        'block-seat-id',
        'unblock-seat-id',
      ]);
      sourceSeat = seat;
      targetSeat = null;
      setSelectValue('move-source-seat-id', seat.dataset.seatId);
      setSelectValue('swap-source-seat-id', seat.dataset.seatId);
      updateGraphicalSelection();
      announce('statusSource', seat);
    }

    function selectMoveTarget(seat) {
      clearSelects([
        'swap-target-seat-id',
        'block-seat-id',
        'unblock-seat-id',
      ]);
      targetSeat = seat;
      setSelectValue('move-target-seat-id', seat.dataset.seatId);
      updateGraphicalSelection();
      announce('statusMoveTarget', seat);
    }

    function selectSwapTarget(seat) {
      clearSelects([
        'move-target-seat-id',
        'block-seat-id',
        'unblock-seat-id',
      ]);
      targetSeat = seat;
      setSelectValue('swap-target-seat-id', seat.dataset.seatId);
      updateGraphicalSelection();
      announce('statusSwapTarget', seat);
    }

    function selectSingleSeat(selectId, statusName, seat) {
      clearSelects([
        'move-source-seat-id',
        'move-target-seat-id',
        'swap-source-seat-id',
        'swap-target-seat-id',
        'block-seat-id',
        'unblock-seat-id',
      ]);
      sourceSeat = null;
      targetSeat = seat;
      setSelectValue(selectId, seat.dataset.seatId);
      updateGraphicalSelection();
      announce(statusName, seat);
    }

    function resetSelection() {
      sourceSeat = null;
      targetSeat = null;
      clearSelects([
        'move-source-seat-id',
        'move-target-seat-id',
        'swap-source-seat-id',
        'swap-target-seat-id',
        'block-seat-id',
        'unblock-seat-id',
      ]);
      updateGraphicalSelection();
      status.textContent = root.dataset.statusEmpty;
    }

    function clearTargetSelection() {
      if (sourceSeat === null) {
        resetSelection();
        return;
      }

      targetSeat = null;
      clearSelects([
        'move-target-seat-id',
        'swap-target-seat-id',
        'block-seat-id',
        'unblock-seat-id',
      ]);
      updateGraphicalSelection();
      announce('statusSource', sourceSeat);
    }

    function clearParticipantSearchResults() {
      participantSearchResults.replaceChildren();
      participantSearchResults.hidden = true;
      participantSearchStatus.textContent = '';
      participantSearchStatus.hidden = true;
    }

    function selectParticipantSeat(seat) {
      selectSource(seat);
      participantSearchInput.value = seat.dataset.occupierName;
      clearParticipantSearchResults();
      seat.focus({ preventScroll: true });
      seat.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    }

    function updateParticipantSearchResults() {
      clearParticipantSearchResults();

      const searchTerm = participantSearchInput.value
        .trim()
        .toLocaleLowerCase();
      if (searchTerm === '') {
        return;
      }

      const matches = searchableSeats.filter(seat => (
        seat.dataset.occupierName.toLocaleLowerCase().includes(searchTerm)
      ));
      if (matches.length === 0) {
        participantSearchStatus.textContent = root.dataset.searchNoResults;
        participantSearchStatus.hidden = false;
        return;
      }

      const resultCounts = new Map();
      matches.forEach(seat => {
        const resultKey = `${seat.dataset.occupierName}\u0000${seat.dataset.seatLabel}`;
        resultCounts.set(resultKey, (resultCounts.get(resultKey) ?? 0) + 1);
      });
      const resultIndexes = new Map();
      matches.forEach(seat => {
        const item = document.createElement('li');
        const button = document.createElement('button');
        const participantName = document.createElement('strong');
        const seatLabel = document.createElement('span');
        const resultKey = `${seat.dataset.occupierName}\u0000${seat.dataset.seatLabel}`;
        const resultCount = resultCounts.get(resultKey);
        const resultIndex = (resultIndexes.get(resultKey) ?? 0) + 1;
        resultIndexes.set(resultKey, resultIndex);
        const disambiguator = resultCount > 1
          ? ` (${resultIndex}/${resultCount})`
          : '';
        const translatedSeatLabel = `${root.dataset.searchSeatLabel} ${seat.dataset.seatLabel}${disambiguator}`;

        button.type = 'button';
        button.className = 'seat-management-participant-search-result';
        button.setAttribute(
          'aria-label',
          `${seat.dataset.occupierName}, ${translatedSeatLabel}`,
        );
        button.addEventListener('click', () => selectParticipantSeat(seat));
        participantName.textContent = seat.dataset.occupierName;
        seatLabel.textContent = translatedSeatLabel;
        button.append(participantName, seatLabel);
        item.append(button);
        participantSearchResults.append(item);
      });
      participantSearchResults.hidden = false;
    }

    seats.forEach(seat => {
      seat.addEventListener('mouseenter', () => {
        hoveredTooltipSeat = seat;
        showTooltip(seat);
      });
      seat.addEventListener('mouseleave', () => {
        if (hoveredTooltipSeat === seat) {
          hoveredTooltipSeat = null;
        }
        scheduleTooltipTransition();
      });
      seat.addEventListener('focus', () => {
        focusedTooltipSeat = seat;
        showTooltip(seat);
      });
      seat.addEventListener('blur', () => {
        if (focusedTooltipSeat === seat) {
          focusedTooltipSeat = null;
        }
        scheduleTooltipTransition();
      });
      seat.addEventListener('click', () => {
        clearParticipantSearchResults();

        if (seat === sourceSeat) {
          resetSelection();
          return;
        }
        if (seat === targetSeat) {
          clearTargetSelection();
          return;
        }

        const occupied = seat.dataset.occupied === 'true';

        if (occupied) {
          if (
            sourceSeat !== null
            && sourceSeat !== seat
            && sourceSeat.dataset.canSwap === 'true'
            && seat.dataset.canSwap === 'true'
          ) {
            selectSwapTarget(seat);
          } else if (seat.dataset.canMoveSource === 'true') {
            selectSource(seat);
          } else if (seat.dataset.canUnblock === 'true') {
            selectSingleSeat('unblock-seat-id', 'statusUnblock', seat);
          } else {
            announce('statusUnavailable', seat);
          }
          return;
        }

        if (seat.dataset.canUnblock === 'true') {
          selectSingleSeat('unblock-seat-id', 'statusUnblock', seat);
        } else if (
          sourceSeat !== null
          && seat.dataset.canMoveTarget === 'true'
        ) {
          selectMoveTarget(seat);
        } else if (seat.dataset.canBlock === 'true') {
          selectSingleSeat('block-seat-id', 'statusBlock', seat);
        } else {
          announce('statusUnavailable', seat);
        }
      });

      seat.disabled = false;
    });

    resetButton.addEventListener('click', resetSelection);
    resetButton.disabled = false;

    participantSearchInput.addEventListener(
      'input',
      updateParticipantSearchResults,
    );
    participantSearchInput.addEventListener(
      'focus',
      updateParticipantSearchResults,
    );
    participantSearch.hidden = false;

    document.addEventListener('keydown', event => {
      if (event.key !== 'Escape') {
        return;
      }

      if (sourceSeat !== null || targetSeat !== null) {
        resetSelection();
      }
      if (activeTooltipSeat !== null) {
        hideTooltip();
      }
    });
    window.addEventListener('scroll', repositionActiveTooltip, true);
    window.addEventListener('resize', repositionActiveTooltip);
  }

  onDomReady(initializeSeatManagement);
})();
