// The loading screen lives in index.html so it shows before the app's script loads.

export function setSplashStatus(text: string) {
  const status = document.querySelector("#splash .splash-status");
  if (status) status.textContent = text;
}

// Fade the loading screen out, then remove it. Safe to call more than once.
export function hideSplash() {
  const splash = document.getElementById("splash");
  if (!splash || splash.classList.contains("is-done")) return;
  splash.classList.add("is-done");
  setTimeout(() => splash.remove(), 400);
}
