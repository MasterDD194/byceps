/** Refresh saved chair information and consume Core's flash without navigating. */
onDomReady(() => {
  let saving = false;
  document.querySelectorAll('a[data-action="set-chair-source"]').forEach(choice => {
    choice.addEventListener('click', async event => {
      event.preventDefault();
      const field = choice.closest('.chair-information');
      if (saving) {
        return;
      }
      if (choice.dataset.chairSource && field.dataset.chairSource === choice.dataset.chairSource) {
        field.querySelector('.dropdown').classList.remove('open');
        field.querySelector('.dropdown-toggle').focus({preventScroll: true});
        return;
      }

      const scrollPosition = {top: window.scrollY, left: window.scrollX, behavior: 'instant'};
      const toggle = field.querySelector('.dropdown-toggle');
      const error = field.querySelector('.chair-update-error');
      let success = field.querySelector('.chair-update-success');
      // Static assets can arrive before the app container's new templates.
      if (!success) {
        success = document.createElement('p');
        success.className = 'chair-update-success';
        success.setAttribute('role', 'status');
        success.hidden = true;
        field.append(success);
      }
      const defaultError = error.dataset.defaultText || error.textContent;
      error.dataset.defaultText = defaultError;
      error.textContent = defaultError;
      saving = true;

      try {
        toggle.disabled = true;
        error.hidden = true;
        success.hidden = true;
        const response = await fetch(choice.href, {method: 'POST'});
        if (response.status !== 204) {
          throw new Error('Chair update failed');
        }

        // This GET also consumes the flash queued by the Core POST endpoint.
        const pageResponse = await fetch(window.location.pathname + window.location.search, {cache: 'no-store'});
        if (!pageResponse.ok || pageResponse.redirected) {
          throw new Error('Ticket refresh failed');
        }
        const page = new DOMParser().parseFromString(await pageResponse.text(), 'text/html');
        const ticket = page.getElementById(field.closest('[id^="ticket-"]').id);
        const updatedField = ticket?.querySelector('.chair-information');
        const serverError = page.querySelector('.bote-notices .color-danger .bote-notice-body');
        if (serverError) {
          error.textContent = serverError.textContent;
          error.hidden = false;
          return;
        }
        const updatedValue = updatedField?.querySelector('.data-value');
        const updatedSelection = updatedField?.querySelector('.field-sub > span');
        const confirmation = page.querySelector('.bote-notices .color-success .bote-notice-body');
        if (!updatedValue || !updatedSelection || !confirmation) {
          throw new Error('Ticket information missing');
        }
        field.querySelector('.data-value').textContent = updatedValue.textContent;
        field.querySelector('.field-sub > span').textContent = updatedSelection.textContent;
        field.dataset.chairSource = updatedField.dataset.chairSource || '';
        field.querySelector('.dropdown').classList.remove('open');
        toggle.disabled = false;
        toggle.focus({preventScroll: true});
        success.textContent = confirmation.textContent;
        success.hidden = false;
      } catch {
        error.hidden = false;
      } finally {
        saving = false;
        toggle.disabled = false;
        window.scrollTo(scrollPosition);
      }
    });
  });
});
