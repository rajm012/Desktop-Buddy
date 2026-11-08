"use strict";

const characters = {
  robot: {
    name: "Bolt",
    description: "a small white robot with a dark screen face and bright eyes",
    hello: "Hey, I'm Bolt. Nice to meet you!",
  },
  ghost: {
    name: "Boo-ombastic",
    description: "a friendly lavender ghost",
    hello: "Boo! Just kidding. Let's be friends.",
  },
  mochi: {
    name: "Mochi",
    description: "a soft mint-colored blob-cat",
    hello: "A cozy little spot. I'll stay here.",
  },
};

let selectedCharacter = "robot";
let selectedMood = "idle";
const preview = document.querySelector("#preview-buddy");
const speech = document.querySelector("#buddy-speech");
const announcement = document.querySelector("#preview-announcement");
const characterButtons = document.querySelectorAll("[data-character]");
const moodButtons = document.querySelectorAll("[data-mood]");

function updatePreview() {
  const character = characters[selectedCharacter];
  preview.src = `assets/${selectedCharacter}-${selectedMood}.png`;
  preview.alt = `${character.name}, ${character.description}, ${selectedMood === "idle" ? "saying hello" : selectedMood === "dance" ? "dancing" : "sleeping"}`;
  preview.classList.toggle("is-dancing", selectedMood === "dance");
  preview.classList.toggle("is-sleeping", selectedMood === "sleep");
  speech.textContent = selectedMood === "idle"
    ? character.hello
    : selectedMood === "dance"
      ? "A tiny dance makes any day better."
      : "Even little buddies need a little rest.";
  announcement.textContent = `Previewing ${character.name}, ${selectedMood === "idle" ? "saying hello" : selectedMood === "dance" ? "dancing" : "sleeping"}.`;

  characterButtons.forEach((button) => {
    const selected = button.dataset.character === selectedCharacter;
    button.classList.toggle("selected", selected);
    button.setAttribute("aria-pressed", String(selected));
    button.querySelector(".select-label").firstChild.textContent = selected
      ? "In the desktop preview "
      : "Preview this buddy ";
  });
  moodButtons.forEach((button) => {
    const selected = button.dataset.mood === selectedMood;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
}

characterButtons.forEach((button) => {
  button.addEventListener("click", () => {
    selectedCharacter = button.dataset.character;
    updatePreview();
  });
});

moodButtons.forEach((button) => {
  button.addEventListener("click", () => {
    selectedMood = button.dataset.mood;
    updatePreview();
  });
});

const copyButton = document.querySelector("#copy-install");
if (navigator.clipboard && window.isSecureContext) {
  copyButton.hidden = false;
  let feedbackTimer;
  copyButton.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(document.querySelector("#install-commands").textContent.trim());
      copyButton.textContent = "Copied!";
      document.querySelector("#copy-status").textContent = "Install commands copied to clipboard.";
    } catch {
      copyButton.textContent = "Select to copy";
      document.querySelector("#copy-status").textContent = "Select the commands below and copy them manually.";
      const range = document.createRange();
      range.selectNodeContents(document.querySelector("#install-commands"));
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
    }
    clearTimeout(feedbackTimer);
    feedbackTimer = setTimeout(() => { copyButton.textContent = "Copy commands"; }, 2500);
  });
}
