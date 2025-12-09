document.addEventListener("DOMContentLoaded", () => {
  // Всплывающее окно персонажа
  const popup = document.getElementById("characterPopup");
  const closeBtn = document.getElementById("closeBtn");
  const downloadBtn = document.getElementById("downloadBtn");

  if (popup) setTimeout(() => popup.classList.add("show"), 1000);
  if (closeBtn) closeBtn.addEventListener("click", () => popup.classList.remove("show"));
  if (downloadBtn) downloadBtn.addEventListener("click", () => {
    window.open("dist/aquabriz.exe");
  });

  // Форма VIP
  const vipForm = document.getElementById("vip-form");
  if (vipForm) {
    const status = document.getElementById("status");
    vipForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(vipForm);
      try {
        const res = await fetch("https://script.google.com/macros/s/AKfycbxqNxU-QpYR-WBeHZsA34JOH2uWWIyz866pPiFN4ROj2NVc3nj0zZvZ3TNkTA4341-Ytg/exec", {method:"POST", body:fd});
        status.textContent = res.ok ? "Заявка отправлена!" : "Ошибка отправки.";
      } catch {
        status.textContent = "Ошибка соединения.";
      }
      vipForm.reset();
    });
  }

  // Форма контактов
  const contactForm = document.getElementById("contactForm");
  if (contactForm) {
    const status = document.getElementById("contactStatus");
    contactForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(contactForm);
      try {
        const res = await fetch("https://script.google.com/macros/s/AKfycbxqNxU-QpYR-WBeHZsA34JOH2uWWIyz866pPiFN4ROj2NVc3nj0zZvZ3TNkTA4341-Ytg/exec", {method:"POST", body:fd});
        status.textContent = res.ok ? "Сообщение отправлено!" : "Ошибка.";
      } catch {
        status.textContent = "Ошибка соединения.";
      }
      contactForm.reset();
    });
  }
});
// support
const faqItems = document.querySelectorAll(".faq-item");

faqItems.forEach(item => {
  const question = item.querySelector(".faq-question");
  const answer = item.querySelector(".faq-answer");
  const arrow = item.querySelector(".arrow");

  question.addEventListener("click", () => {
    answer.classList.toggle("show");
    arrow.classList.toggle("rotate");
  });
});
