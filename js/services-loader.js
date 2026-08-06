const SERVICES_CONFIG = {
  apiEndpoint: "/api/yclients/services",
  categoriesEndpoint: "/api/yclients/categories",
  cacheTimeout: 5 * 60 * 1000,
};

let servicesCache = null;
let categoriesCache = null;
let cacheTimestamp = 0;

async function getServiceCategories() {
  const now = Date.now();
  if (categoriesCache && now - cacheTimestamp < SERVICES_CONFIG.cacheTimeout) {
    return categoriesCache;
  }
  try {
    const response = await fetch(SERVICES_CONFIG.categoriesEndpoint);
    if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
    const data = await response.json();
    categoriesCache = data.data || data;
    cacheTimestamp = now;
    return categoriesCache;
  } catch (error) {
    console.error("Ошибка загрузки категорий:", error);
    return getFallbackCategories();
  }
}

async function getServices(categoryId = null) {
  const now = Date.now();
  if (servicesCache && now - cacheTimestamp < SERVICES_CONFIG.cacheTimeout) {
    if (categoryId)
      return servicesCache.filter((s) => s.category_id == categoryId);
    return servicesCache;
  }
  try {
    let url = SERVICES_CONFIG.apiEndpoint;
    if (categoryId) url += `?category_id=${categoryId}`;
    const response = await fetch(url);
    if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
    const data = await response.json();
    servicesCache = data.data || data;
    cacheTimestamp = now;
    if (categoryId)
      return servicesCache.filter((s) => s.category_id == categoryId);
    return servicesCache;
  } catch (error) {
    console.error("Ошибка загрузки услуг:", error);
    return getFallbackServices();
  }
}

function formatPrice(minPrice, maxPrice) {
  const min = parseInt(minPrice) || 0;
  const max = parseInt(maxPrice) || 0;
  if (min === 0 && max === 0) return "По запросу";
  if (min === max) return `${min.toLocaleString("ru-RU")} ₽`;
  if (max === 0) return `от ${min.toLocaleString("ru-RU")} ₽`;
  return `${min.toLocaleString("ru-RU")}–${max.toLocaleString("ru-RU")} ₽`;
}

function createServiceItemHtml(service) {
  const title = service.booking_title || service.title || "Услуга";
  const description = (service.comment || "").trim();
  const priceHtml = formatPrice(service.price_min, service.price_max);
  return `
    <div class="service-item">
      <div class="service-name">${escapeHtml(title)}</div>
      <div class="service-price">${priceHtml}</div>
      ${description ? `<div class="service-desc">${escapeHtml(description)}</div>` : ""}
    </div>
  `;
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function groupServicesByCategory(services, categories) {
  const grouped = new Map();
  categories.forEach((cat) => {
    grouped.set(cat.id, []);
  });
  services.forEach((service) => {
    const catId = service.category_id;
    if (grouped.has(catId)) {
      grouped.get(catId).push(service);
    } else {
      if (!grouped.has("uncategorized")) grouped.set("uncategorized", []);
      grouped.get("uncategorized").push(service);
    }
  });
  return grouped;
}

async function renderServices(container, services, categories) {
  if (!container) {
    console.error("Контейнер для услуг не найден");
    return;
  }
  const grouped = groupServicesByCategory(services, categories);
  let html = "";
  grouped.forEach((categoryServices, categoryId) => {
    if (categoryServices.length === 0) return;
    const category = categories.find((c) => c.id == categoryId);
    const categoryName = category ? category.title : "Другие услуги";
    html += `
      <div class="service-category">
        <h3>${escapeHtml(categoryName)}</h3>
        <div class="service-items">
          ${categoryServices.map((service) => createServiceItemHtml(service)).join("")}
        </div>
      </div>
    `;
  });
  container.innerHTML = html;
  attachServiceEventListeners(container);
}

function attachServiceEventListeners(container) {
  const serviceItems = container.querySelectorAll(".service-item");
  serviceItems.forEach((item) => {
    item.addEventListener("click", function (e) {
      const nameEl = this.querySelector(".service-name");
      const priceEl = this.querySelector(".service-price");
      const descEl = this.querySelector(".service-desc");
      if (nameEl) {
        openServiceModal({
          title: nameEl.textContent,
          price: priceEl ? priceEl.textContent : "",
          description: descEl ? descEl.textContent : "",
        });
      }
    });
  });
}

function openServiceModal(serviceData) {
  const modal = document.getElementById("serviceModal");
  if (!modal) return;
  const titleEl = document.getElementById("serviceTitle");
  const descEl = document.getElementById("serviceDescription");
  const priceEl = document.getElementById("servicePrice");
  const bookBtn = modal.querySelector(".service-btn");
  if (titleEl) titleEl.textContent = serviceData.title || "";
  if (descEl) descEl.textContent = serviceData.description || "";
  if (priceEl)
    priceEl.textContent = serviceData.price ? `Цена: ${serviceData.price}` : "";
  if (bookBtn && serviceData.title) {
    bookBtn.setAttribute("data-service", serviceData.title);
    bookBtn.textContent = "Записаться";
  }
  const bookingModal = document.getElementById("bookingModal");
  if (typeof window.openModal === "function") {
    if (modal.classList.contains("active")) {
      modal.classList.remove("active");
      document.body.style.overflow = "";
    }
    window.openModal(bookingModal);
    setTimeout(function () {
      var svc = window.ycServiceMap[serviceData.title];
      if (svc && typeof onServiceSelected === "function") {
        onServiceSelected(svc);
      }
    }, 100);
  } else {
    modal.classList.remove("active");
    document.body.style.overflow = "";
    if (bookingModal) {
      bookingModal.classList.add("active");
      document.body.style.overflow = "hidden";
      var content = bookingModal.querySelector(".modal-content");
      if (content) content.style.animation = "slideUp 0.4s ease forwards";
    }
  }
}

window.openServiceModal = openServiceModal;

function getFallbackCategories() {
  return [
    { id: 1, title: "Маникюр" },
    { id: 2, title: "Брови" },
    { id: 3, title: "Парикмахерские услуги" },
  ];
}

function getFallbackServices() {
  return [
    {
      id: 1,
      booking_title: "Маникюр с покрытием гель-лак",
      comment: "Стоимость зависит от дизайна/укрепления ногтевой пластины",
      price_min: 1700,
      price_max: 2700,
      category_id: 1,
    },
    {
      id: 2,
      booking_title: "Коррекция бровей",
      comment: "Воск/пинцет",
      price_min: 700,
      price_max: 700,
      category_id: 2,
    },
  ];
}

function showLoadingState(container) {
  if (!container) return;
  container.innerHTML = `
    <div class="services-loading">
      <div class="loading-spinner"></div>
      <p>Загружаем услуги...</p>
    </div>
  `;
}

function showErrorState(container, message = "Не удалось загрузить услуги") {
  if (!container) return;
  container.innerHTML = `
    <div class="services-error">
      <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10"/>
        <line x1="12" y1="8" x2="12" y2="12"/>
        <line x1="12" y1="16" x2="12.01" y2="16"/>
      </svg>
      <p>${escapeHtml(message)}</p>
      <button class="retry-btn" onclick="window.servicesLoader.init()">Попробовать снова</button>
    </div>
  `;
}

async function initServicesLoader(containerSelector = ".services-grid") {
  const container = document.querySelector(containerSelector);
  if (!container) {
    console.warn("Контейнер услуг не найден:", containerSelector);
    return;
  }
  showLoadingState(container);
  try {
    const timeoutPromise = new Promise((_, reject) => {
      setTimeout(() => reject(new Error("Таймаут загрузки")), 10000);
    });
    const [categories, services] = await Promise.race([
      Promise.all([getServiceCategories(), getServices()]),
      timeoutPromise,
    ]);
    if (
      !categories ||
      !services ||
      categories.length === 0 ||
      services.length === 0
    ) {
      console.warn("Нет данных для отображения");
      const fallbackCategories = getFallbackCategories();
      const fallbackServices = getFallbackServices();
      await renderServices(container, fallbackServices, fallbackCategories);
      return;
    }
    await renderServices(container, services, categories);
  } catch (error) {
    console.error("Критическая ошибка при загрузке услуг:", error);
    showErrorState(
      container,
      "Не удалось загрузить услуги. Проверьте соединение и попробуйте снова.",
    );
    if (error.message !== "Таймаут загрузки") {
      console.error("Детали ошибки:", error);
    }
  }
}

window.servicesLoader = {
  init: initServicesLoader,
  getCategories: getServiceCategories,
  getServices: getServices,
  renderServices: renderServices,
  formatPrice: formatPrice,
  clearCache: () => {
    servicesCache = null;
    categoriesCache = null;
    cacheTimestamp = 0;
  },
};

document.addEventListener("DOMContentLoaded", () => {
  initServicesLoader();
});
