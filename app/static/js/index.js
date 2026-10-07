function storageKey(code) {
  return `ggame:${code.toUpperCase()}`;
}

function saveSession(code, data) {
  const raw = JSON.stringify(data);
  try {
    sessionStorage.setItem(storageKey(code), raw);
    localStorage.setItem(storageKey(code), raw);
  } catch (e) {
    // storage blocked (e.g. private mode) — the session just won't survive a new tab
  }
}

function showToast(message) {
  const box = document.getElementById("error-box");
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = message;
  box.appendChild(toast);
  setTimeout(() => {
    toast.classList.add("leaving");
    setTimeout(() => toast.remove(), 200);
  }, 3800);
}

function setLoading(btn, loading, loadingText) {
  if (loading) {
    btn.dataset.label = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner"></span> ${loadingText || "Attendi..."}`;
  } else {
    btn.disabled = false;
    if (btn.dataset.label) btn.innerHTML = btn.dataset.label;
  }
}

async function postJson(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.detail || "Errore imprevisto.");
  }
  return data;
}

const createBtn = document.getElementById("create-btn");
const joinBtn = document.getElementById("join-btn");

createBtn.addEventListener("click", async () => {
  const input = document.getElementById("create-nickname");
  const nickname = input.value.trim();
  if (!nickname) {
    input.classList.add("invalid");
    setTimeout(() => input.classList.remove("invalid"), 350);
    showToast("Inserisci il tuo nome.");
    return;
  }
  setLoading(createBtn, true, "Creo la stanza...");
  try {
    const data = await postJson("/api/rooms", { nickname });
    saveSession(data.room_code, {
      token: data.player_token,
      player_id: data.player_id,
      nickname,
    });
    window.location.href = `/r/${data.room_code}`;
  } catch (err) {
    setLoading(createBtn, false);
    showToast(err.message);
  }
});

joinBtn.addEventListener("click", async () => {
  const codeInput = document.getElementById("join-code");
  const nickInput = document.getElementById("join-nickname");
  const code = codeInput.value.trim().toUpperCase();
  const nickname = nickInput.value.trim();
  if (!code || !nickname) {
    [codeInput, nickInput].forEach((el) => {
      if (!el.value.trim()) {
        el.classList.add("invalid");
        setTimeout(() => el.classList.remove("invalid"), 350);
      }
    });
    showToast("Inserisci codice stanza e il tuo nome.");
    return;
  }
  setLoading(joinBtn, true, "Entro...");
  try {
    const data = await postJson(`/api/rooms/${code}/join`, { nickname });
    saveSession(code, {
      token: data.player_token,
      player_id: data.player_id,
      nickname,
    });
    window.location.href = `/r/${code}`;
  } catch (err) {
    setLoading(joinBtn, false);
    showToast(err.message);
  }
});
