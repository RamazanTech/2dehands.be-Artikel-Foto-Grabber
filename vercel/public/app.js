const form = document.getElementById("grab-form");
const urlInput = document.getElementById("listing-url");
const errorBox = document.getElementById("error");
const results = document.getElementById("results");
const summary = document.getElementById("results-summary");
const imageGrid = document.getElementById("image-grid");
const selectedCount = document.getElementById("selected-count");
const selectAllBtn = document.getElementById("select-all");
const deselectAllBtn = document.getElementById("deselect-all");
const downloadBtn = document.getElementById("download-selected");

let images = [];

function showError(message) {
  errorBox.textContent = message;
  errorBox.classList.remove("hidden");
}

function clearError() {
  errorBox.textContent = "";
  errorBox.classList.add("hidden");
}

function setLoading(isLoading) {
  downloadBtn.disabled = isLoading;
  selectAllBtn.disabled = isLoading;
  deselectAllBtn.disabled = isLoading;
}

function updateSelectedCount() {
  const checkboxes = document.querySelectorAll("input[name='selected']");
  let count = 0;
  checkboxes.forEach((cb) => {
    if (cb.checked) count += 1;
  });
  selectedCount.textContent = count;
  downloadBtn.disabled = count === 0;
}

function renderImages() {
  imageGrid.innerHTML = "";
  images.forEach((image) => {
    const label = document.createElement("label");
    label.className = "thumb-selectable";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.name = "selected";
    checkbox.value = image.index;
    checkbox.addEventListener("change", updateSelectedCount);

    const wrapper = document.createElement("div");
    wrapper.className = "thumb-image";

    const img = document.createElement("img");
    img.src = image.url;
    img.alt = `Foto ${image.index + 1}`;
    img.loading = "lazy";

    const caption = document.createElement("figcaption");
    caption.textContent = `Foto ${image.index + 1}`;

    wrapper.appendChild(img);
    label.appendChild(checkbox);
    label.appendChild(wrapper);
    label.appendChild(caption);
    imageGrid.appendChild(label);
  });
  updateSelectedCount();
}

async function grabPhotos(event) {
  event.preventDefault();
  clearError();
  results.classList.add("hidden");
  images = [];

  const url = urlInput.value.trim();
  if (!url) {
    showError("Vul een geldige URL in.");
    return;
  }

  setLoading(true);
  try {
    const response = await fetch("/api/grab", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });

    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || "Kon de foto's niet ophalen.");
    }

    const data = await response.json();
    images = data.images || [];
    if (!images.length) {
      throw new Error("Geen foto's gevonden.");
    }

    summary.textContent = `${images.length} foto's gevonden. Selecteer welke je wilt downloaden.`;
    renderImages();
    results.classList.remove("hidden");
  } catch (error) {
    showError(error.message);
  } finally {
    setLoading(false);
  }
}

async function downloadSelected() {
  clearError();
  const selectedUrls = [];
  document.querySelectorAll("input[name='selected']:checked").forEach((cb) => {
    const index = Number(cb.value);
    if (!Number.isNaN(index) && images[index]) {
      selectedUrls.push(images[index].url);
    }
  });

  if (!selectedUrls.length) {
    showError("Selecteer minstens één foto.");
    return;
  }

  setLoading(true);
  const originalLabel = downloadBtn.textContent;
  downloadBtn.textContent = "Bezig met downloaden...";

  try {
    const response = await fetch("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ urls: selectedUrls }),
    });

    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || "Download mislukt.");
    }

    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "photos.zip";
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  } catch (error) {
    showError(error.message);
  } finally {
    downloadBtn.textContent = originalLabel;
    setLoading(false);
  }
}

form.addEventListener("submit", grabPhotos);
selectAllBtn.addEventListener("click", () => {
  document.querySelectorAll("input[name='selected']").forEach((cb) => {
    cb.checked = true;
  });
  updateSelectedCount();
});
deselectAllBtn.addEventListener("click", () => {
  document.querySelectorAll("input[name='selected']").forEach((cb) => {
    cb.checked = false;
  });
  updateSelectedCount();
});
downloadBtn.addEventListener("click", downloadSelected);
