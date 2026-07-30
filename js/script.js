// Prevent scroll restoration during preloader
history.scrollRestoration = "manual";

window.addEventListener("load", () => {
  setTimeout(() => {
    document.getElementById("loader").classList.add("hide");
    document.getElementById("page").classList.add("show");
    document.documentElement.style.overflow = "";
    document.body.style.overflow = "";
    window.scrollTo(0, 0);
    // Restore normal scroll behavior after loader hides
    setTimeout(() => {
      history.scrollRestoration = "auto";
    }, 500);
  }, 2200);
});

// ─── Данные для галереи ───
// ─── Данные для галереи ───
const GALLERY_IMAGES = [
  { src: "img/gallery/XXXL.webp", alt: "Интерьер студии VERBENA" },
  { src: "img/gallery/XXXL1.webp", alt: "Рабочая зона студии" },
  { src: "img/gallery/XXXL2.webp", alt: "Зона ресепшена студии" },
  { src: "img/gallery/XXXL3.webp", alt: "Интерьер салона" },
  { src: "img/gallery/XXXL13.webp", alt: "Интерьер салона" },
  { src: "img/gallery/XXXL4.webp", alt: "Интерьер салона" },
  { src: "img/gallery/XXXL5.webp", alt: "" },
  { src: "img/gallery/XXXL6.webp", alt: "" },
  { src: "img/gallery/XXXL7.webp", alt: "" },
  { src: "img/gallery/XXXL8.webp", alt: "" },
  { src: "img/gallery/XXXL9.webp", alt: "" },
  { src: "img/gallery/XXXL10.webp", alt: "" },
  { src: "img/gallery/XXXL11.webp", alt: "" },
  { src: "img/gallery/XXXL12.webp", alt: "" },
];

// ─── Резервные данные на случай, если YClients API недоступен ───
const FALLBACK_SERVICES_DATA = [
  {
    category: "Маникюр",
    items: [
      {
        name: "Маникюр с покрытием гель-лак",
        price: "1700–2700 ₽",
        desc: "Стоимость зависит от дизайна/укрепления ногтевой пластины и до наращивания углов",
      },
      {
        name: "Педикюр с покрытием гель лак (только пальчики)",
        price: "1600–2100 ₽",
        desc: "Услуга включает в себя: снятие старого покрытия (при необходимости), чистка ногтей от загрязнений, покрытие гель-лаком.",
      },
      {
        name: "Полный педикюр с покрытием гель-лак",
        price: "2500–3200 ₽",
        desc: "Услуга включает в себя: снятие старого покрытия (при необходимости), чистка ногтей от загрязнений, чистка стопы в технике SMART-pedicure, покрытие ногтей гель-лаком.",
      },
      {
        name: "Полный педикюр с покрытием лаком",
        price: "2100–3200 ₽",
        desc: "",
      },
      { name: "Наращивание ногтей", price: "2700–3400 ₽", desc: "" },
      { name: "Маникюр (гигиена)", price: "1100–1500 ₽", desc: "" },
      {
        name: "Педикюр (гигиена стопы и ногтей без покрытия)",
        price: "2000–2600 ₽",
        desc: "",
      },
      {
        name: "Маникюр с покрытием гель-лак + укрепление",
        price: "1900 ₽",
        desc: "",
      },
      {
        name: "Маникюр с покрытием DIP-система",
        price: "1900–2200 ₽",
        desc: "Альтернативное покрытие ногтей для людей с аллергией. Создается прочное покрытие похожее на гель-лак, срок носки до 3 недель. Идеальный вариант если хочется ухоженные руки без последствий для здоровья.",
      },
    ],
  },
  {
    category: "Брови",
    items: [
      {
        name: "Коррекция бровей, прореживание (воск/пинцет)",
        price: "700 ₽",
        desc: "",
      },
      {
        name: "Окрашивание + коррекция (хна, краска, построение архитектуры)",
        price: "1100 ₽",
        desc: "",
      },
      {
        name: "Долговременная укладка (окрашивание+коррекция)",
        price: "1600 ₽",
        desc: "",
      },
      { name: "Удаление волос (1 зона)", price: "150 ₽", desc: "" },
    ],
  },
  {
    category: "Парикмахерские услуги",
    items: [
      { name: "Укладка (по форме на брашинг)", price: "600–1200 ₽", desc: "" },
      {
        name: "Тонирование волос",
        price: "4500–6000 ₽",
        desc: "Окрашивание волос тон в тон, придание оттенка осветленным волосам.",
      },
      {
        name: "Окрашивание волос",
        price: "3700–6000 ₽",
        desc: "Окрашивание волос продуктами от итальянского бренда Kaaral Baco.",
      },
      { name: "Окрашивание корней", price: "2200–3500 ₽", desc: "" },
      {
        name: "Вуаль (рассветление по контуру)",
        price: "3500–6000 ₽",
        desc: "",
      },
      {
        name: "«Жизненная сила» уход от Lebel",
        price: "3000–4000 ₽",
        desc: "Программа восстановления глубинной структуры волос.",
      },
      { name: "Стрижка", price: "500–1000 ₽", desc: "" },
    ],
  },
];

// ─── Динамический рендеринг услуг из API ───
async function loadAndRenderServices() {
  const grid = document.querySelector(".services-grid");
  if (!grid) return;
  try {
    const [catRes, svcRes] = await Promise.all([
      fetch("/api/service_categories"),
      fetch("/api/yclients/services"), // ← ИЗМЕНЕНО: используем /api/yclients/services
    ]);

    const catData = await catRes.json();
    const services = await svcRes.json(); // ← ИЗМЕНЕНО: чистый массив, не {success, data}

    const categories = catData.success && catData.data ? catData.data : [];

    if (
      categories.length === 0 ||
      !Array.isArray(services) ||
      services.length === 0
    ) {
      throw new Error("Нет данных от API");
    }

    const grouped = {};
    categories.forEach((cat) => {
      grouped[cat.id] = { name: cat.title, items: [] };
    });
    grouped["uncategorized"] = { name: "Другие услуги", items: [] };

    services.forEach((svc) => {
      const catId = svc.category_id || "uncategorized";
      if (!grouped[catId]) {
        grouped[catId] = { name: "Другие услуги", items: [] };
      }
      let priceStr = "По запросу";
      if (svc.price_min && svc.price_max && svc.price_min !== svc.price_max) {
        priceStr = `${svc.price_min}–${svc.price_max} ₽`;
      } else if (svc.price_min) {
        priceStr = `${svc.price_min} ₽`;
      }
      grouped[catId].items.push({
        name: svc.title || svc.booking_title || "Услуга",
        price: priceStr,
        desc: svc.comment || "",
      });
    });

    const finalData = Object.values(grouped).filter(
      (cat) => cat.items.length > 0,
    );
    grid.innerHTML = finalData
      .map(
        (cat) => `
      <div class="service-category">
        <h3>${cat.name}</h3>
        <div class="service-items">
          ${cat.items
            .map(
              (item) => `
            <div class="service-item">
              <div class="service-name">${item.name}</div>
              <div class="service-price">${item.price}</div>
              ${item.desc ? `<div class="service-desc">${item.desc}</div>` : ""}
            </div>
          `,
            )
            .join("")}
        </div>
      </div>
    `,
      )
      .join("");
  } catch (error) {
    console.warn(
      "⚠️ Не удалось загрузить услуги из API, используем резервные данные. Причина:",
      error.message,
    );
    grid.innerHTML = FALLBACK_SERVICES_DATA.map(
      (cat) => `
      <div class="service-category">
        <h3>${cat.category}</h3>
        <div class="service-items">
          ${cat.items
            .map(
              (item) => `
            <div class="service-item">
              <div class="service-name">${item.name}</div>
              <div class="service-price">${item.price}</div>
              ${item.desc ? `<div class="service-desc">${item.desc}</div>` : ""}
            </div>
          `,
            )
            .join("")}
        </div>
      </div>
    `,
    ).join("");
  }
}

// ─── Рендеринг галереи ───
function renderGallery() {
  const container = document.querySelector(".gallery-container");
  if (!container) return;
  container.innerHTML = GALLERY_IMAGES.map(function (img, i) {
    var cls = i === 0 ? "active" : i === 1 ? "next-card" : "stack-card";
    return (
      '<img class="gallery-img ' +
      cls +
      '" src="' +
      img.src +
      '" alt="' +
      img.alt +
      '" />'
    );
  }).join("");
}
// ─── Галерея ───
let currentImageIndex = 0;
function updateGallery() {
  const images = document.querySelectorAll(".gallery-img");
  const nextImageIndex = (currentImageIndex + 1) % images.length;
  images.forEach((img, i) => {
    img.classList.remove("active", "next-card", "stack-card");
    if (i === currentImageIndex) img.classList.add("active");
    else if (i === nextImageIndex) img.classList.add("next-card");
    else img.classList.add("stack-card");
  });
}
function nextImage() {
  const images = document.querySelectorAll(".gallery-img");
  currentImageIndex = (currentImageIndex + 1) % images.length;
  updateGallery();
}
function prevImage() {
  const images = document.querySelectorAll(".gallery-img");
  currentImageIndex = (currentImageIndex - 1 + images.length) % images.length;
  updateGallery();
}

// ─── Инициализация при загрузке ───
document.addEventListener("DOMContentLoaded", () => {
  // Рендеринг динамического контента
  renderGallery();
  loadAndRenderServices(); // ← ЗАМЕНЕНО

  const bookingBtnEl = document.getElementById("bookingBtn");
  const heroSection = document.querySelector(".hero");

  function toggleStickyBooking() {
    if (!bookingBtnEl) return;
    const threshold = heroSection
      ? heroSection.offsetTop + heroSection.offsetHeight * 0.3
      : 300;
    if (window.scrollY > threshold) bookingBtnEl.classList.add("fixed-bottom");
    else bookingBtnEl.classList.remove("fixed-bottom");
  }
  window.addEventListener("scroll", toggleStickyBooking);
  toggleStickyBooking();
  updateGallery();

  const gallery = document.querySelector(".gallery-container");
  if (gallery) setInterval(nextImage, 5000);
});

document.addEventListener("DOMContentLoaded", () => {
  const heroBtn = document.querySelector(".hero-btn");
  if (!heroBtn) return;
  const initialTop = heroBtn.getBoundingClientRect().top + window.scrollY;
  function toggleHeroBtnFixed() {
    if (window.scrollY >= initialTop) heroBtn.classList.add("hero-btn-fixed");
    else heroBtn.classList.remove("hero-btn-fixed");
  }
  window.addEventListener("scroll", toggleHeroBtnFixed);
  toggleHeroBtnFixed();

  const bookingGroup = document.querySelector(".hero-booking-group");
  if (bookingGroup) {
    function updateFixedClass() {
      bookingGroup.classList.toggle(
        "has-fixed",
        heroBtn.classList.contains("hero-btn-fixed"),
      );
    }
    const observer = new MutationObserver(updateFixedClass);
    observer.observe(heroBtn, { attributes: true, attributeFilter: ["class"] });
    updateFixedClass();
  }

  if (bookingGroup) {
    heroBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      bookingGroup.classList.toggle("open");
    });
    document.addEventListener(
      "touchstart",
      function (e) {
        if (
          !bookingGroup.contains(e.target) &&
          bookingGroup.classList.contains("open")
        ) {
          bookingGroup.classList.remove("open");
        }
      },
      { passive: true },
    );
    // Найти кнопку "Запись на сайте" внутри hero-btn-split
    const siteBtn = document.querySelector(
      ".hero-btn-split-item[data-action='site']",
    );
    if (siteBtn) {
      siteBtn.addEventListener("click", function () {
        // Закрыть выпадающее меню hero
        if (bookingGroup) bookingGroup.classList.remove("open");
        // Открыть модалку
        var modal = document.getElementById("bookingModal");
        if (modal) {
          if (typeof window.openModal === "function") {
            window.openModal(modal);
          } else {
            // fallback если modal.js ещё не загрузился
            modal.classList.add("active");
            document.body.style.overflow = "hidden";
            var content = modal.querySelector(".modal-content");
            if (content) content.style.animation = "slideUp 0.4s ease forwards";
          }
        }
      });
    }
  }
});

// ─── Отзывы ───
const REVIEWS_DATA = [
  {
    text: "Хожу сюда на маникюр и брови, ни разу не пожалела. Результатом всегда довольна, аккуратно и качественно. В салоне чисто и по-домашнему уютно. Запись чёткая, можно записаться онлайн, что для меня является важным критерием выбора салона. Отдельное спасибо за вкусный кофе😊",
    author: "Саша",
    photo: "img/Sasha1.webp",
  },
  {
    text: "Это тот самый салон, где чувствуешь себя желанным гостем с первой минуты! На ресепшене милая и вежливая девушка встретила улыбкой, сразу предложила чай/кофе. В салоне чисто, опрятно, играет лёгкая музыка: можно просто выдохнуть и расслабиться. Была у мастера Марины — настоящий профессионал: всё делала внимательно и бережно, при этом управилась достаточно быстро. Маникюр получился аккуратный, качественный — ровные линии, идеальное покрытие. Ушла с красивыми ногтями и отличным настроением. Очень рекомендую!",
    author: "Арина",
    photo: "img/Arina.webp",
  },
  {
    text: "Огромное спасибо мастеру Анастасии за маникюр. Помогут воплотить любую идею!❤️",
    author: "Лиза",
    photo: "img/Liza.webp",
  },
  {
    text: "Делала у мастера Анастасии педикюр с покрытием. Очень аккуратный мастер, легкая рука, вежливая. Мне очень понравилась ее работа, Спасибо большое. Вежливый и внимательный администратор Анна, спасибо за вкусный кофе",
    author: "Дарья",
    photo: "",
  },
  {
    text: "люблю этот салон, приезжаю конкретно к мастеру Веронике из питера на каникулах) очень тоненькие но крепкие ногти, с условием моей работы руками все супеееер держится. Отдельное спасибо администраторам за гостеприимство и не принужденную атмосферу) Успехов",
    author: "Соня",
    photo: "",
  },
  {
    text: "Очень понравилась работа мастера, сделали маникюр на сложные ногти аккуратно, красиво. довольна оказанной услугой. рекомендую этот салон к посещению",
    author: "Ирина",
    photo: "",
  },
  {
    text: "В студии царит уютная атмосфера. Приятные мастера и персонал в целом. Делают самые красивые ноготочки.",
    author: "София",
    photo: "",
  },
  {
    text: "Приятные и вежливые мастера, чисто, уютно, рядом парковка. Удобная онлайн запись, не надо выгадывать время",
    author: "Алла",
    photo: "",
  },
];

function shuffleArray(arr) {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

let currentReviews = [];
let reviewsInterval = null;

function pickRandomReviews(count) {
  const shuffled = shuffleArray(REVIEWS_DATA);
  return shuffled.slice(0, count);
}

function buildReviewCardHtml(r, index) {
  const isLong = r.text.length > 280;
  const hasPhoto = r.photo && r.photo.trim() !== "";
  const photoHtml = hasPhoto
    ? `<div class="review-photo-wrap"><img class="review-photo" src="${r.photo}" alt="Фото отзыва ${r.author}" /></div>`
    : "";
  return `<article class="review-card" data-review-index="${index}"${isLong ? ' data-full-text="true"' : ""}>
      ${photoHtml}
      <div class="review-content">
        <div class="review-mark" aria-hidden="true">\u201C</div>
        <div class="review-text-wrapper">
          <p class="review-text">${r.text}</p>
        </div>
        ${isLong ? '<button class="review-toggle-btn" aria-label="Показать полностью" aria-expanded="false"><svg class="review-toggle-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg></button>' : ""}
        <p class="review-author">${r.author}</p>
      </div>
    </article>`;
}

function initReviewToggle(card) {
  const toggleBtn = card.querySelector(".review-toggle-btn");
  if (!toggleBtn) return;
  card.dataset.origHeight = card.offsetHeight + "px";
  toggleBtn.addEventListener("click", function (e) {
    e.stopPropagation();
    const text = card.querySelector(".review-text");
    const isExpanded = card.classList.contains("expanded");
    if (isExpanded) {
      card.style.transition = "none";
      card.classList.remove("expanded");
      card.style.height = card.dataset.origHeight || "";
      card.style.overflow = "";
      card.querySelector(".review-content").style.overflow = "";
      card.querySelector(".review-text-wrapper").style.overflow = "";
      if (text) text.style.maxHeight = "";
      void card.offsetHeight;
      requestAnimationFrame(() => {
        card.style.transition = "";
      });
    } else {
      card.style.transition = "none";
      if (text) text.style.transition = "none";
      card.style.height = "auto";
      card.style.overflow = "visible";
      card.querySelector(".review-content").style.overflow = "visible";
      card.querySelector(".review-text-wrapper").style.overflow = "visible";
      if (text) text.style.maxHeight = "none";
      const fullHeight = card.scrollHeight;
      const origH = card.dataset.origHeight || "520px";
      card.style.height = origH;
      card.style.overflow = "hidden";
      card.querySelector(".review-content").style.overflow = "hidden";
      card.querySelector(".review-text-wrapper").style.overflow = "hidden";
      if (text) text.style.maxHeight = "";
      void card.offsetHeight;
      card.style.transition = "";
      if (text) text.style.transition = "";
      card.classList.add("expanded");
      requestAnimationFrame(() => {
        card.style.height = fullHeight + "px";
      });
    }
    this.setAttribute("aria-expanded", String(!isExpanded));
  });
}

function renderReviews(reviews) {
  const grid = document.getElementById("reviewsGrid");
  if (!grid) return;
  currentReviews = reviews;
  grid.innerHTML = reviews.map((r, i) => buildReviewCardHtml(r, i)).join("");
  grid.querySelectorAll(".review-card").forEach(initReviewToggle);
}

function getRandomCardIndex() {
  return Math.floor(Math.random() * 3);
}

function getRandomReview(excludeTexts) {
  const candidates = REVIEWS_DATA.filter((r) => !excludeTexts.includes(r.text));
  if (candidates.length === 0) return null;
  return candidates[Math.floor(Math.random() * candidates.length)];
}

function rotateOneReview() {
  const grid = document.getElementById("reviewsGrid");
  if (!grid) return;
  const cards = grid.querySelectorAll(".review-card");
  if (cards.length !== 3) return;

  const cardIndex = getRandomCardIndex();
  const card = cards[cardIndex];
  const currentTexts = currentReviews.map((r) => r.text);
  const newReview = getRandomReview(currentTexts);
  if (!newReview) return;

  const newReviews = currentReviews.slice();
  newReviews[cardIndex] = newReview;

  // Плавное исчезновение
  card.style.transition =
    "opacity 0.7s ease, transform 0.7s cubic-bezier(0.4, 0, 0.2, 1)";
  card.style.opacity = "0";
  card.style.transform = "scale(0.96) translateY(-8px)";

  setTimeout(() => {
    const newHtml = buildReviewCardHtml(newReview, cardIndex);
    card.outerHTML = newHtml;
    currentReviews = newReviews;

    const newCard = grid.querySelectorAll(".review-card")[cardIndex];
    if (newCard) {
      initReviewToggle(newCard);

      newCard.style.transition = "none";
      newCard.style.opacity = "0";
      newCard.style.transform = "scale(0.96) translateY(8px)";

      void newCard.offsetHeight;

      newCard.style.transition =
        "opacity 0.7s ease, transform 0.7s cubic-bezier(0.4, 0, 0.2, 1)";
      newCard.style.opacity = "1";
      newCard.style.transform = "scale(1) translateY(0)";

      setTimeout(() => {
        newCard.style.transition = "";
        newCard.style.opacity = "";
        newCard.style.transform = "";
      }, 750);
    }
  }, 700);
}

function startReviewsAutoPlay() {
  if (reviewsInterval) clearInterval(reviewsInterval);
  reviewsInterval = setInterval(rotateOneReview, 7000);
}

document.addEventListener("DOMContentLoaded", () => {
  const initial = pickRandomReviews(3);
  renderReviews(initial);
  startReviewsAutoPlay();
  document.addEventListener("click", function (e) {
    const photo = e.target.closest(".review-photo");
    if (!photo) return;
    let overlay = document.querySelector(".lightbox-overlay");
    if (!overlay) {
      overlay = document.createElement("div");
      overlay.className = "lightbox-overlay";
      overlay.innerHTML =
        '<button class="lightbox-close" aria-label="Закрыть">&times;</button><img src="" alt="Увеличенное фото" />';
      document.body.appendChild(overlay);
      overlay.addEventListener("click", (e2) => {
        if (
          e2.target === overlay ||
          e2.target.classList.contains("lightbox-close")
        ) {
          overlay.classList.remove("active");
          document.body.style.overflow = "";
        }
      });
      document.addEventListener("keydown", (e2) => {
        if (e2.key === "Escape" && overlay.classList.contains("active")) {
          overlay.classList.remove("active");
          document.body.style.overflow = "";
        }
      });
    }
    const img = overlay.querySelector("img");
    if (img) {
      img.src = photo.src;
      img.alt = photo.alt || "Увеличенное фото";
    }
    overlay.classList.add("active");
    document.body.style.overflow = "hidden";
  });
});

// ─── Контакты ───
document.addEventListener("DOMContentLoaded", function () {
  var contactsBtn = document.querySelector(".side-nav-contacts-btn");
  var contactsPopup = document.getElementById("contactsPopup");
  var contactsClose = document.querySelector(".contacts-popup-close");
  var contactsOverlay = document.getElementById("contactsOverlay");

  if (!contactsBtn || !contactsPopup) return;

  function openContacts() {
    contactsPopup.classList.add("active");
    if (contactsOverlay) contactsOverlay.classList.add("active");
    contactsBtn.setAttribute("aria-expanded", "true");
  }

  function closeContacts() {
    contactsPopup.classList.remove("active");
    if (contactsOverlay) contactsOverlay.classList.remove("active");
    contactsBtn.setAttribute("aria-expanded", "false");
  }

  contactsBtn.addEventListener("click", function (e) {
    e.stopPropagation();
    if (contactsPopup.classList.contains("active")) closeContacts();
    else openContacts();
  });

  if (contactsClose) contactsClose.addEventListener("click", closeContacts);
  if (contactsOverlay) contactsOverlay.addEventListener("click", closeContacts);

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && contactsPopup.classList.contains("active")) {
      closeContacts();
    }
  });
});

// ─── Кнопка "Присоединиться" в side-nav ───
document.addEventListener("DOMContentLoaded", function () {
  var sideNavCareerBtn = document.querySelector(".side-nav-career-btn");
  if (!sideNavCareerBtn) return;

  sideNavCareerBtn.addEventListener("click", function (e) {
    e.stopPropagation();
    var modal = document.getElementById("careerModal");
    if (modal && typeof window.openModal === "function") {
      window.openModal(modal);
    }
  });
});

// ─── Наследование пунктов навигации в mobile-nav ───
document.addEventListener("DOMContentLoaded", function() {
  var mobileNav = document.querySelector(".mobile-nav");
  var desktopNav = document.querySelector("nav ul");
  if (!mobileNav || !desktopNav) return;
  
  // Очищаем mobile-nav
  mobileNav.innerHTML = "";
  
  // Иконки для пунктов меню
  var icons = {
    "#about": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "#services": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "#reviews": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "contacts": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/><circle cx="12" cy="10" r="3" fill="none" stroke="currentColor" stroke-width="1.7"/></svg>',
    "booking": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>'
  };
  
  // Клонируем ссылки из десктопной навигации
  var links = desktopNav.querySelectorAll("a[href^='#']");
  links.forEach(function(link) {
    var href = link.getAttribute("href");
    var text = link.textContent.trim();
    var icon = icons[href] || icons["#about"];
    
    var a = document.createElement("a");
    a.href = href;
    a.className = "mobile-nav-link";
    a.innerHTML = icon + "<span>" + text + "</span>";
    mobileNav.appendChild(a);
  });
  
  // Добавляем кнопку "Контакты"
  var contactsBtn = document.createElement("button");
  contactsBtn.className = "mobile-nav-contacts-btn mobile-nav-link";
  contactsBtn.innerHTML = icons["contacts"] + "<span>Контакты</span>";
  mobileNav.appendChild(contactsBtn);
  
  // Добавляем кнопку "Ищем мастера"
  var careerBtn = document.createElement("button");
  careerBtn.className = "mobile-nav-link mobile-nav-career-btn";
  careerBtn.setAttribute("data-open-career", "");
  careerBtn.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 22c0-4.4 3.6-8 8-8s8 3.6 8 8"/></svg><span>Ищем мастера</span>';
  mobileNav.appendChild(careerBtn);

  // Добавляем кнопку "Записаться"
  var bookingBtn = document.createElement("button");
  bookingBtn.className = "mobile-nav-link";
  bookingBtn.innerHTML = icons["booking"] + "<span>Записаться</span>";
  bookingBtn.addEventListener("click", function(e) {
    e.preventDefault();
    var modal = document.getElementById("bookingModal");
    if (modal && typeof window.openModal === "function") {
      window.openModal(modal);
    }
  });
  mobileNav.appendChild(bookingBtn);
  
  // Обработчик для кнопки контактов
  var contactsPopup = document.getElementById("contactsPopup");
  var contactsOverlay = document.getElementById("contactsOverlay");
  if (contactsPopup) {
    contactsBtn.addEventListener("click", function(e) {
      e.stopPropagation();
      contactsPopup.classList.add("active");
      if (contactsOverlay) contactsOverlay.classList.add("active");
    });
  }
});
