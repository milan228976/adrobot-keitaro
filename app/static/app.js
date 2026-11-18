"use strict";

const el = (id) => document.getElementById(id);
let catalog = { offers: [] };
let currentStream = null;
let streamStats = null;
let editing = false;
let selection = 0;
let pinOfferId = null;

function notice(message, error = false) {
  const area = el("notice");
  area.hidden = !message;
  area.textContent = message || "";
  area.classList.toggle("error", error);
}

async function api(path, method = "GET", data) {
  const response = await fetch("/api/" + path, {
    method,
    ...(data === undefined ? {} : {
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  });
  const result = await response.json();
  if (!response.ok) {
    const detail = Array.isArray(result.detail)
      ? result.detail.map((item) => item.msg.replace(/^Value error, /, "")).join(" ")
      : result.detail;
    throw new Error(detail || "Ошибка запроса. Попробуйте обновить страницу.");
  }
  return result;
}

function optionLabel(row) {
  return "#" + row.id + " · " + row.name;
}

function populate(select, label, rows) {
  select.replaceChildren(new Option(label, ""));
  for (const row of rows) select.add(new Option(optionLabel(row), row.id));
}

async function loadCampaigns() {
  const campaigns = await api("campaigns");
  populate(el("campaigns"), "Выбрать кампанию", campaigns);
}

async function loadCatalog() {
  catalog = await api("catalog");
  populate(el("new-offer"), "Выбрать оффер", catalog.offers);
  populate(el("domain"), "Выбрать домен", catalog.domains);
  populate(el("group"), "Выбрать группу", catalog.groups);
  populate(el("source"), "Выбрать источник", catalog.sources);
  for (const row of catalog.offers) {
    el("offer-options").append(new Option(optionLabel(row)));
  }
  el("create-button").disabled = false;
}

function render() {
  el("editor").hidden = !currentStream;
  if (!currentStream) return;
  const { offers, pending, changed_upstream: changed } = currentStream;
  el("draft-state").textContent = changed ? "Конфликт с Keitaro" : (pending ? "Черновик" : "Синхронизировано");
  el("apply").disabled = editing || !pending || changed;
  el("discard").disabled = editing || !pending;
  el("refresh").disabled = editing;
  el("offer-search").disabled = editing || changed;
  el("add").querySelector("button").disabled = editing || changed;
  const total = offers.filter((offer) => offer.state === "active")
    .reduce((sum, offer) => sum + offer.share, 0);
  const statsText = streamStats instanceof Error ? "Статистика временно недоступна"
    : streamStats === null ? "Загрузка статистики…" : "Клики и конверсии за 7 дней · Europe/Moscow";
  el("stats-caption").textContent = statsText + " · Доля активных: " + total + "%";

  const body = el("rows");
  body.replaceChildren();
  if (!offers.length) {
    const cell = body.insertRow().insertCell();
    cell.colSpan = 5;
    cell.textContent = "В потоке пока нет офферов.";
  }
  const names = new Map(catalog.offers.map((offer) => [offer.id, offer.name]));
  for (const offer of offers) {
    const row = body.insertRow();
    const name = names.get(offer.offer_id);
    row.insertCell().textContent = "#" + offer.offer_id + (name ? " · " + name : "") +
      (offer.state === "active" ? "" : " (выключен)");

    const share = row.insertCell();
    share.className = "share-control";
    if (offer.state === "active") {
      const pin = document.createElement("button");
      pin.type = "button";
      pin.textContent = offer.share + "%" + (offer.pinned ? " · закреплено" : "");
      pin.setAttribute("aria-label", (offer.pinned ? "Открепить " : "Закрепить ") + "долю оффера #" + offer.offer_id);
      pin.disabled = editing || changed;
      pin.onclick = () => {
        if (offer.pinned) {
          mutate(offersForEdit().map((item) =>
            item.offer_id === offer.offer_id ? { ...item, pinned_share: null } : item
          ));
          return;
        }
        pinOfferId = offer.offer_id;
        el("pin-form").elements.share.value = offer.share;
        el("pin-dialog").showModal();
      };
      share.append(pin);
    } else {
      share.textContent = offer.share + "%";
    }

    const stat = streamStats && !(streamStats instanceof Error) ? streamStats[offer.offer_id] : null;
    row.insertCell().textContent = stat?.clicks ?? (streamStats && !(streamStats instanceof Error) ? 0 : "—");
    row.insertCell().textContent = stat?.conversions ?? (streamStats && !(streamStats instanceof Error) ? 0 : "—");

    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Удалить";
    remove.disabled = editing || changed;
    remove.setAttribute("aria-label", "Удалить оффер #" + offer.offer_id);
    remove.onclick = () => mutate(offersForEdit().filter((item) => item.offer_id !== offer.offer_id));
    row.insertCell().append(remove);
  }
}

async function openStream(id, attempt = ++selection) {
  currentStream = null;
  streamStats = null;
  render();
  if (!id) return;
  const draft = await api("streams/" + id + "/draft");
  if (attempt !== selection) return;
  currentStream = draft;
  render();
  api("streams/" + id + "/stats")
    .catch((error) => error)
    .then((stats) => {
      if (attempt !== selection) return;
      streamStats = stats;
      render();
    });
}

async function openCampaign(id) {
  notice();
  const attempt = ++selection;
  el("campaign-detail").hidden = true;
  currentStream = null;
  render();
  if (!id) return;
  try {
    const campaign = await api("campaigns/" + id);
    if (attempt !== selection) return;
    el("campaign-detail").hidden = false;
    el("campaign-name").textContent = optionLabel(campaign);
    el("campaign-state").textContent = ({ active: "Активна", disabled: "Выключена", deleted: "В архиве" })[campaign.state] || campaign.state;
    const editable = campaign.streams.filter((stream) => stream.editable);
    populate(el("streams"), "Выбрать поток", editable);
    el("no-stream").hidden = !!editable.length;
    if (editable.length) {
      el("streams").value = editable[0].id;
      await openStream(editable[0].id, attempt);
    }
  } catch (error) {
    if (attempt === selection) notice(error.message, true);
  }
}

function offersForEdit() {
  return currentStream.offers.map((offer) => ({
    offer_id: offer.offer_id,
    pinned_share: offer.pinned ? offer.share : null,
  }));
}

async function updateDraft(action, method, fields, message) {
  if (editing || !currentStream) return false;
  const { id, revision, baseline } = currentStream;
  editing = true;
  const attempt = selection;
  notice();
  render();
  try {
    const updated = await api("streams/" + id + "/" + action, method, { revision, baseline, ...fields });
    if (attempt === selection) {
      currentStream = updated;
      notice(message);
    }
    return true;
  } catch (error) {
    if (attempt === selection) notice(error.message, true);
    return false;
  } finally {
    editing = false;
    render();
  }
}

function mutate(offers) {
  return updateDraft("draft", "PUT", { offers }, "Изменения сохранены в черновик.");
}

el("campaigns").onchange = (event) => openCampaign(event.currentTarget.value);
el("open").onsubmit = (event) => {
  event.preventDefault();
  return openCampaign(event.currentTarget.elements.id.value);
};
el("streams").onchange = (event) => {
  notice();
  openStream(event.currentTarget.value).catch((error) => notice(error.message, true));
};
el("refresh").onclick = () => {
  const id = currentStream.id;
  notice();
  openStream(id).catch((error) => notice(error.message, true));
};
el("apply").onclick = () => updateDraft("apply", "POST", {}, "Офферы обновлены в Keitaro.");
el("discard").onclick = () => updateDraft("discard", "POST", {}, "Черновик сброшен.");
el("close-pin").onclick = () => el("pin-dialog").close();
el("pin-form").onsubmit = (event) => {
  event.preventDefault();
  const share = Number(event.currentTarget.elements.share.value);
  el("pin-dialog").close();
  mutate(offersForEdit().map((item) =>
    item.offer_id === pinOfferId ? { ...item, pinned_share: share } : item
  ));
};
el("add").onsubmit = async (event) => {
  event.preventDefault();
  const input = el("offer-search");
  const text = input.value.trim();
  const match = catalog.offers.find((offer) => optionLabel(offer) === text || offer.name === text);
  const id = match?.id ?? (/^\d+$/.test(text) ? Number(text) : 0);
  if (!id) {
    notice("Выберите оффер из списка или введите его ID.", true);
    return;
  }
  const offers = offersForEdit();
  if (offers.some((offer) => offer.offer_id === id)) {
    notice("Оффер уже есть в потоке.", true);
    return;
  }
  if (await mutate([...offers, { offer_id: id, pinned_share: null }])) input.value = "";
};

el("create").onsubmit = async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = el("create-button");
  const fields = Object.fromEntries(new FormData(form));
  for (const key of ["offer_id", "domain_id", "group_id", "traffic_source_id"]) {
    fields[key] = Number(fields[key]);
  }
  button.disabled = true;
  button.textContent = "Создаём…";
  notice();
  try {
    const campaign = await api("campaigns", "POST", fields);
    form.reset();
    await openCampaign(campaign.id);
    notice("Кампания #" + campaign.id + " создана.");
    loadCampaigns().catch((error) => notice(error.message, true));
  } catch (error) {
    notice(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "Создать кампанию";
  }
};

Promise.allSettled([loadCampaigns(), loadCatalog()]).then((results) => {
  const errors = results.filter((result) => result.status === "rejected");
  if (errors.length) notice(errors.map((result) => result.reason.message).join(" "), true);
  render();
});
