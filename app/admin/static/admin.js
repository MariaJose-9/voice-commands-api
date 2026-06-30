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

  document.querySelectorAll("[data-audio-preview-input]").forEach((input) => {
    const preview = document.querySelector("[data-audio-preview]");
    const player = document.querySelector("[data-audio-preview-player]");
    const fileName = document.querySelector("[data-audio-preview-name]");
    let objectUrl = null;

    if (!preview || !player) {
      return;
    }

    input.addEventListener("change", () => {
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
        objectUrl = null;
      }

      const file = input.files?.[0];
      if (!file) {
        player.removeAttribute("src");
        preview.hidden = true;
        if (fileName) {
          fileName.textContent = "";
        }
        return;
      }

      objectUrl = URL.createObjectURL(file);
      player.src = objectUrl;
      preview.hidden = false;
      if (fileName) {
        fileName.textContent = `${file.name} (${Math.round(file.size / 1024)} KB)`;
      }
    });
  });
});
