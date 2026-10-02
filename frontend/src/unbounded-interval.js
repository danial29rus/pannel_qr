// The interval is deliberately not capped in the client: the project owner chooses it.
const unlockInterval = () => document.querySelectorAll('input[max="1440"]').forEach((input) => input.removeAttribute("max"));
new MutationObserver(unlockInterval).observe(document.documentElement, { childList: true, subtree: true });
unlockInterval();
