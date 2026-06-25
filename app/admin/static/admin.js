window.voiceAdmin = {
  loadedAt: new Date().toISOString(),
};

document.addEventListener("DOMContentLoaded", () => {
  const csrfToken = document
    .querySelector('meta[name="csrf-token"]')
    ?.getAttribute("content");

  if (!csrfToken) {
    return;
  }

  document.querySelectorAll('form[method="post"]').forEach((form) => {
    const existing = form.querySelector('input[name="csrf_token"]');
    if (existing) {
      existing.value = csrfToken;
      return;
    }

    const input = document.createElement("input");
    input.type = "hidden";
    input.name = "csrf_token";
    input.value = csrfToken;
    form.appendChild(input);
  });
});
