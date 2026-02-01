/**
 * Initialize the seating relocate selection UI in admin.
 */
function init_seat_admin_relocate() {
  const seatContainers = Array.from(document.querySelectorAll('.seat-with-tooltip'));
  if (seatContainers.length === 0) {
    return;
  }

  const sourceInfo = document.getElementById('relocate-source-info');
  const targetInfo = document.getElementById('relocate-target-info');
  const clearTrigger = document.getElementById('relocate-clear-selection');
  const searchInput = document.getElementById('relocate-search-input');
  const sourceInfoMain = sourceInfo !== null ? sourceInfo.querySelector('.relocate-info__main') : null;
  const sourceInfoTicket = sourceInfo !== null ? sourceInfo.querySelector('.relocate-info__ticket') : null;
  const targetInfoMain = targetInfo !== null ? targetInfo.querySelector('.relocate-info__main') : null;
  const targetInfoTicket = targetInfo !== null ? targetInfo.querySelector('.relocate-info__ticket') : null;

  const modal = document.getElementById('relocate-preview-modal');
  const modalTitle = document.getElementById('relocate-preview-title');
  const modalMessage = document.getElementById('relocate-preview-message');
  const modalWarning = document.getElementById('relocate-preview-swap-warning');
  const modalCancel = document.getElementById('relocate-preview-cancel');
  const modalOk = document.getElementById('relocate-preview-ok');
  const modalBackdrop = document.getElementById('relocate-preview-backdrop');
  const relocateForm = document.getElementById('relocate-form');
  const ticketIdInput = document.getElementById('relocate-ticket-id');
  const targetSeatIdInput = document.getElementById('relocate-target-seat-id');
  const sourceSeatIdInput = document.getElementById('relocate-source-seat-id');
  const targetTicketIdInput = document.getElementById('relocate-target-ticket-id');
  const modeInput = document.getElementById('relocate-mode');

  if (sourceInfo === null || targetInfo === null || clearTrigger === null) {
    return;
  }

  if (sourceInfoMain === null || sourceInfoTicket === null || targetInfoMain === null || targetInfoTicket === null) {
    return;
  }

  let sourceSeat = null;
  let targetSeat = null;
  let modalOpen = false;

  function is_occupied(seatContainer) {
    return seatContainer.dataset.ticketId !== undefined;
  }

  function get_seat_label(seatContainer) {
    return seatContainer.dataset.label;
  }

  function get_ticket_id(seatContainer) {
    return seatContainer.dataset.ticketId;
  }

  function get_seat_id(seatContainer) {
    return seatContainer.dataset.seatId;
  }

  function get_occupier_name(seatContainer) {
    return seatContainer.dataset.occupierName;
  }

  function format_occupier_label(seatContainer) {
    const occupierName = get_occupier_name(seatContainer);
    if (occupierName !== undefined && occupierName !== '') {
      return occupierName;
    }

    const ticketId = get_ticket_id(seatContainer);
    if (ticketId !== undefined && ticketId !== '') {
      return 'Ticket ' + ticketId;
    }

    return 'Unbekannt';
  }

  function format_source_info(seatContainer) {
    const seatLabel = get_seat_label(seatContainer);
    const ticketId = get_ticket_id(seatContainer);
    const occupierName = get_occupier_name(seatContainer);
    const name = occupierName !== undefined && occupierName !== '' ? occupierName : 'Unbekannt';
    return {
      main: name + ' - ' + seatLabel,
      ticket: ticketId !== undefined && ticketId !== '' ? 'Ticket ' + ticketId : ''
    };
  }

  function format_target_info(seatContainer) {
    const seatLabel = get_seat_label(seatContainer);
    if (is_occupied(seatContainer)) {
      const occupierName = get_occupier_name(seatContainer);
      const ticketId = get_ticket_id(seatContainer);
      const name = occupierName !== undefined && occupierName !== '' ? occupierName : 'Unbekannt';
      return {
        main: name + ' - ' + seatLabel,
        ticket: ticketId !== undefined && ticketId !== '' ? 'Ticket ' + ticketId : ''
      };
    }
    return {
      main: 'frei - ' + seatLabel,
      ticket: ''
    };
  }

  function set_placeholder(mainNode, ticketNode) {
    mainNode.innerHTML = '<span class="dimmed">Nicht gesetzt</span>';
    ticketNode.textContent = '';
  }

  function update_panel() {
    if (sourceSeat === null) {
      set_placeholder(sourceInfoMain, sourceInfoTicket);
    } else {
      const sourceInfoDetails = format_source_info(sourceSeat);
      sourceInfoMain.textContent = sourceInfoDetails.main;
      sourceInfoTicket.textContent = sourceInfoDetails.ticket;
    }

    if (targetSeat === null) {
      set_placeholder(targetInfoMain, targetInfoTicket);
    } else {
      const targetInfoDetails = format_target_info(targetSeat);
      targetInfoMain.textContent = targetInfoDetails.main;
      targetInfoTicket.textContent = targetInfoDetails.ticket;
    }
  }

  function clear_source() {
    if (sourceSeat !== null) {
      sourceSeat.classList.remove('is-relocate-source');
    }
    sourceSeat = null;
  }

  function clear_target() {
    if (targetSeat !== null) {
      targetSeat.classList.remove('is-relocate-target');
    }
    targetSeat = null;
  }

  function clear_selection() {
    clear_source();
    clear_target();
    update_panel();
    close_modal();
    apply_search_filter();
  }

  function open_modal() {
    if (modal === null || modalMessage === null || sourceSeat === null || targetSeat === null) {
      return;
    }

    const sourceName = format_occupier_label(sourceSeat);
    const sourceLabel = get_seat_label(sourceSeat);
    const targetLabel = get_seat_label(targetSeat);
    if (modalWarning !== null) {
      modalWarning.textContent = '';
      modalWarning.hidden = true;
    }

    if (modalTitle !== null) {
      modalTitle.textContent = is_occupied(targetSeat) ? 'Platztausch bestätigen' : 'Umsetzen bestätigen';
    }

    if (is_occupied(targetSeat)) {
      const targetOccupier = format_occupier_label(targetSeat);
      modalMessage.textContent = 'Achtung: Du tauschst die Plätze von ' + sourceName + ' (' + sourceLabel + ') und ' + targetOccupier + ' (' + targetLabel + ').';
    } else {
      modalMessage.textContent = 'Teilnehmer ' + sourceName + ' wird auf Sitz ' + targetLabel + ' umgesetzt.';
    }

    modalOpen = true;
    modal.classList.add('is-open');
    modal.setAttribute('aria-hidden', 'false');
  }

  function close_modal() {
    if (modal === null) {
      return;
    }
    if (modalOk !== null) {
      modalOk.disabled = false;
    }
    modalOpen = false;
    modal.classList.remove('is-open');
    modal.setAttribute('aria-hidden', 'true');
  }

  function select_source(seatContainer) {
    clear_source();
    clear_target();
    sourceSeat = seatContainer;
    sourceSeat.classList.add('is-relocate-source');
    update_panel();
    apply_search_filter();
  }

  function select_target(seatContainer) {
    clear_target();
    targetSeat = seatContainer;
    targetSeat.classList.add('is-relocate-target');
    update_panel();
    apply_search_filter();
    open_modal();
  }

  function select_source_and_target(newSourceSeat, newTargetSeat) {
    clear_source();
    clear_target();
    sourceSeat = newSourceSeat;
    sourceSeat.classList.add('is-relocate-source');
    targetSeat = newTargetSeat;
    targetSeat.classList.add('is-relocate-target');
    update_panel();
    apply_search_filter();
    open_modal();
  }

  function clear_search() {
    if (searchInput === null) {
      return;
    }
    searchInput.value = '';
    apply_search_filter();
  }

  function apply_search_filter() {
    if (searchInput === null) {
      return;
    }

    const query = searchInput.value.trim().toLowerCase();

    seatContainers.forEach(seatContainer => {
      seatContainer.classList.remove('is-relocate-search-match', 'is-relocate-search-hidden');

      if (query === '') {
        return;
      }

      const occupierName = (seatContainer.dataset.occupierName || '').toLowerCase();
      if (occupierName.includes(query)) {
        seatContainer.classList.add('is-relocate-search-match');
      } else {
        seatContainer.classList.add('is-relocate-search-hidden');
      }
    });

    if (sourceSeat !== null) {
      sourceSeat.classList.remove('is-relocate-search-hidden');
    }

    if (targetSeat !== null) {
      targetSeat.classList.remove('is-relocate-search-hidden');
    }
  }

  function select_single_match_as_source() {
    if (searchInput === null || sourceSeat !== null) {
      return;
    }

    const query = searchInput.value.trim().toLowerCase();
    if (query === '') {
      return;
    }

    const matchingSeats = seatContainers.filter(seatContainer => {
      const occupierName = (seatContainer.dataset.occupierName || '').toLowerCase();
      return occupierName.includes(query) && is_occupied(seatContainer);
    });

    if (matchingSeats.length === 1) {
      select_source(matchingSeats[0]);
    }
  }

  seatContainers.forEach(seatContainer => {
    seatContainer.addEventListener('click', event => {
      if (modalOpen) {
        return;
      }

      if (sourceSeat === null) {
        if (!is_occupied(seatContainer)) {
          return;
        }
        select_source(seatContainer);
        return;
      }

      if (seatContainer === sourceSeat) {
        return;
      }

      if (is_occupied(seatContainer)) {
        select_source_and_target(seatContainer, sourceSeat);
        event.preventDefault();
        return;
      }

      select_target(seatContainer);

      event.preventDefault();
    });
  });

  clearTrigger.addEventListener('click', () => clear_selection());

  if (modalCancel !== null) {
    modalCancel.addEventListener('click', () => {
      clear_target();
      update_panel();
      close_modal();
      apply_search_filter();
    });
  }

  if (modalOk !== null) {
    modalOk.addEventListener('click', () => {
      if (sourceSeat === null || targetSeat === null) {
        close_modal();
        return;
      }

      if (relocateForm === null || ticketIdInput === null || targetSeatIdInput === null || sourceSeatIdInput === null || targetTicketIdInput === null || modeInput === null) {
        close_modal();
        return;
      }

      const ticketId = get_ticket_id(sourceSeat);
      const targetSeatId = get_seat_id(targetSeat);
      const sourceSeatId = get_seat_id(sourceSeat);

      if (ticketId === undefined || targetSeatId === undefined || sourceSeatId === undefined) {
        close_modal();
        return;
      }

      ticketIdInput.value = ticketId;
      targetSeatIdInput.value = targetSeatId;
      sourceSeatIdInput.value = sourceSeatId;

      if (is_occupied(targetSeat)) {
        const targetTicketId = get_ticket_id(targetSeat);
        if (targetTicketId === undefined) {
          close_modal();
          return;
        }

        targetTicketIdInput.value = targetTicketId;
        modeInput.value = 'swap';
      } else {
        targetTicketIdInput.value = '';
        modeInput.value = 'move';
      }

      modalOk.disabled = true;
      relocateForm.submit();
    });
  }

  if (modalBackdrop !== null) {
    modalBackdrop.addEventListener('click', () => {
      clear_target();
      update_panel();
      close_modal();
      apply_search_filter();
    });
  }

  if (searchInput !== null) {
    searchInput.addEventListener('input', () => apply_search_filter());
    searchInput.addEventListener('search', () => apply_search_filter());
    searchInput.addEventListener('keydown', event => {
      if (event.key === 'Enter') {
        select_single_match_as_source();
        event.preventDefault();
      } else if (event.key === 'Escape') {
        clear_search();
        event.preventDefault();
      }
    });
  }

  update_panel();
}
