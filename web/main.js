// Chugh Vibes — form submit (double opt-in) + scroll reveal.

const API = "https://fn-ai-scout-fb.azurewebsites.net/api/subscribe";
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function wireForm(form) {
  const note = form.querySelector(".form-note");
  const btn = form.querySelector("button");
  const defaultNote = note.textContent;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = form.email.value.trim();
    const name = (form.name?.value || "").trim();
    const trap = form.company?.value || ""; // honeypot

    note.className = "form-note";
    if (!EMAIL_RE.test(email)) {
      note.textContent = "That email doesn't look right — mind checking it?";
      note.classList.add("err");
      form.email.focus();
      return;
    }

    btn.disabled = true;
    btn.dataset.label = btn.textContent;
    btn.textContent = "Sending…";

    try {
      const res = await fetch(API, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, name, company: trap }),
      });
      if (res.ok) {
        form.reset();
        note.textContent = "Almost there — check your inbox and confirm to start.";
        note.classList.add("ok");
      } else {
        const data = await res.json().catch(() => ({}));
        note.textContent = data.message || "Something hiccuped. Try again in a moment.";
        note.classList.add("err");
      }
    } catch {
      note.textContent = "Couldn't reach the server. Try again in a moment.";
      note.classList.add("err");
    } finally {
      btn.disabled = false;
      btn.textContent = btn.dataset.label || "Get the daily drop";
      if (!note.classList.contains("ok")) {
        setTimeout(() => {
          if (note.classList.contains("err")) { note.className = "form-note"; note.textContent = defaultNote; }
        }, 6000);
      }
    }
  });
}

document.querySelectorAll("form.join").forEach(wireForm);

// Scroll reveal
const io = new IntersectionObserver(
  (entries) => entries.forEach((en) => { if (en.isIntersecting) { en.target.classList.add("in"); io.unobserve(en.target); } }),
  { threshold: 0.15 }
);
document.querySelectorAll(".reveal").forEach((el) => io.observe(el));
