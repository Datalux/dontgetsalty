const ROOM_CODE = window.ROOM_CODE;
const content = document.getElementById("content");
const errorBox = document.getElementById("error-box");
const connDot = document.getElementById("conn-dot");
const connLabel = document.getElementById("conn-label");
const copyCodeBtn = document.getElementById("copy-code-btn");

const AVATAR_COLORS = 8;

let QUESTION_SUGGESTIONS = { semplice: [], piccante: [], esplicito: [] };

async function loadSuggestions() {
  if (!session) return;
  try {
    QUESTION_SUGGESTIONS = await api(`/api/rooms/${ROOM_CODE}/suggestions`);
  } catch (e) {
    // suggestions are a nice-to-have; silently keep the previous/empty pools on failure
  }
}

function randomSuggestion(category, avoid) {
  const pool = QUESTION_SUGGESTIONS[category] || [];
  if (!pool.length) return "";
  let pick = pool[Math.floor(Math.random() * pool.length)];
  for (let i = 0; i < 5 && pick === avoid && pool.length > 1; i++) {
    pick = pool[Math.floor(Math.random() * pool.length)];
  }
  return pick;
}

function avatarColor(name) {
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  return `var(--avatar-${(hash % AVATAR_COLORS) + 1})`;
}

function initials(name) {
  const trimmed = name.trim();
  if (!trimmed) return "?";
  const parts = trimmed.split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

function avatarHtml(name, size) {
  const cls = size === "small" ? "avatar small" : "avatar";
  return `<span class="${cls}" style="background:${avatarColor(name)}">${escapeHtml(initials(name))}</span>`;
}

function storageKey(code) {
  return `ggame:${code.toUpperCase()}`;
}

function getSession() {
  try {
    const raw = sessionStorage.getItem(storageKey(ROOM_CODE));
    return raw ? JSON.parse(raw) : null;
  } catch (e) {
    return null;
  }
}

function saveSession(data) {
  sessionStorage.setItem(storageKey(ROOM_CODE), JSON.stringify(data));
}

function clearSession() {
  sessionStorage.removeItem(storageKey(ROOM_CODE));
}

function showToast(message) {
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = message;
  errorBox.appendChild(toast);
  setTimeout(() => {
    toast.classList.add("leaving");
    setTimeout(() => toast.remove(), 200);
  }, 3800);
}

function setLoading(btn, loading, loadingText) {
  if (!btn) return;
  if (loading) {
    btn.dataset.label = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner"></span> ${loadingText || "Attendi..."}`;
  } else {
    btn.disabled = false;
    if (btn.dataset.label) btn.innerHTML = btn.dataset.label;
  }
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function progressBarHtml(current, total, label) {
  const pct = total > 0 ? Math.min(100, (current / total) * 100) : 0;
  return `
    <div class="progress-track"><div class="progress-fill" style="width:${pct}%"></div></div>
    <div class="progress-label"><span>${label || ""}</span><span>${current}/${total}</span></div>
  `;
}

function autoGrowTextarea(el) {
  el.style.height = "auto";
  el.style.height = `${el.scrollHeight}px`;
}

function stepDotsHtml(current, total) {
  let dots = "";
  for (let i = 1; i <= total; i++) {
    const cls = i < current ? "step done" : i === current ? "step active" : "step";
    dots += `<span class="${cls}"></span>`;
  }
  return `<div class="step-dots">${dots}</div>`;
}

function setContent(html) {
  content.classList.remove("fade-in");
  content.innerHTML = html;
  // force reflow so the animation restarts on every render
  void content.offsetWidth;
  content.classList.add("fade-in");
}

let session = getSession();
let socket = null;
let lastState = null;
let selectedRounds = 3;
let selectedVoteTarget = null;
let voteChoiceHidden = true;

function shuffled(array) {
  const arr = array.slice();
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

async function api(path, options = {}) {
  const headers = Object.assign({ "Content-Type": "application/json" }, options.headers || {});
  if (session) headers["Authorization"] = `Bearer ${session.token}`;
  const res = await fetch(path, { ...options, headers });
  const data = await res.json();
  if (!res.ok) {
    if (res.status === 401) {
      clearSession();
      session = null;
      renderJoinForm();
    }
    throw new Error(data.detail || "Errore imprevisto.");
  }
  return data;
}

function setConnStatus(state) {
  connDot.classList.remove("online");
  if (state === "online") {
    connDot.classList.add("online");
    connLabel.textContent = "Connesso";
  } else if (state === "connecting") {
    connLabel.textContent = "Connessione...";
  } else {
    connLabel.textContent = "Riconnessione...";
  }
}

function connectSocket() {
  if (!session) return;
  setConnStatus("connecting");
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${proto}://${window.location.host}/ws/${ROOM_CODE}?token=${session.token}`);
  socket.addEventListener("open", () => setConnStatus("online"));
  socket.addEventListener("message", (event) => {
    const state = JSON.parse(event.data);
    render(state);
  });
  socket.addEventListener("close", () => {
    setConnStatus("offline");
    setTimeout(() => {
      if (session) connectSocket();
    }, 1500);
  });
}

copyCodeBtn.addEventListener("click", async () => {
  const shareUrl = `${window.location.origin}/r/${ROOM_CODE}`;
  try {
    if (navigator.share) {
      await navigator.share({ title: "Don't Get Salty", text: `Unisciti alla stanza ${ROOM_CODE}`, url: shareUrl });
      return;
    }
    await navigator.clipboard.writeText(ROOM_CODE);
    showToast("Codice copiato negli appunti!");
  } catch (err) {
    // user cancelled share, or clipboard unavailable — no-op
  }
});

async function init() {
  if (!session) {
    renderJoinForm();
    return;
  }
  loadSuggestions();
  try {
    const state = await api(`/api/rooms/${ROOM_CODE}/state`);
    render(state);
    connectSocket();
  } catch (err) {
    showToast(err.message);
  }
}

function renderJoinForm() {
  setContent(`
    <div class="card">
      <h2>Entra in questa stanza</h2>
      <div class="field-row">
        <label for="nickname">Il tuo nome</label>
        <input type="text" id="nickname" maxlength="64" placeholder="Es. Giuseppe" />
      </div>
      <button id="join-btn" class="block">Entra</button>
    </div>
  `);
  const btn = document.getElementById("join-btn");
  const input = document.getElementById("nickname");
  input.focus();
  const submit = async () => {
    const nickname = input.value.trim();
    if (!nickname) {
      input.classList.add("invalid");
      setTimeout(() => input.classList.remove("invalid"), 350);
      showToast("Inserisci il tuo nome.");
      return;
    }
    setLoading(btn, true, "Entro...");
    try {
      const data = await api(`/api/rooms/${ROOM_CODE}/join`, {
        method: "POST",
        body: JSON.stringify({ nickname }),
      });
      session = { token: data.player_token, player_id: data.player_id, nickname };
      saveSession(session);
      loadSuggestions();
      const state = await api(`/api/rooms/${ROOM_CODE}/state`);
      render(state);
      connectSocket();
    } catch (err) {
      setLoading(btn, false);
      showToast(err.message);
    }
  };
  btn.addEventListener("click", submit);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") submit();
  });
}

function render(state) {
  const prev = lastState;
  lastState = state;
  document.body.classList.toggle("hero-gradient", state.status === "finished");
  if (state.status === "lobby") return renderLobby(state);
  if (state.status === "collecting_questions") return renderCollecting(state, prev);
  if (state.status === "voting") return renderVoting(state, prev);
  if (state.status === "finished") return renderFinished(state);
  setContent(`<p class="hint">Stato sconosciuto.</p>`);
}

function playersListHtml(players, youId) {
  return `
    <ul class="player-list">
      ${players
        .map((p) => {
          const badges = [];
          if (p.is_host) badges.push(`<span class="badge">host</span>`);
          if (p.id === youId) badges.push(`<span class="badge you">tu</span>`);
          return `
        <li>
          ${avatarHtml(p.nickname, "small")}
          <span class="player-name">${escapeHtml(p.nickname)}</span>
          ${badges.join("")}
          <span class="dot ${p.connected ? "online" : ""}" title="${p.connected ? "online" : "offline"}"></span>
        </li>`;
        })
        .join("")}
    </ul>
  `;
}

function renderLobby(state) {
  const standingIn = state.can_act_as_host && !state.is_host;
  const roundsSection = state.can_act_as_host
    ? `
      <div class="card">
        <h2>Avvia la partita</h2>
        ${standingIn ? `<p class="hint" style="text-align:left">L'host non è raggiungibile: puoi avviare tu la partita.</p>` : ""}
        <label>Numero di round</label>
        <div class="stepper">
          <button type="button" class="stepper-btn secondary" id="rounds-minus">−</button>
          <span class="stepper-value" id="rounds-value">${selectedRounds}</span>
          <button type="button" class="stepper-btn secondary" id="rounds-plus">+</button>
        </div>
        <label class="toggle-row" for="suggestions-toggle">
          <span>Suggerimenti domande</span>
          <span class="switch">
            <input type="checkbox" id="suggestions-toggle" ${state.suggestions_enabled ? "checked" : ""} />
            <span class="switch-track"></span>
          </span>
        </label>
        <button id="start-btn" class="block" ${state.can_start ? "" : "disabled"}>Avvia partita</button>
        ${state.can_start ? "" : `<p class="hint">Servono almeno ${state.min_players} giocatori.</p>`}
      </div>`
    : `<div class="card"><p class="hint">In attesa che l'host avvii la partita<span class="waiting-dots"><span></span><span></span><span></span></span></p></div>`;

  setContent(`
    <p class="hint">Condividi il codice in alto con gli amici per farli entrare.</p>
    <div class="card">
      <h2>Giocatori (${state.players.length})</h2>
      ${playersListHtml(state.players, state.you.id)}
    </div>
    ${roundsSection}
  `);

  if (state.can_act_as_host) {
    const valueEl = document.getElementById("rounds-value");
    const clamp = (n) => Math.max(1, Math.min(20, n));
    document.getElementById("rounds-minus").addEventListener("click", () => {
      selectedRounds = clamp(selectedRounds - 1);
      valueEl.textContent = selectedRounds;
    });
    document.getElementById("rounds-plus").addEventListener("click", () => {
      selectedRounds = clamp(selectedRounds + 1);
      valueEl.textContent = selectedRounds;
    });
    const suggestionsToggle = document.getElementById("suggestions-toggle");
    suggestionsToggle.addEventListener("change", async () => {
      const enabled = suggestionsToggle.checked;
      try {
        const s = await api(`/api/rooms/${ROOM_CODE}/suggestions`, {
          method: "POST",
          body: JSON.stringify({ enabled }),
        });
        render(s);
      } catch (err) {
        suggestionsToggle.checked = !enabled;
        showToast(err.message);
      }
    });
    const startBtn = document.getElementById("start-btn");
    startBtn.addEventListener("click", async () => {
      setLoading(startBtn, true, "Avvio...");
      try {
        const s = await api(`/api/rooms/${ROOM_CODE}/start`, {
          method: "POST",
          body: JSON.stringify({ rounds: selectedRounds }),
        });
        render(s);
      } catch (err) {
        setLoading(startBtn, false);
        showToast(err.message);
      }
    });
  }
}

function renderCollecting(state, prev) {
  // A WS broadcast fires whenever ANY player submits — most of the time
  // that only changes the "N/total" counter for everyone else. Rebuilding
  // the whole screen would wipe out what they're still typing, so once the
  // form is up we only patch the counter/force-button in place and leave
  // the textarea alone. A full rebuild only happens on an actual phase/
  // round/submission-state change.
  const canPatch =
    prev &&
    prev.status === "collecting_questions" &&
    prev.current_round === state.current_round &&
    prev.you_submitted === state.you_submitted &&
    prev.can_act_as_host === state.can_act_as_host &&
    document.getElementById("questions-progress");

  if (canPatch) {
    document.getElementById("questions-progress").innerHTML = progressBarHtml(
      state.questions_submitted,
      state.questions_total,
      "Domande inviate"
    );
    const forceCard = document.getElementById("force-voting-card");
    if (forceCard) {
      forceCard.hidden = !(state.questions_submitted > 0 && state.questions_submitted < state.questions_total);
    }
    return;
  }

  // A fresh compose screen for this round — refresh the suggestion pool so
  // it excludes whatever's already been submitted (this round or earlier).
  if (!state.you_submitted) loadSuggestions();

  const value = state.your_question_text ? escapeHtml(state.your_question_text) : "";
  const suggestHtml = state.suggestions_enabled
    ? `
      <label>Serve un'idea?</label>
      <div class="suggest-row">
        <button type="button" class="chip chip-simple" data-category="semplice">Semplice</button>
        <button type="button" class="chip chip-piccante" data-category="piccante">Piccante</button>
        <button type="button" class="chip chip-spicy" data-category="esplicito">Esplicito</button>
      </div>`
    : "";

  const formHtml = state.you_submitted
    ? `
    <div class="card">
      <h2>Proponi una domanda</h2>
      <div class="submitted-question">
        <svg class="check-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"></path></svg>
        <p class="submitted-question-text blurred" id="submitted-text">${value}</p>
      </div>
      <button type="button" id="toggle-visibility-btn" class="text">Mostra la domanda</button>
      <p class="hint" style="text-align:left">Inviata! In attesa degli altri giocatori.</p>
    </div>`
    : `
    <div class="card">
      <h2>Proponi una domanda</h2>
      <p class="hint" style="text-align:left">Verrà mostrata in modo anonimo agli altri giocatori.</p>
      <div class="field-row">
        <label for="question-text">Scrivi qui la tua domanda</label>
        <textarea id="question-text" maxlength="500" placeholder="Es. Chi arriva sempre in ritardo?">${value}</textarea>
        <span class="char-count" id="char-count">${value.length}/500</span>
      </div>
      ${suggestHtml}
      <button id="question-btn" class="block">Invia domanda</button>
    </div>`;

  setContent(`
    <div class="round-indicator">
      <p class="round-tag">Round ${state.current_round} di ${state.total_rounds}</p>
    </div>
    ${formHtml}
    <div class="card" id="questions-progress">
      ${progressBarHtml(state.questions_submitted, state.questions_total, "Domande inviate")}
    </div>
    ${
      state.can_act_as_host
        ? `
    <div class="card" id="force-voting-card" ${
      state.questions_submitted > 0 && state.questions_submitted < state.questions_total ? "" : "hidden"
    }>
      <p class="hint" style="text-align:left">Qualcuno è bloccato e non riesce a inviare la domanda?</p>
      <button type="button" id="force-voting-btn" class="secondary block">Forza inizio votazione</button>
    </div>`
        : ""
    }
  `);

  if (!state.you_submitted) {
    const textarea = document.getElementById("question-text");
    const charCount = document.getElementById("char-count");
    textarea.addEventListener("input", () => {
      charCount.textContent = `${textarea.value.length}/500`;
      autoGrowTextarea(textarea);
    });

    content.querySelectorAll(".chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        const suggestion = randomSuggestion(chip.dataset.category, textarea.value.trim());
        textarea.value = suggestion;
        charCount.textContent = `${textarea.value.length}/500`;
        autoGrowTextarea(textarea);
        textarea.focus();
      });
    });

    const btn = document.getElementById("question-btn");
    btn.addEventListener("click", async () => {
      const text = textarea.value.trim();
      if (!text) {
        textarea.classList.add("invalid");
        setTimeout(() => textarea.classList.remove("invalid"), 350);
        showToast("Scrivi una domanda.");
        return;
      }
      setLoading(btn, true, "Invio...");
      try {
        const s = await api(`/api/rooms/${ROOM_CODE}/questions`, {
          method: "POST",
          body: JSON.stringify({ text }),
        });
        render(s);
      } catch (err) {
        setLoading(btn, false);
        showToast(err.message);
      }
    });
  } else {
    const submittedText = document.getElementById("submitted-text");
    const toggleBtn = document.getElementById("toggle-visibility-btn");
    toggleBtn.addEventListener("click", () => {
      const hidden = submittedText.classList.toggle("blurred");
      toggleBtn.textContent = hidden ? "Mostra la domanda" : "Nascondi la domanda";
    });
  }

  const forceBtn = document.getElementById("force-voting-btn");
  if (forceBtn) {
    forceBtn.addEventListener("click", async () => {
      setLoading(forceBtn, true, "Avvio...");
      try {
        const s = await api(`/api/rooms/${ROOM_CODE}/force-start-voting`, { method: "POST" });
        render(s);
      } catch (err) {
        setLoading(forceBtn, false);
        showToast(err.message);
      }
    });
  }
}

function tallyHtml(tally) {
  const max = Math.max(1, ...tally.map((t) => t.votes));
  const topVotes = Math.max(0, ...tally.map((t) => t.votes));
  return tally
    .map((t) => {
      const isWinner = t.votes > 0 && t.votes === topVotes;
      return `
      <div class="tally-row ${isWinner ? "winner" : ""}">
        <span class="tally-name">${escapeHtml(t.nickname)}</span>
        <span class="tally-bar-track"><span class="tally-bar-fill" style="width:${(t.votes / max) * 100}%"></span></span>
        <span class="tally-count">${t.votes}</span>
      </div>`;
    })
    .join("");
}

function renderVoting(state, prev) {
  const canPatch =
    prev &&
    prev.status === "voting" &&
    prev.question_index === state.question_index &&
    prev.question_done === state.question_done &&
    !state.question_done &&
    prev.you_voted === state.you_voted &&
    document.getElementById("votes-progress");

  if (canPatch) {
    document.getElementById("votes-progress").innerHTML = progressBarHtml(
      state.votes_cast,
      state.votes_total,
      "Voti ricevuti"
    );
    return;
  }

  // A fresh vote screen for this question — reset the (unconfirmed, local-only)
  // selection and re-shuffle the name order so tap position never lines up
  // with the same person question after question.
  if (!prev || prev.status !== "voting" || prev.question_index !== state.question_index) {
    selectedVoteTarget = null;
    voteChoiceHidden = true;
  }

  const header = `
    <div class="round-indicator">
      <p class="round-tag">Round ${state.current_round} di ${state.total_rounds} · Domanda ${state.question_index}/${state.question_count}</p>
      ${stepDotsHtml(state.question_index, state.question_count)}
    </div>
  `;

  if (!state.question) {
    setContent(`${header}<p class="hint">Caricamento...</p>`);
    return;
  }

  let bottomHtml = "";
  if (state.question_done) {
    const nextLabel = state.round_complete
      ? state.has_next_round
        ? "Round successivo"
        : "Vedi risultato finale"
      : "Prossima domanda";
    bottomHtml = `
      <div class="card"><h2>Risultato</h2>${tallyHtml(state.tally)}</div>
      ${
        state.can_act_as_host
          ? `<button id="advance-btn" class="block">${nextLabel}</button>`
          : `<p class="hint">In attesa che l'host continui<span class="waiting-dots"><span></span><span></span><span></span></span></p>`
      }`;
  } else if (state.you_voted) {
    const votedPlayer = state.players.find((p) => p.id === state.you_vote_target);
    bottomHtml = `
      <div class="card">
        <p class="hint" style="text-align:left">Hai votato:</p>
        <div class="submitted-question">
          <svg class="check-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"></path></svg>
          <p class="submitted-question-text ${voteChoiceHidden ? "blurred" : ""}" id="vote-choice-text">${escapeHtml(
            votedPlayer ? votedPlayer.nickname : "?"
          )}</p>
        </div>
        <button type="button" id="toggle-vote-visibility-btn" class="text">${
          voteChoiceHidden ? "Mostra la scelta" : "Nascondi la scelta"
        }</button>
      </div>
      <div class="card" id="votes-progress">${progressBarHtml(state.votes_cast, state.votes_total, "Voti ricevuti")}</div>
      ${
        state.can_act_as_host
          ? `
      <div class="card">
        <p class="hint" style="text-align:left">Qualcuno è bloccato e non riesce a votare?</p>
        <button type="button" id="force-vote-btn" class="secondary block">Forza chiusura voto</button>
      </div>`
          : ""
      }
    `;
  } else {
    const shuffledPlayers = shuffled(state.players);
    bottomHtml = `
      <div class="card">
        <div class="vote-list">
          ${shuffledPlayers
            .map(
              (p) => `
            <button type="button" data-id="${p.id}" class="vote-item ${selectedVoteTarget === p.id ? "chosen" : ""}">${escapeHtml(
                p.nickname
              )}</button>`
            )
            .join("")}
        </div>
        <button type="button" id="confirm-vote-btn" class="block" ${selectedVoteTarget ? "" : "disabled"}>Conferma voto</button>
      </div>
      <div class="card" id="votes-progress">${progressBarHtml(state.votes_cast, state.votes_total, "Voti ricevuti")}</div>
      ${
        state.can_act_as_host
          ? `
      <div class="card">
        <p class="hint" style="text-align:left">Qualcuno è bloccato e non riesce a votare?</p>
        <button type="button" id="force-vote-btn" class="secondary block">Forza chiusura voto</button>
      </div>`
          : ""
      }
    `;
  }

  setContent(`
    ${header}
    <div class="card question-card">
      <p class="question-label">La domanda è</p>
      <p class="question-reveal-text">${escapeHtml(state.question.text)}</p>
    </div>
    ${bottomHtml}
  `);

  if (!state.question_done && !state.you_voted) {
    const confirmBtn = document.getElementById("confirm-vote-btn");
    content.querySelectorAll(".vote-item").forEach((btn) => {
      btn.addEventListener("click", () => {
        selectedVoteTarget = parseInt(btn.dataset.id, 10);
        content.querySelectorAll(".vote-item").forEach((b) => {
          b.classList.toggle("chosen", parseInt(b.dataset.id, 10) === selectedVoteTarget);
        });
        confirmBtn.disabled = false;
      });
    });
    confirmBtn.addEventListener("click", async () => {
      if (!selectedVoteTarget) return;
      setLoading(confirmBtn, true, "Invio...");
      content.querySelectorAll(".vote-item").forEach((b) => (b.disabled = true));
      try {
        const s = await api(`/api/rooms/${ROOM_CODE}/votes`, {
          method: "POST",
          body: JSON.stringify({ target_player_id: selectedVoteTarget }),
        });
        render(s);
      } catch (err) {
        setLoading(confirmBtn, false);
        content.querySelectorAll(".vote-item").forEach((b) => (b.disabled = false));
        showToast(err.message);
      }
    });
  }

  const toggleVoteBtn = document.getElementById("toggle-vote-visibility-btn");
  if (toggleVoteBtn) {
    toggleVoteBtn.addEventListener("click", () => {
      voteChoiceHidden = !voteChoiceHidden;
      document.getElementById("vote-choice-text").classList.toggle("blurred", voteChoiceHidden);
      toggleVoteBtn.textContent = voteChoiceHidden ? "Mostra la scelta" : "Nascondi la scelta";
    });
  }

  const advanceBtn = document.getElementById("advance-btn");
  if (advanceBtn) {
    advanceBtn.addEventListener("click", async () => {
      setLoading(advanceBtn, true, "Avanti...");
      try {
        const s = await api(`/api/rooms/${ROOM_CODE}/advance`, { method: "POST" });
        render(s);
      } catch (err) {
        setLoading(advanceBtn, false);
        showToast(err.message);
      }
    });
  }

  const forceVoteBtn = document.getElementById("force-vote-btn");
  if (forceVoteBtn) {
    forceVoteBtn.addEventListener("click", async () => {
      setLoading(forceVoteBtn, true, "Chiudo...");
      try {
        const s = await api(`/api/rooms/${ROOM_CODE}/force-close-vote`, { method: "POST" });
        render(s);
      } catch (err) {
        setLoading(forceVoteBtn, false);
        showToast(err.message);
      }
    });
  }
}

function renderFinished(state) {
  const guessBoard = state.guess_leaderboard || [];
  const guessTotal = state.guess_questions_total || 0;
  const guessHtml = guessBoard.length && guessTotal > 0
    ? guessBoard
        .map(
          (row, i) => `
      <div class="leaderboard-row ${i === 0 ? "top" : ""}">
        <span class="leaderboard-rank">${i + 1}</span>
        ${avatarHtml(row.nickname, "small")}
        <span class="player-name">${escapeHtml(row.nickname)}</span>
        <span class="leaderboard-score">${row.score}/${guessTotal}</span>
      </div>`
        )
        .join("")
    : `<p class="hint">Nessun voto registrato.</p>`;

  const leaderboardTotals = {};
  state.recap.forEach((round) => {
    round.questions.forEach((q) => {
      q.tally.forEach((t) => {
        leaderboardTotals[t.nickname] = (leaderboardTotals[t.nickname] || 0) + t.votes;
      });
    });
  });
  const leaderboard = Object.entries(leaderboardTotals)
    .map(([nickname, votes]) => ({ nickname, votes }))
    .sort((a, b) => b.votes - a.votes);

  const leaderboardHtml = leaderboard.length
    ? leaderboard
        .map(
          (row, i) => `
      <div class="leaderboard-row ${i === 0 ? "top" : ""}">
        <span class="leaderboard-rank">${i + 1}</span>
        ${avatarHtml(row.nickname, "small")}
        <span class="player-name">${escapeHtml(row.nickname)}</span>
        <span class="tally-count">${row.votes}</span>
      </div>`
        )
        .join("")
    : `<p class="hint">Nessun voto registrato.</p>`;

  const roundChipsHtml =
    state.recap.length > 1
      ? `
    <div class="round-chip-row">
      ${state.recap
        .map(
          (round, i) => `
        <button type="button" class="chip round-chip ${i === 0 ? "active" : ""}" data-round="${round.round_number}">Round ${round.round_number}</button>`
        )
        .join("")}
    </div>`
      : "";

  const rounds = state.recap
    .map(
      (round, i) => `
      <div class="recap-round" data-round="${round.round_number}" ${i === 0 ? "" : "hidden"}>
        ${round.questions
          .map(
            (q) => `
          <div class="recap-question">
            <button type="button" class="recap-question-toggle">
              <span class="question-text">${escapeHtml(q.text)}</span>
              <svg class="chevron" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
            </button>
            <div class="recap-question-body"><div class="recap-question-body-inner">
              ${tallyHtml(q.tally)}
            </div></div>
          </div>`
          )
          .join("")}
      </div>`
    )
    .join("");

  setContent(`
    <div class="finish-header">
      <svg class="brand-mark" width="56" height="56" viewBox="0 0 100 100" aria-hidden="true">
        <polygon points="50,6 90,50 50,50" fill="rgba(255,255,255,0.95)" />
        <polygon points="50,6 10,50 50,50" fill="rgba(255,255,255,0.75)" />
        <polygon points="50,94 90,50 50,50" fill="rgba(255,255,255,0.6)" />
        <polygon points="50,94 10,50 50,50" fill="rgba(255,255,255,0.85)" />
      </svg>
      <h1 style="font-size:1.4rem">Partita conclusa!</h1>
      <p class="hint">Ecco come è andata.</p>
    </div>
    <div class="card">
      <h2>Chi ha letto meglio il gruppo</h2>
      <p class="hint" style="text-align:left">Un punto ogni volta che il tuo voto ha coinciso con la scelta più gettonata dal gruppo.</p>
      <div class="leaderboard">${guessHtml}</div>
    </div>
    <div class="card">
      <h2>Il più chiacchierato della serata</h2>
      <p class="hint" style="text-align:left">Chi ha ricevuto più voti in totale, nel bene e nel male — solo per curiosità.</p>
      <div class="leaderboard">${leaderboardHtml}</div>
    </div>
    <div class="card">
      ${
        state.next_room_code
          ? `
        <p class="hint" style="text-align:left">È stata avviata una nuova partita per il gruppo.</p>
        <button type="button" id="join-next-room-btn" class="block">Entra nella nuova stanza</button>
        <button type="button" id="home-btn" class="secondary block">Torna alla home</button>`
          : state.can_act_as_host
            ? `
        <button type="button" id="new-room-btn" class="block">Nuova partita</button>
        <p class="hint" style="text-align:left">Crea una stanza nuova con lo stesso gruppo — questa resta intatta, con tutte le domande e i voti.</p>
        <button type="button" id="home-btn" class="secondary block">Torna alla home</button>`
            : `<button type="button" id="home-btn" class="block">Torna alla home</button>`
      }
    </div>
    ${roundChipsHtml}
    ${rounds}
  `);

  // Joining the next room for real (not just handed a ready-made token) means
  // a player only shows up in its lobby the moment they actually arrive —
  // not the instant someone else creates the room.
  async function joinRoomByCode(code) {
    const data = await api(`/api/rooms/${code}/join`, {
      method: "POST",
      body: JSON.stringify({ nickname: session.nickname }),
    });
    sessionStorage.setItem(
      storageKey(code),
      JSON.stringify({ token: data.player_token, player_id: data.player_id, nickname: session.nickname })
    );
    window.location.href = `/r/${code}`;
  }

  const newRoomBtn = document.getElementById("new-room-btn");
  if (newRoomBtn) {
    newRoomBtn.addEventListener("click", async () => {
      setLoading(newRoomBtn, true, "Preparo...");
      try {
        const s = await api(`/api/rooms/${ROOM_CODE}/new-room`, { method: "POST" });
        // The host's own seat is already made server-side (they're arriving
        // right now) — jump in directly instead of joining for real too.
        if (s.your_new_room) {
          sessionStorage.setItem(
            storageKey(s.your_new_room.code),
            JSON.stringify({
              token: s.your_new_room.player_token,
              player_id: s.your_new_room.player_id,
              nickname: session.nickname,
            })
          );
          window.location.href = `/r/${s.your_new_room.code}`;
        }
      } catch (err) {
        setLoading(newRoomBtn, false);
        showToast(err.message);
      }
    });
  }
  const joinNextRoomBtn = document.getElementById("join-next-room-btn");
  if (joinNextRoomBtn) {
    joinNextRoomBtn.addEventListener("click", async () => {
      setLoading(joinNextRoomBtn, true, "Entro...");
      try {
        await joinRoomByCode(state.next_room_code);
      } catch (err) {
        setLoading(joinNextRoomBtn, false);
        showToast(err.message);
      }
    });
  }
  document.getElementById("home-btn").addEventListener("click", () => {
    clearSession();
    window.location.href = "/";
  });

  content.querySelectorAll(".round-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const target = chip.dataset.round;
      content.querySelectorAll(".round-chip").forEach((c) => c.classList.toggle("active", c === chip));
      content.querySelectorAll(".recap-round").forEach((el) => {
        el.hidden = el.dataset.round !== target;
      });
    });
  });

  content.querySelectorAll(".recap-question").forEach((card) => {
    card.querySelector(".recap-question-toggle").addEventListener("click", () => {
      card.classList.toggle("expanded");
    });
  });
}

init();
