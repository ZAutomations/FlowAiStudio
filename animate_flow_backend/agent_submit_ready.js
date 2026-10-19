// Shared read-only pre-submit check; Flow may hide its toggle in Agent layout.
function agentSubmitReady() {
    const visible = el => !!el && el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().height > 0;
    const chip = document.querySelector('button.agent-mode-chip');
    const toggle = document.querySelector('flow-agent-mode-toggle-chip');
    const panel = [...document.querySelectorAll('.agent-panel-prompt-box, .agent-panel-wrapper')].some(visible);
    const enabled = chip?.getAttribute('aria-pressed') === 'true'
        || chip?.classList.contains('agent-mode-chip-checked')
        || toggle?.classList.contains('checked') || panel;
    const submit = [...document.querySelectorAll('button[aria-label="Start generation"]')].find(visible);
    return !!(enabled && submit && !submit.disabled && submit.getAttribute('aria-disabled') !== 'true');
}
if (typeof module !== 'undefined') module.exports = {agentSubmitReady};
