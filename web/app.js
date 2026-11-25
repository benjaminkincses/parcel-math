"use strict";

const byId = (id) => document.getElementById(id);
const money = new Intl.NumberFormat("en-IE", { style: "currency", currency: "EUR" });
const price = (cents) => money.format(cents / 100);
const form = byId("delivery-form");
const confirmButton = byId("confirm");
const resultBox = byId("result");
let visit;
let lastChoice;
let busy = false;

function element(tag, className, text) {
  const node = document.createElement(tag);
  node.className = className;
  node.textContent = text;
  return node;
}

async function request(path, init) {
  const response = await fetch(path, { cache: "no-store", ...init });
  if (!response.ok) throw new Error("Checkout request failed");
  return response.json();
}

function deliveryTime(days) {
  const value = Array.isArray(days) ? days.join("–") : String(days);
  if (/[^\d\s–-]/.test(value)) return value;
  return value + (value === "1" ? " day" : " days");
}

function renderOptions() {
  const { itemCents, options } = visit.scenario;
  const landed = visit.variant === "landed";
  const rows = options.map((option) => {
    const row = element("label", "option", "");
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "delivery";
    radio.value = option.id;
    radio.required = true;
    const detail = element("span", "option-detail", "");
    detail.append(
      element("strong", "option-name", option.label),
      element("span", "option-time", deliveryTime(option.days)),
    );
    const cost = element("span", "option-cost", "");
    cost.append(
      element("strong", "", price(landed ? itemCents + option.feeCents : option.feeCents)),
      element("small", "", landed ? "Order total" : "Shipping"),
    );
    row.append(radio, detail, cost);
    return row;
  });
  byId("options").replaceChildren(...rows);
}

function selectedOption() {
  const id = form.querySelector('input[name="delivery"]:checked')?.value;
  return visit.scenario.options.find((option) => String(option.id) === id);
}

function refreshSelection() {
  const selected = selectedOption();
  byId("estimate").textContent = selected
    ? price(visit.scenario.itemCents + selected.feeCents)
    : "Choose an option";
  confirmButton.disabled = busy || !selected || selected.id === lastChoice;
}

function displayResult(result, returning = false) {
  const { budgetCents, options } = visit.scenario;
  const chosen = options.find((option) => String(option.id) === String(result.optionId));
  if (!chosen) return;
  lastChoice = chosen.id;
  for (const input of form.querySelectorAll('input[name="delivery"]')) {
    input.checked = input.value === String(chosen.id);
  }
  const difference = result.totalCents - budgetCents;
  const balance = difference === 0 ? "exactly on budget"
    : price(Math.abs(difference)) + (result.withinBudget ? " under budget" : " over budget");
  const saved = returning || result.firstChoice;
  const heading = returning ? "Saved delivery choice" : saved ? "Delivery choice saved" : "Delivery estimate";
  resultBox.classList.toggle("over", !result.withinBudget);
  resultBox.replaceChildren(
    element("strong", "result-heading", heading),
    element("p", "", chosen.label + " comes to " + price(result.totalCents) + ", " + balance + "."),
    element("p", "result-hint", saved
      ? "You can try another option. Only the first confirmed choice counts."
      : "Your first delivery choice remains recorded."),
  );
  resultBox.hidden = false;
  confirmButton.textContent = "Try this option";
}

function showError(message, retryLoad) {
  byId("error-message").textContent = message;
  byId("retry").hidden = !retryLoad;
  byId("error-box").hidden = false;
}

async function loadVisit() {
  byId("loading").hidden = false;
  byId("error-box").hidden = true;
  try {
    const demo = new URLSearchParams(window.location.search).get("demo");
    const visitPath = ["standard", "landed"].includes(demo) ? "/api/visit?demo=" + demo : "/api/visit";
    visit = await request(visitPath);
    const { itemCents, budgetCents } = visit.scenario;
    byId("subtotal").textContent = price(itemCents);
    byId("cap").textContent = price(budgetCents);
    renderOptions();
    if (visit.complete && visit.result) displayResult(visit.result, true);
    refreshSelection();
    byId("checkout").hidden = false;
  } catch {
    showError("Your parcel could not load. Check your connection and try again.", true);
  } finally {
    byId("loading").hidden = true;
  }
}

form.addEventListener("change", refreshSelection);
byId("retry").addEventListener("click", loadVisit);
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const selected = selectedOption();
  if (busy || !selected || selected.id === lastChoice) return;
  busy = true;
  byId("delivery-set").disabled = true;
  confirmButton.disabled = true;
  byId("error-box").hidden = true;
  const oldLabel = confirmButton.textContent;
  confirmButton.textContent = "Saving…";
  try {
    const result = await request("/api/choose", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ optionId: selected.id }),
    });
    displayResult(result);
  } catch {
    confirmButton.textContent = oldLabel;
    showError("We couldn’t confirm this delivery. Please try the button again.", false);
  } finally {
    busy = false;
    byId("delivery-set").disabled = false;
    refreshSelection();
  }
});

loadVisit();
