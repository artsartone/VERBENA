let currentUser = null;
let currentEditId = null;
let currentUserId = null;

// ─── Авторизация ───
async function checkAuth() {
  try {
    const res = await fetch("/api/auth/me");
    if (!res.ok) {
      window.location.href = "/admin/login";
      return null;
    }
    const user = await res.json();
    document.getElementById("sidebarUserName").textContent =
      user.display_name || user.username;
    document.body.classList.add("role-" + user.role);
    currentUser = user;
    document
      .querySelectorAll(".admin-only")
      .forEach(
        (el) => (el.style.display = user.role === "admin" ? "" : "none"),
      );
    return user;
  } catch (_) {
    window.location.href = "/admin/login";
    return null;
  }
}

// ─── SSE — браузерные уведомления в реальном времени ───
let sseClient = null;
let browserNotifyEnabled = false;

function initBrowserNotifications() {
  const toggle = document.getElementById("browserNotifyToggle");
  if (!toggle) return;

  // Восстанавливаем состояние из localStorage
  browserNotifyEnabled = localStorage.getItem("browser_notify_enabled") === "1";
  toggle.checked = browserNotifyEnabled;

  toggle.onchange = function () {
    browserNotifyEnabled = this.checked;
    localStorage.setItem(
      "browser_notify_enabled",
      browserNotifyEnabled ? "1" : "0",
    );

    if (browserNotifyEnabled) {
      // Запрашиваем разрешение на уведомления
      if ("Notification" in window) {
        if (Notification.permission === "granted") {
          connectSSE();
          updateBrowserNotifyStatus("✅ Уведомления включены", true);
        } else if (Notification.permission === "denied") {
          toggle.checked = false;
          browserNotifyEnabled = false;
          localStorage.setItem("browser_notify_enabled", "0");
          updateBrowserNotifyStatus(
            "⚠️ Уведомления заблокированы браузером. Разрешите их в настройках сайта.",
            false,
          );
        } else {
          Notification.requestPermission().then((permission) => {
            if (permission === "granted") {
              connectSSE();
              updateBrowserNotifyStatus("✅ Уведомления включены", true);
            } else {
              toggle.checked = false;
              browserNotifyEnabled = false;
              localStorage.setItem("browser_notify_enabled", "0");
              updateBrowserNotifyStatus("⚠️ Вы отклонили уведомления.", false);
            }
          });
        }
      } else {
        toggle.checked = false;
        browserNotifyEnabled = false;
        updateBrowserNotifyStatus(
          "⚠️ Ваш браузер не поддерживает уведомления.",
          false,
        );
      }
    } else {
      disconnectSSE();
      updateBrowserNotifyStatus(
        "💡 Уведомления выключены. Включите, чтобы получать оповещения.",
        false,
      );
    }
  };

  // Если уже было включено — подключаем SSE
  if (
    browserNotifyEnabled &&
    "Notification" in window &&
    Notification.permission === "granted"
  ) {
    connectSSE();
    updateBrowserNotifyStatus("✅ Уведомления включены", true);
  } else if (browserNotifyEnabled) {
    toggle.checked = false;
    browserNotifyEnabled = false;
    localStorage.setItem("browser_notify_enabled", "0");
  }
}

function updateBrowserNotifyStatus(text, isSuccess) {
  const el = document.getElementById("browserNotifyStatus");
  if (!el) return;
  el.innerHTML = `<span style="color:${isSuccess ? "#27ae60" : "#888"};font-size:13px">${text}</span>`;
}

function connectSSE() {
  if (sseClient) return;
  try {
    sseClient = new EventSource("/api/events/stream");

    sseClient.addEventListener("new_booking", function (e) {
      const data = JSON.parse(e.data);
      if (
        browserNotifyEnabled &&
        "Notification" in window &&
        Notification.permission === "granted"
      ) {
        new Notification("📅 Новая запись в VERBENA", {
          body: `${data.client_name}\n${data.service}\n${data.booking_date} в ${data.booking_time}`,
          icon: "/assets/favicon/favicon-96x96.png",
          tag: "new-booking",
        });
      }
      // Автообновление дашборда
      if (typeof loadAll === "function") loadAll();
    });

    sseClient.onerror = function () {
      // При ошибке пробуем переподключиться через 5 секунд
      setTimeout(() => {
        if (sseClient) {
          sseClient.close();
          sseClient = null;
        }
        if (browserNotifyEnabled) connectSSE();
      }, 5000);
    };
  } catch (e) {
    console.error("SSE connection error:", e);
  }
}

function disconnectSSE() {
  if (sseClient) {
    sseClient.close();
    sseClient = null;
  }
}

// ─── Настройки уведомлений ───
async function loadNotifySettings() {
  try {
    // Получаем свои данные (доступно любой роли)
    const authRes = await fetch("/api/auth/me");
    if (authRes.status !== 200) {
      initNotifyToggleEvents();
      return;
    }
    const me = await authRes.json();

    const toggle = document.getElementById("notifyToggle");
    const statusEl = document.getElementById("notifyStatus");
    const inputEl = document.getElementById("notifyInput");
    const tgInput = document.getElementById("notifyTelegramId");

    if (me.telegram_id) {
      toggle.checked = me.notify_enabled === 1;
      statusEl.style.display = "none";
      inputEl.style.display = "none";
      tgInput.value = me.telegram_id;
    } else {
      toggle.checked = false;
      statusEl.style.display = "none";
      inputEl.style.display = "none";
      tgInput.value = "";
    }

    initNotifyToggleEvents();
  } catch (e) {
    console.error(e);
  }
}

function initNotifyToggleEvents() {
  const toggle = document.getElementById("notifyToggle");
  const statusEl = document.getElementById("notifyStatus");
  const inputEl = document.getElementById("notifyInput");
  const tgInput = document.getElementById("notifyTelegramId");

  if (!toggle) return;

  toggle.onchange = function () {
    if (this.checked) {
      // Если ID не указан — показываем поле ввода
      if (!tgInput || !tgInput.value.trim()) {
        if (inputEl) inputEl.style.display = "block";
        if (statusEl) {
          statusEl.textContent = "";
          statusEl.style.display = "none";
        }
      } else {
        saveNotifySettings();
      }
    } else {
      saveNotifySettings();
    }
  };
}

async function saveNotifySettings() {
  const toggle = document.getElementById("notifyToggle");
  const telegramId = document.getElementById("notifyTelegramId").value.trim();
  const statusEl = document.getElementById("notifyStatus");
  const inputEl = document.getElementById("notifyInput");

  // Валидация Telegram ID
  if (telegramId && !/^\d+$/.test(telegramId)) {
    showToast("Telegram ID должен содержать только цифры", "error");
    toggle.checked = false;
    return;
  }
  if (telegramId && telegramId.length < 5) {
    showToast("Telegram ID слишком короткий", "error");
    toggle.checked = false;
    return;
  }

  const notifyEnabled = toggle.checked ? 1 : 0;

  try {
    const res = await fetch(`/api/auth/update-notify`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        telegram_id: telegramId,
        notify_enabled: notifyEnabled,
      }),
    });
    if (!res.ok) throw new Error("Ошибка сохранения");
    showToast("Настройки уведомлений сохранены", "success");
    inputEl.style.display = "none";
    statusEl.style.display = "none";
  } catch (e) {
    showToast(e.message, "error");
    toggle.checked = !toggle.checked;
  }
}

async function logout() {
  await fetch("/api/auth/logout", { method: "POST" });
  window.location.href = "/admin/login";
}

// ─── Сворачивание сайдбара ───
document.addEventListener("DOMContentLoaded", () => {
  const sidebar = document.getElementById("sidebar");
  const collapseBtn = document.getElementById("sidebarCollapseBtn");
  if (!sidebar || !collapseBtn) return;

  // Восстанавливаем состояние
  const collapsed = localStorage.getItem("sidebar_collapsed") === "1";
  if (collapsed) sidebar.classList.add("collapsed");

  collapseBtn.addEventListener("click", () => {
    sidebar.classList.toggle("collapsed");
    localStorage.setItem(
      "sidebar_collapsed",
      sidebar.classList.contains("collapsed") ? "1" : "0",
    );
  });
});

// ─── Гамбургер ───
document.addEventListener("click", (e) => {
  const toggle = document.getElementById("sidebarToggle");
  const sidebar = document.querySelector(".sidebar");
  const overlay = document.getElementById("sidebarOverlay");
  if (!toggle || !sidebar) return;
  if (e.target === toggle || toggle.contains(e.target)) {
    sidebar.classList.toggle("open");
    overlay.classList.toggle("open");
    toggle.classList.toggle("open");
    document.body.style.overflow = sidebar.classList.contains("open")
      ? "hidden"
      : "";
    return;
  }
  if (e.target === overlay) {
    sidebar.classList.remove("open");
    overlay.classList.remove("open");
    toggle.classList.remove("open");
    document.body.style.overflow = "";
  }
});

// ─── Навигация + закрытие мобильного меню ───
document.querySelectorAll(".sidebar-link[data-tab]").forEach((link) => {
  link.addEventListener("click", (e) => {
    e.preventDefault();
    document
      .querySelectorAll(".sidebar-link")
      .forEach((l) => l.classList.remove("active"));
    link.classList.add("active");
    document
      .querySelectorAll(".tab-content")
      .forEach((t) => t.classList.remove("active"));
    document.getElementById("tab-" + link.dataset.tab).classList.add("active");

    if (link.dataset.tab === "users") loadUsers();
    if (link.dataset.tab === "schedule") {
      loadEmployeesFilter().then(() => loadSchedule());
    }
    if (link.dataset.tab === "career") loadCareer();
    if (link.dataset.tab === "notifications") loadNotifySettings();
    if (link.dataset.tab === "profile") loadProfile();

    // Закрыть мобильное меню при переходе
    if (window.innerWidth <= 768) {
      document.querySelector(".sidebar")?.classList.remove("open");
      document.getElementById("sidebarOverlay")?.classList.remove("open");
      document.getElementById("sidebarToggle")?.classList.remove("open");
      document.body.style.overflow = "";
    }
  });
});

// [ЗАКОММЕНТИРОВАНО] Загрузка — дашборд и записи скрыты
// async function loadAll() {
//     await Promise.all([loadStats(), loadDashboard(), loadBookings(), loadHistory(), loadFilters()]);
// }
async function loadAll() {
  // Загружаем только то, что показывается
  await Promise.all([loadFilters()]);
}

async function loadStats() {
  try {
    const res = await fetch("/api/stats");
    if (res.status === 401) {
      window.location.href = "/admin/login";
      return;
    }
    const d = await res.json();
    document.getElementById("statTotal").textContent = d.total_bookings;
    document.getElementById("statActive").textContent = d.active_bookings;
    document.getElementById("statServices").textContent = d.total_services;
    document.getElementById("statEmployees").textContent =
      d.total_employees_active || 0;
  } catch (e) {
    console.error(e);
  }
}

async function loadDashboard() {
  try {
    const res = await fetch("/api/bookings?status=active,pending");
    if (res.status === 401) {
      window.location.href = "/admin/login";
      return;
    }
    const bookings = await res.json();
    const up = bookings
      .filter((b) => b.status === "pending" || b.status === "active")
      .sort(
        (a, b) =>
          sortDate(a.booking_date).localeCompare(sortDate(b.booking_date)) ||
          a.booking_time.localeCompare(b.booking_time),
      )
      .slice(0, 10);
    const tbody = document.getElementById("dashboardBody");
    tbody.innerHTML = !up.length
      ? '<tr><td colspan="8" class="empty-state">Нет активных записей</td></tr>'
      : up
          .map((b) => {
            const statusText =
              b.status === "pending"
                ? "Заявка"
                : b.status === "active"
                  ? "Активна"
                  : b.status === "completed"
                    ? "Выполнена"
                    : "Отменена";
            const statusClass =
              b.status === "pending"
                ? "badge-pending"
                : b.status === "active"
                  ? "badge-active"
                  : b.status === "completed"
                    ? "badge-completed"
                    : "badge-cancelled";
            let actions = "";
            if (b.status === "pending") {
              const confirmBtn = `<button class="btn btn-sm btn-confirm" onclick="openActionModal(${b.id}, 'confirm')" title="Подтвердить">▶</button>`;
              const cancelBtn = `<button class="btn btn-sm btn-cancel" onclick="openActionModal(${b.id}, 'cancel')" title="Отменить">✕</button>`;
              actions = `${confirmBtn} ${cancelBtn}`;
            } else if (b.status === "active") {
              actions = `<button class="btn btn-sm btn-success" onclick="openActionModal(${b.id}, 'complete')" title="Выполнить">✓</button>
                               <button class="btn btn-sm btn-cancel" onclick="openActionModal(${b.id}, 'cancel')" title="Отменить">✕</button>`;
            }
            return `<tr>
                <td data-label="Дата" class="col-center col-nowrap col-date">${b.booking_date}</td>
                <td data-label="Время" class="col-center col-nowrap col-time">${b.booking_time}</td>
                <td data-label="Клиент"><strong>${esc(b.client_name)}</strong></td>
                <td data-label="Телефон">${esc(b.client_phone)}</td>
                <td data-label="Услуга" class="col-service">${esc(b.service)}</td>
                <td data-label="Сотрудник">${b.assigned_employee_name ? esc(b.assigned_employee_name) : '<span style="color:#aaa">—</span>'}</td>
                <td data-label="Статус" class="col-center col-nowrap"><span class="badge ${statusClass}">${statusText}</span></td>
                <td data-label="Действия" class="col-center col-nowrap">${actions}</td></tr>`;
          })
          .join("");
  } catch (e) {
    console.error(e);
  }
}

async function loadFilters() {
  try {
    const svcRes = await fetch("/api/services");
    if (svcRes.ok) {
      const svcs = await svcRes.json();
      const sel = document.getElementById("serviceFilter");
      const cur = sel.value;
      sel.innerHTML =
        '<option value="">Все услуги</option>' +
        svcs
          .map((s) => `<option value="${esc(s)}">${esc(s)}</option>`)
          .join("");
      sel.value = cur;
    }
    await loadEmployeesFilter();
  } catch (e) {
    console.error(e);
  }
}

// ─── Кеш записей для модалки действий ───
let _bookingsCache = [];

// ─── Заполнить выпадающий список сотрудников в модалке подтверждения ───
async function loadEmployeesFilterForAction() {
  try {
    const res = await fetch("/api/employees/list");
    if (!res.ok) return;
    const emps = await res.json();
    const sel = document.getElementById("actionEmployee");
    if (!sel) return;
    sel.innerHTML =
      '<option value="">— Выбери мастера —</option>' +
      emps
        .map((e) => `<option value="${e.id}">${esc(e.display_name)}</option>`)
        .join("");
  } catch (e) {
    console.error(e);
  }
}

async function loadEmployeesFilter() {
  try {
    const res = await fetch("/api/employees/list");
    if (!res.ok) return [];
    const emps = await res.json();
    const render = (id, allVal, allLabel) => {
      const el = document.getElementById(id);
      if (!el) return;
      const cur = el.value;
      el.innerHTML =
        `<option value="">${allLabel}</option>` +
        emps
          .map((e) => `<option value="${e.id}">${esc(e.display_name)}</option>`)
          .join("");
      el.value = cur;
    };
    render("employeeFilter", "", "Все сотрудники");
    render("scheduleEmployee", "", "Все сотрудники");
    const empSel = document.getElementById("editEmployee");
    if (empSel) {
      const cur = empSel.value;
      empSel.innerHTML =
        '<option value="">— Не назначен —</option>' +
        emps
          .map((e) => `<option value="${e.id}">${esc(e.display_name)}</option>`)
          .join("");
      empSel.value = cur;
    }
    return emps;
  } catch (e) {
    console.error(e);
    return [];
  }
}

async function loadBookings() {
  try {
    const status = document.getElementById("statusFilter")?.value || "all";
    const service = document.getElementById("serviceFilter")?.value || "";
    const employee = document.getElementById("employeeFilter")?.value || "";
    let url = `/api/bookings?status=${status}`;
    if (service) url += `&service=${encodeURIComponent(service)}`;
    if (employee) url += `&employee=${employee}`;
    const res = await fetch(url);
    if (res.status === 401) {
      window.location.href = "/admin/login";
      return;
    }
    const bookings = await res.json();
    const tbody = document.getElementById("bookingsBody");
    tbody.innerHTML = !bookings.length
      ? '<tr><td colspan="10" class="empty-state">Нет записей</td></tr>'
      : bookings
          .map((b) => {
            let actions = "";
            if (b.status === "pending") {
              actions = `<button class="btn btn-sm btn-confirm" onclick="openActionModal(${b.id}, 'confirm')">▶</button>
                               <button class="btn btn-sm btn-cancel" onclick="openActionModal(${b.id}, 'cancel')">✕</button>`;
            } else if (b.status === "active") {
              if (currentUser?.role === "admin") {
                actions = `<button class="btn btn-sm btn-secondary" onclick="openEditModal(${b.id})">✎</button>
                                   <button class="btn btn-sm btn-success" onclick="openActionModal(${b.id}, 'complete')">✓</button>
                                   <button class="btn btn-sm btn-cancel" onclick="openActionModal(${b.id}, 'cancel')">✕</button>`;
              } else {
                actions = `<button class="btn btn-sm btn-secondary" onclick="openEditModal(${b.id})">✎</button>
                                   <button class="btn btn-sm btn-success" onclick="openActionModal(${b.id}, 'complete')">✓</button>
                                   <button class="btn btn-sm btn-cancel" onclick="openActionModal(${b.id}, 'cancel')">✕</button>`;
              }
            } else if (currentUser?.role === "admin") {
              actions = `<button class="btn btn-sm btn-secondary" onclick="openEditModal(${b.id})">✎</button>`;
            } else if (currentUser?.role === "employee") {
              actions = `<button class="btn btn-sm btn-secondary" onclick="openEditModal(${b.id})">✎</button>`;
            }
            return `<tr>
                <td data-label="ID" class="col-center col-nowrap">#${b.id}</td>
                <td data-label="Дата" class="col-nowrap">${b.booking_date}</td>
                <td data-label="Время" class="col-nowrap col-time">${b.booking_time}</td>
                <td data-label="Клиент"><strong>${esc(b.client_name)}</strong></td>
                <td data-label="Телефон">${esc(b.client_phone)}</td>
                <td data-label="Услуга">${esc(b.service)}</td>
                <td data-label="Сотрудник">${b.assigned_employee_name ? esc(b.assigned_employee_name) : '<span style="color:#aaa">\u2014</span>'}</td>
                <td data-label="Статус" class="col-center col-nowrap">${statusBadge(b.status)}</td>
                <td data-label="Комментарий">${b.comment ? esc(b.comment) : '<span style="color:#aaa">\u2014</span>'}</td>
                <td data-label="Действия" class="col-center col-nowrap">${actions}</td></tr>`;
          })
          .join("");
  } catch (e) {
    console.error(e);
  }
}

async function loadSchedule() {
  // ВРЕМЕННО ОТКЛЮЧЕНО: не подтягиваем данные в таблицу занятости
  return;

  /*
    const date = document.getElementById("scheduleDate")?.value || "";
    const employee = document.getElementById("scheduleEmployee")?.value || "";
    let dateFrom = "", dateTo = "";
    if (scheduleDateRange.start) {
        const pad = (n) => (n < 10 ? "0" + n : n);
        dateFrom = `${scheduleDateRange.start.getFullYear()}-${pad(scheduleDateRange.start.getMonth() + 1)}-${pad(scheduleDateRange.start.getDate())}`;
    }
    if (scheduleDateRange.end) {
        const pad = (n) => (n < 10 ? "0" + n : n);
        dateTo = `${scheduleDateRange.end.getFullYear()}-${pad(scheduleDateRange.end.getMonth() + 1)}-${pad(scheduleDateRange.end.getDate())}`;
    }
    try {
        const params = new URLSearchParams();
        if (dateFrom) params.set("date_from", dateFrom);
        if (dateTo) params.set("date_to", dateTo);
        if (employee) params.set("employee_id", employee);
        let url = `/api/employees/schedule?${params.toString()}`;
        const res = await fetch(url);
        if (!res.ok) return;
        const items = await res.json();
        const c = document.getElementById("scheduleContent");
        if (!items.length) { c.innerHTML = '<div class="empty-state">Нет записей на выбранный период</div>'; return; }
        const byEmp = {};
        items.forEach(b => {
            const n = b.assigned_employee_name || 'Без сотрудника';
            if (!byEmp[n]) byEmp[n] = [];
            byEmp[n].push(b);
        });
        let html = "";
        for (const [name, bk] of Object.entries(byEmp)) {
            html += `<div class="schedule-employee-block"><div class="schedule-employee-title">${esc(name)}</div><div class="schedule-slots">`;
            bk.sort((a, b2) => a.booking_time.localeCompare(b2.booking_time)).forEach(b => {
                html += `<div class="schedule-slot"><span class="schedule-time">${b.booking_time}</span> <span class="schedule-client"><strong>${esc(b.client_name || '—')}</strong></span> <span class="schedule-service">${esc(b.service || '—')}</span> <span class="schedule-status">${statusBadge(b.status)}</span></div>`;
            });
            html += `</div></div>`;
        }
        c.innerHTML = html;
    } catch (e) { console.error(e); }
    */
}

// ─── Инициализация календаря для занятости ───
function initScheduleDatePicker() {
  createDatePicker("scheduleDate", scheduleDateRange, {
    rangeMode: true,
    onChange: () => {
      loadSchedule();
    },
  });
}

// ─── Career (отклики) ───
async function loadCareer() {
  try {
    const res = await fetch("/api/career/applications");
    if (!res.ok) throw new Error("HTTP " + res.status);
    const apps = await res.json();
    const tbody = document.getElementById("careerBody");
    if (!tbody) return;
    if (!apps || apps.length === 0) {
      tbody.innerHTML =
        '<tr><td colspan="8" class="empty-state">Нет откликов</td></tr>';
      return;
    }
    tbody.innerHTML = apps
      .map(function (a) {
        var date = a.created_at
          ? a.created_at.replace(/^(\d{4}-\d{2}-\d{2}).*/, "$1")
          : "—";
        var resumeLink = a.resume
          ? '<a href="' +
            a.resume +
            '" target="_blank" style="color:#b58c5c">ссылка</a>'
          : "—";
        var cover = a.cover_letter || "—";
        var source = a.source === "tg" ? "Telegram" : "Сайт";
        return (
          "<tr>" +
          "<td>" +
          a.id +
          "</td>" +
          "<td>" +
          date +
          "</td>" +
          "<td>" +
          escapeHtml(a.client_name) +
          "</td>" +
          "<td>" +
          escapeHtml(a.client_phone) +
          "</td>" +
          "<td>" +
          escapeHtml(a.experience) +
          "</td>" +
          "<td>" +
          resumeLink +
          "</td>" +
          '<td style="max-width:200px;white-space:normal">' +
          escapeHtml(cover) +
          "</td>" +
          "<td>" +
          source +
          "</td>" +
          "</tr>"
        );
      })
      .join("");
  } catch (e) {

    console.error("Ошибка загрузки откликов:", e);

    var tbody = document.getElementById("careerBody");
    if (tbody)
      tbody.innerHTML =
        '<tr><td colspan="8" class="empty-state">Ошибка загрузки</td></tr>';
  }
}

function escapeHtml(text) {
  var d = document.createElement("div");
  d.textContent = text;
  return d.innerHTML;
}

async function loadHistory() {
  // ВРЕМЕННО ОТКЛЮЧЕНО: не подтягиваем данные в таблицу истории
  return;

  /*
    try {
        const status = document.getElementById("historyStatusFilter")?.value || "all";
        let dateFrom = "", dateTo = "";
        if (historyRange.start) {
            const pad = (n) => (n < 10 ? "0" + n : n);
            dateFrom = `${historyRange.start.getFullYear()}-${pad(historyRange.start.getMonth() + 1)}-${pad(historyRange.start.getDate())}`;
        }
        if (historyRange.end) {
            const pad = (n) => (n < 10 ? "0" + n : n);
            dateTo = `${historyRange.end.getFullYear()}-${pad(historyRange.end.getMonth() + 1)}-${pad(historyRange.end.getDate())}`;
        }
        const filterClient = (document.getElementById("historyFilterClient")?.value || "").trim();
        const filterPhone = (document.getElementById("historyFilterPhone")?.value || "").trim();
        const filterService = (document.getElementById("historyFilterService")?.value || "").trim();
        const filterMaster = (document.getElementById("historyFilterMaster")?.value || "").trim();
        const filterPrice = (document.getElementById("historyFilterPrice")?.value || "").trim();
        
        let url = `/api/history?status=${status}`;
        if (dateFrom) url += `&date_from=${encodeURIComponent(dateFrom)}`;
        if (dateTo) url += `&date_to=${encodeURIComponent(dateTo)}`;
        if (filterClient) url += `&client=${encodeURIComponent(filterClient)}`;
        if (filterPhone) url += `&phone=${encodeURIComponent(filterPhone)}`;
        if (filterService) url += `&service=${encodeURIComponent(filterService)}`;
        if (filterMaster) url += `&master=${encodeURIComponent(filterMaster)}`;
        if (filterPrice) url += `&price=${encodeURIComponent(filterPrice)}`;
        
        const res = await fetch(url);
        if (res.status === 401) { window.location.href = "/admin/login"; return; }
        const items = await res.json();
        const tbody = document.getElementById("historyBody");
        tbody.innerHTML = !items.length
            ? '<tr><td colspan="8" class="empty-state">Нет записей в истории</td></tr>'
            : items.map(h => `<tr><td class="col-center">#${h.id}</td><td class="col-date col-nowrap">${h.completed_at}</td> <td><strong>${esc(h.client_name)}</strong></td><td>${esc(h.client_phone)}</td> <td>${esc(h.service)}</td> <td>${h.assigned_employee_name ? esc(h.assigned_employee_name) : '<span style="color:#aaa">—</span>'}</td> <td class="price-col">${h.price || '<span style="color:#aaa">—</span>'}</td> <td class="col-center">${h.status === 'cancelled' ? '<span class="badge badge-cancelled">Отменена</span>' : '<span class="badge badge-completed">Выполнена</span>'}</td></tr>`).join("");
        
        const summaryEl = document.getElementById("historySummary");
        if (summaryEl) {
            summaryEl.style.display = currentUser?.role === "admin" ? "" : "none";
        }
        const sumEl = document.getElementById("historySumValue");
        if (sumEl && currentUser?.role === "admin") {
            let total = 0;
            items.forEach(h => {
                if (h.price && h.price !== "—" && h.status !== "cancelled") {
                    const val = parseInt(h.price.replace(/\s/g, "").replace("₽", ""));
                    if (!isNaN(val)) total += val;
                }
            });
            sumEl.textContent = total.toLocaleString() + " ₽";
        }
    } catch (e) { console.error(e); }
    */
}

// ─── Выпадающий список выбора фильтров истории ───
function toggleFilterDropdown(e) {
  e.stopPropagation();
  const dd = document.getElementById("filterDropdown");
  if (!dd) return;
  dd.style.display = dd.style.display === "none" ? "block" : "none";
}

function applyFilterSelection() {
  const checks = document.querySelectorAll(
    "#filterDropdown input[type='checkbox']",
  );
  const anyChecked = Array.from(checks).some((cb) => cb.checked);
  const row = document.getElementById("historyFiltersRow");
  if (row) {
    row.style.display = anyChecked ? "flex" : "none";
  }
  checks.forEach((cb) => {
    const filter = cb.dataset.filter;
    let el = null;
    if (filter === "status") {
      el = document.getElementById("historyStatusFilter");
    } else if (filter === "daterange") {
      el = document.getElementById("historyDateRange");
    } else {
      const id =
        "historyFilter" + filter.charAt(0).toUpperCase() + filter.slice(1);
      el = document.getElementById(id);
    }
    if (el) {
      el.style.display = cb.checked ? "" : "none";
    }
  });
}

// Закрываем dropdown при клике вне него и вне кнопки-триггера
document.addEventListener("click", (e) => {
  const dd = document.getElementById("filterDropdown");
  const trigger = document.getElementById("historyFilterToggle");
  if (!dd || dd.style.display === "none") return;
  if (
    !dd.contains(e.target) &&
    e.target !== trigger &&
    !trigger?.contains(e.target)
  ) {
    dd.style.display = "none";
  }
});

// ─── Универсальный календарь для выбора дат ───
// Используется в истории услуг (диапазон) и занятости (одиночная дата)

let historyRange = { start: null, end: null };
let scheduleDateRange = { start: null, end: null };

/**
 * Создаёт календарь-пикер для указанного поля ввода.
 * @param {string} inputId — id поля input
 * @param {object} state — объект { start: null, end: null } для хранения выбранных дат
 * @param {object} options
 * @param {boolean} options.rangeMode — true = выбор диапазона, false = выбор одного дня
 * @param {function} options.onChange — вызывается при изменении даты
 */
function createDatePicker(inputId, state, options = {}) {
  const input = document.getElementById(inputId);
  if (!input || input.dataset.pickerInited) return;
  input.dataset.pickerInited = "1";

  const {
    rangeMode = true,
    disableFuture = false,
    onChange = () => {},
  } = options;
  const monthNames = [
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
  ];
  const dayNames = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
  let viewDate = new Date();
  if (state.start) viewDate = new Date(state.start);
  let awaitingEnd = false; // true = ждём вторую дату, не закрываем календарь

  // Контейнер для поля и кнопки очистки
  const wrapper = document.createElement("div");
  wrapper.style.cssText =
    "display:inline-flex;align-items:center;gap:4px;position:relative";

  const clearBtn = document.createElement("button");
  clearBtn.type = "button";
  clearBtn.className = "clear-dates-btn";
  clearBtn.innerHTML = "✕";
  clearBtn.title = "Сбросить даты";
  clearBtn.style.display = "none";

  input.parentNode.insertBefore(wrapper, input);
  wrapper.appendChild(input);
  wrapper.appendChild(clearBtn);

  const calendar = document.createElement("div");
  calendar.className = "history-calendar";
  calendar.style.display = "none";
  document.body.appendChild(calendar);

  const pad = (n) => (n < 10 ? "0" + n : n);

  function formatDate(d) {
    return d
      ? `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()}`
      : "";
  }

  function updateInputLabel() {
    if (state.start && state.end) {
      if (rangeMode) {
        input.value = `${formatDate(state.start)} — ${formatDate(state.end)}`;
      } else {
        input.value = formatDate(state.start);
      }
      clearBtn.style.display = "";
    } else if (state.start) {
      input.value = formatDate(state.start);
      clearBtn.style.display = "";
    } else {
      input.value = "";
      clearBtn.style.display = "none";
    }
  }

  function positionCalendar() {
    const rect = input.getBoundingClientRect();
    const margin = 6;
    const calH = calendar.offsetHeight;
    const spaceBelow = window.innerHeight - rect.bottom;
    const spaceAbove = rect.top;
    let top;
    if (spaceBelow >= calH + margin || spaceBelow >= spaceAbove) {
      top = rect.bottom + window.scrollY + margin;
    } else {
      top = rect.top + window.scrollY - calH - margin;
    }
    calendar.style.position = "fixed";
    calendar.style.top = `${top}px`;
    calendar.style.left = `${Math.min(rect.left, window.innerWidth - 280)}px`;
  }

  function closeCalendar() {
    calendar.style.display = "none";
  }

  function renderCalendar() {
    const year = viewDate.getFullYear();
    const month = viewDate.getMonth();
    let startWeekday = new Date(year, month, 1).getDay() - 1;
    if (startWeekday < 0) startWeekday = 6;
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const today = new Date();
    today.setHours(0, 0, 0, 0);

    const rs = state.start ? new Date(state.start) : null;
    const re = state.end ? new Date(state.end) : null;

    let html = `<div class="sc-header"><button class="sc-nav" data-dir="-1">‹</button><span class="sc-title">${monthNames[month]} ${year}</span><button class="sc-nav" data-dir="1">›</button></div>`;
    html += `<div class="sc-weekdays">${dayNames.map((d) => `<span>${d}</span>`).join("")}</div><div class="sc-days">`;
    for (let i = 0; i < startWeekday; i++)
      html += `<span class="sc-day sc-empty"></span>`;
    for (let d = 1; d <= daysInMonth; d++) {
      const thisDate = new Date(year, month, d);
      thisDate.setHours(0, 0, 0, 0);
      const isFuture = disableFuture && thisDate >= today;
      const isStart = rs && thisDate.getTime() === rs.getTime();
      const isEnd = re && thisDate.getTime() === re.getTime();
      const inRange = rs && re && thisDate >= rs && thisDate <= re;
      let cls = "sc-day";
      if (isFuture) cls += " sc-disabled";
      if (isStart) cls += " sc-range-start";
      if (isEnd) cls += " sc-range-end";
      if (inRange && !isStart && !isEnd) cls += " sc-range-in";
      html += `<span class="${cls}" data-day="${d}">${d}</span>`;
    }
    html += `</div>`;
    calendar.innerHTML = html;

    calendar.querySelectorAll(".sc-nav").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        viewDate = new Date(
          viewDate.getFullYear(),
          viewDate.getMonth() + parseInt(btn.dataset.dir),
          1,
        );
        renderCalendar();
        positionCalendar();
      });
    });
    calendar
      .querySelectorAll(".sc-day:not(.sc-empty):not(.sc-disabled)")
      .forEach((el) => {
        el.addEventListener("click", () => {
          const day = parseInt(el.dataset.day, 10);
          const clicked = new Date(year, month, day);
          clicked.setHours(0, 0, 0, 0);

          if (rangeMode) {
            if (!state.start || (state.start && state.end)) {
              // Первый клик — начало диапазона
              state.start = clicked;
              state.end = null;
              awaitingEnd = true;
            } else {
              // Второй клик — конец диапазона
              if (clicked.getTime() === state.start.getTime()) {
                // Клик по той же дате — одиночный день
                state.end = clicked;
              } else if (clicked < state.start) {
                state.end = new Date(state.start);
                state.start = clicked;
              } else {
                state.end = clicked;
              }
              awaitingEnd = false;
            }
          } else {
            state.start = clicked;
            state.end = clicked;
          }

          updateInputLabel();
          renderCalendar();

          // Закрываем и вызываем onChange только когда диапазон выбран полностью
          if (!rangeMode || !awaitingEnd) {
            calendar.style.display = "none";
            onChange();
          }
        });
      });
    positionCalendar();
  }

  // Кнопка очистки
  clearBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    state.start = null;
    state.end = null;
    input.value = "";
    clearBtn.style.display = "none";
    calendar.style.display = "none";
    onChange();
  });

  input.addEventListener("focus", () => {
    calendar.style.display = "block";
    renderCalendar();
  });
  input.addEventListener("click", () => {
    calendar.style.display = "block";
    renderCalendar();
  });
  document.addEventListener("click", (e) => {
    if (
      !calendar.contains(e.target) &&
      e.target !== input &&
      e.target !== clearBtn
    ) {
      calendar.style.display = "none";
    }
  });
}

window.clearHistoryDates = function () {
  historyRange = { start: null, end: null };
  const input = document.getElementById("historyDateRange");
  if (input) input.value = "";
  loadHistory();
};

async function loadUsers() {
  try {
    const res = await fetch("/api/users");
    if (res.status !== 200) return;
    const users = await res.json();
    document.getElementById("usersBody").innerHTML = users
      .map((u) => {
        const telegramBadge = u.telegram_id
          ? `<span style="color:#4caf50;font-size:12px">✓</span> <code style="font-size:11px;color:#888">${esc(u.telegram_id)}</code>`
          : '<span style="color:#aaa;font-size:12px">—</span>';
        const notifyIcon = u.notify_enabled
          ? '<span style="color:#4caf50;font-size:14px">🔔</span>'
          : '<span style="color:#ccc;font-size:14px">🔕</span>';
        return `<tr><td class="col-center">#${u.id}</td><td><strong>${esc(u.display_name)}</strong></td>
            <td>${esc(u.username)}</td>
            <td>${u.position ? esc(u.position) : '<span style="color:#aaa">—</span>'}</td>
            <td class="col-center"><span class="role-icon role-icon-${u.role === "admin" ? "admin" : "employee"}"></span>${u.role === "admin" ? "Админ" : "Сотрудник"}</td>
            <td class="col-center" style="white-space:nowrap">${notifyIcon} ${telegramBadge}</td>
            <td class="col-center"><button class="btn btn-sm btn-secondary" onclick="openUserModal(${u.id})">✎</button>
                <button class="btn btn-sm btn-danger" onclick="deleteUser(${u.id})">✕</button></td></tr>`;
      })
      .join("");
  } catch (e) {
    console.error(e);
  }
}

// ─── Модалка записи ───
async function openEditModal(id) {
  currentEditId = id;
  try {
    const res = await fetch("/api/bookings?status=all");
    const bookings = await res.json();
    const b = bookings.find((x) => x.id === id);
    if (!b) return;
    document.getElementById("editId").textContent = id;
    document.getElementById("editName").value = b.client_name;
    document.getElementById("editPhone").value = b.client_phone;
    document.getElementById("editService").value = b.service;
    document.getElementById("editDate").value = b.booking_date;
    document.getElementById("editTime").value = b.booking_time;
    document.getElementById("editStatus").value = b.status;
    document.getElementById("editComment").value = b.comment || "";
    document.getElementById("editPrice").value = "";
    await loadEmployeesFilter();
    document.getElementById("editEmployee").value =
      b.assigned_employee_id || "";
    const isEmployee = currentUser?.role === "employee";
    document.getElementById("priceRow").style.display =
      !isEmployee && b.status === "active" ? "block" : "none";
    populateTimeSelect("editTime", b.booking_time);
    document.getElementById("editStatus").onchange = function () {
      document.getElementById("priceRow").style.display =
        !isEmployee && this.value === "completed" ? "block" : "none";
    };
    document.getElementById("editModal").style.display = "flex";
    // Сбросить состояние календаря перед инициализацией
    editDatePickerState = { start: null, end: null };
    initDatePicker();
  } catch (e) {
    console.error(e);
  }
}

function closeEditModal() {
  document.getElementById("editModal").style.display = "none";
  currentEditId = null;
  destroyDatePicker();
}

// Заполнение поля времени поминутно (шаг 15 мин) — не зависит от ФОС
function populateTimeSelect(selectId, selectedTime) {
  const sel = document.getElementById(selectId);
  if (!sel) return;
  sel.innerHTML = '<option value="" selected disabled>Выберите время</option>';
  for (let h = 10; h < 20; h++) {
    for (let m = 0; m < 60; m += 15) {
      const t = `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
      const opt = document.createElement("option");
      opt.value = t;
      opt.textContent = t;
      sel.appendChild(opt);
    }
  }
  if (selectedTime) sel.value = selectedTime;
}

// ─── Создание новой записи из админ-панели ───
async function openNewBookingModal() {
  currentEditId = null;
  try {
    const res = await fetch("/api/bookings/next-id");
    if (res.ok) {
      const data = await res.json();
      document.getElementById("editId").textContent = data.next_id;
    } else {
      document.getElementById("editId").textContent = "—";
    }
  } catch (_) {
    document.getElementById("editId").textContent = "—";
  }
  document.getElementById("editName").value = "";
  document.getElementById("editPhone").value = "";
  document.getElementById("editService").value = "";
  document.getElementById("editDate").value = "";
  document.getElementById("editTime").value = "";
  document.getElementById("editComment").value = "";
  document.getElementById("editPrice").value = "";
  document.getElementById("editStatus").value = "pending";
  const isEmployee = currentUser?.role === "employee";
  document.getElementById("priceRow").style.display = "none";
  document.getElementById("editStatus").onchange = function () {
    document.getElementById("priceRow").style.display =
      !isEmployee && this.value === "completed" ? "block" : "none";
  };
  await loadEmployeesFilter();
  document.getElementById("editEmployee").value = "";
  populateTimeSelect("editTime");
  document.getElementById("editModal").style.display = "flex";
  initDatePicker();
}

async function saveEdit() {
  const empSel = document.getElementById("editEmployee");
  const empId = empSel.value;
  const empName = empId ? empSel.options[empSel.selectedIndex]?.text : "";
  const date = document.getElementById("editDate").value;
  const time = document.getElementById("editTime").value;

  // Проверка пересечения по времени
  if (date && time && empId) {
    const conflict = await checkTimeConflict(date, time, empId, currentEditId);
    if (conflict) {
      showToast(
        `⛔ На ${date} в ${time} у сотрудника уже есть запись #${conflict.id}`,
        "error",
      );
      return;
    }
  }

  const data = {
    client_name: document.getElementById("editName").value,
    client_phone: document.getElementById("editPhone").value,
    service: document.getElementById("editService").value,
    booking_date: date,
    booking_time: time,
    status: document.getElementById("editStatus").value,
    comment: document.getElementById("editComment").value,
    assigned_employee_id: empId ? parseInt(empId) : null,
    assigned_employee_name: empName || "",
  };
  if (data.status === "completed")
    data.price = document.getElementById("editPrice").value;
  try {
    const url = currentEditId
      ? `/api/bookings/${currentEditId}`
      : "/api/bookings";
    const method = currentEditId ? "PUT" : "POST";
    const res = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.error || "Ошибка сохранения");
    }
    closeEditModal();
    showToast(
      currentEditId
        ? "Запись #" + currentEditId + " сохранена"
        : "Запись создана",
      "success",
    );
    await loadAll();
  } catch (e) {
    showToast(e.message || "Ошибка при сохранении", "error");
    console.error(e);
  }
}

// ─── Поиск в кеше записей ───
function getCachedBooking(id) {
  return _bookingsCache.find((b) => b.id === id) || null;
}

async function loadBookingForAction(id) {
  const booking = await getBookingById(id);
  if (booking) {
    // Сохраняем в кеш
    const existingIdx = _bookingsCache.findIndex((b) => b.id === id);
    if (existingIdx >= 0) _bookingsCache[existingIdx] = booking;
    else _bookingsCache.push(booking);
    // Переоткрываем модалку
    openActionModal(id, "confirm");
    return;
  }
  // Если не нашли — открываем обычную модалку подтверждения без проверки
  actionBookingId = id;
  actionType = "confirm";
  document.getElementById("actionModalTitle").textContent =
    "Подтвердить заявку";
  document.getElementById("actionModalText").textContent =
    `Заявка #${id} будет подтверждена и перейдёт в активные записи.`;
  document.getElementById("actionConfirmBtn").textContent = "✓ Подтвердить";
  document.getElementById("actionConfirmBtn").className = "btn btn-success";
  document.getElementById("actionPriceRow").style.display = "none";
  document.getElementById("actionEmployeeRow").style.display = "none";
  document.getElementById("actionModal").style.display = "flex";
}

// ─── Модалка действий (подтвердить / выполнить / отменить) ───
let actionBookingId = null;
let actionType = null; // 'confirm' | 'complete' | 'cancel'

function openActionModal(id, type) {
  actionBookingId = id;
  actionType = type;
  let title, text, btnLabel, btnClass;

  // Скрываем поле выбора сотрудника по умолчанию
  document.getElementById("actionEmployeeRow").style.display = "none";

  if (type === "confirm") {
    // Проверяем, назначен ли сотрудник
    const booking = getCachedBooking(id);
    if (booking && !booking.assigned_employee_id) {
      title = "Назначить мастера";
      text = "Чтобы взять заявку в работу, укажи мастера:";
      btnLabel = "✓ Подтвердить и назначить";
      btnClass = "btn btn-success";
      // Показываем выпадающий список сотрудников
      document.getElementById("actionEmployeeRow").style.display = "block";
      // Загружаем сотрудников
      loadEmployeesFilterForAction();
    } else if (booking && booking.assigned_employee_id) {
      title = "Подтвердить заявку";
      text = `Заявка #${id} будет подтверждена и перейдёт в активные записи.`;
      btnLabel = "✓ Подтвердить";
      btnClass = "btn btn-success";
    } else {
      // Если запись ещё не загружена — загружаем и переоткрываем
      loadBookingForAction(id);
      return;
    }
  } else if (type === "complete") {
    title = "Выполнить запись";
    text = `Запись #${id} будет отмечена как выполненная и попадёт в историю услуг.`;
    btnLabel = "✓ Выполнить";
    btnClass = "btn btn-success";
  } else {
    title = "Отменить запись";
    text = `Запись #${id} будет отменена и попадёт в историю услуг.`;
    btnLabel = "✕ Отменить";
    btnClass = "btn btn-danger";
  }
  document.getElementById("actionModalTitle").textContent = title;
  document.getElementById("actionModalText").textContent = text;
  // Поле цены доступно и админу, и сотруднику при завершении
  const showPrice = type === "complete";
  document.getElementById("actionPriceRow").style.display = showPrice
    ? "block"
    : "none";
  document.getElementById("actionPrice").value = "";
  document.getElementById("actionConfirmBtn").textContent = btnLabel;
  document.getElementById("actionConfirmBtn").className = btnClass;
  document.getElementById("actionModal").style.display = "flex";
}

function closeActionModal() {
  document.getElementById("actionModal").style.display = "none";
  actionBookingId = null;
  actionType = null;
}

async function confirmAction() {
  if (!actionBookingId || !actionType) return;
  const id = actionBookingId;
  const type = actionType;
  let data;
  if (type === "confirm") {
    // Проверяем, нужно ли назначить сотрудника
    const empEl = document.getElementById("actionEmployee");
    const empSel = empEl ? empEl.value : "";
    const empNameEl = empEl ? empEl.options[empEl.selectedIndex]?.text : "";
    const empName =
      empSel && empNameEl !== "— Выбери мастера —" ? empNameEl : "";

    // Если форма с выбором сотрудника видна — значит сотрудник не назначен
    const empRow = document.getElementById("actionEmployeeRow");
    if (empRow && empRow.style.display !== "none") {
      if (!empSel) {
        showToast("⛔ Выберите мастера из списка", "error");
        return;
      }
      data = {
        status: "active",
        assigned_employee_id: parseInt(empSel),
        assigned_employee_name: empName,
      };
    } else {
      data = { status: "active" };
    }
  } else if (type === "complete") {
    data = { status: "completed" };
    const price = document.getElementById("actionPrice").value.trim();
    if (price) data.price = price;
  } else {
    data = { status: "cancelled" };
  }
  try {
    const res = await fetch(`/api/bookings/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (!res.ok) throw new Error("Ошибка");
    closeActionModal();
    const msgs = {
      confirm: "подтверждена",
      complete: "выполнена",
      cancel: "отменена",
    };
    showToast(`Запись #${id} ${msgs[type]}`, "success");
    await loadAll();
  } catch (e) {
    showToast("Ошибка при сохранении", "error");
    console.error(e);
  }
}

async function deleteBooking(id) {
  openActionModal(id, "cancel");
}

// ─── Toast уведомления ───
function showToast(message, type = "success") {
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.classList.add("show"), 10);
  setTimeout(() => {
    toast.classList.remove("show");
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

// ─── Модалка сотрудника ───
async function openUserModal(id) {
  currentUserId = id || null;
  document.getElementById("userModalTitle").textContent = id
    ? "Редактировать сотрудника"
    : "Добавить сотрудника";
  [
    "userDisplayName",
    "userPosition",
    "userUsername",
    "userPassword",
    "userTelegramId",
  ].forEach((id) => (document.getElementById(id).value = ""));
  document.getElementById("userNotifyEnabled").checked = false;
  document.getElementById("userRole").value = "employee";

  // Показываем/скрываем notifyRow в зависимости от telegram_id
  const notifyRow = document.getElementById("notifyRow");
  document
    .getElementById("userTelegramId")
    .addEventListener("input", function () {
      notifyRow.style.display = this.value.trim() ? "block" : "none";
    });
  notifyRow.style.display = "none";

  if (id) {
    try {
      const users = await (await fetch("/api/users")).json();
      const u = users.find((x) => x.id === id);
      if (u) {
        document.getElementById("userDisplayName").value = u.display_name;
        document.getElementById("userPosition").value = u.position || "";
        document.getElementById("userUsername").value = u.username;
        document.getElementById("userRole").value = u.role;
        document.getElementById("userTelegramId").value = u.telegram_id || "";
        if (u.telegram_id) {
          document.getElementById("userNotifyEnabled").checked =
            u.notify_enabled === 1;
          notifyRow.style.display = "block";
        } else {
          document.getElementById("userNotifyEnabled").checked = false;
          notifyRow.style.display = "none";
        }
      }
    } catch (e) {
      console.error(e);
    }
  }

  // Валидация Telegram ID при вводе (только цифры)
  const tgInput = document.getElementById("userTelegramId");
  tgInput.addEventListener("input", function () {
    this.value = this.value.replace(/\D/g, "");
  });
  document.getElementById("userModal").style.display = "flex";
}

function closeUserModal() {
  document.getElementById("userModal").style.display = "none";
  currentUserId = null;
}

async function saveUser() {
  const telegramId = document.getElementById("userTelegramId").value.trim();
  const notifyEnabled = telegramId
    ? document.getElementById("userNotifyEnabled").checked
      ? 1
      : 0
    : 0;
  const data = {
    display_name: document.getElementById("userDisplayName").value.trim(),
    position: document.getElementById("userPosition").value.trim(),
    username: document.getElementById("userUsername").value.trim(),
    password: document.getElementById("userPassword").value,
    role: document.getElementById("userRole").value,
    telegram_id: telegramId,
    notify_enabled: notifyEnabled,
  };
  if (!data.display_name || !data.username) {
    alert("Заполните ФИО и логин");
    return;
  }
  if (!currentUserId && !data.password) {
    alert("Введите пароль");
    return;
  }
  try {
    let res;
    if (currentUserId) {
      if (!data.password) delete data.password;
      res = await fetch(`/api/users/${currentUserId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
    } else {
      res = await fetch("/api/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
    }
    if (!res.ok) throw new Error((await res.json()).error || "Ошибка");
    closeUserModal();
    await loadUsers();
  } catch (e) {
    alert(e.message);
    console.error(e);
  }
}

async function deleteUser(id) {
  if (!confirm("Удалить пользователя #" + id + "?")) return;
  try {
    const res = await fetch(`/api/users/${id}`, { method: "DELETE" });
    if (!res.ok) throw new Error((await res.json()).error || "Ошибка");
    await loadUsers();
  } catch (e) {
    alert(e.message);
    console.error(e);
  }
}

// ─── Профиль ───
async function loadProfile() {
  try {
    const res = await fetch("/api/users");
    let me = null;
    if (res.status === 200) {
      const users = await res.json();
      me = users.find((u) => u.id === currentUser?.id);
    }
    if (!me) {
      // Не админ — получаем через /api/auth/me
      const authRes = await fetch("/api/auth/me");
      if (authRes.status === 200) me = await authRes.json();
    }
    if (!me) return;

    document.getElementById("profileDisplayName").value = me.display_name || "";
    document.getElementById("profilePosition").value = me.position || "";
    document.getElementById("profileUsername").value = me.username || "";
    document.getElementById("profileRole").value =
      me.role === "admin" ? "Администратор" : "Сотрудник";
    document.getElementById("profilePassword").value = "";
    document.getElementById("profileAvatarLetter").textContent =
      (me.display_name || me.username || "—")[0].toUpperCase();

    // Обновляем кнопку истории
    const historyBtn = document.getElementById("profileHistoryBtn");
    if (historyBtn) {
      const displayName = me.display_name || me.username || "";
      historyBtn.onclick = function () {
        navigateTo("history", { master: displayName });
      };
    }
  } catch (e) {
    console.error(e);
  }
}

async function saveProfile() {
  const data = {
    display_name: document.getElementById("profileDisplayName").value.trim(),
    position: document.getElementById("profilePosition").value.trim(),
  };
  const password = document.getElementById("profilePassword").value;
  if (password) data.password = password;

  if (!data.display_name) {
    showToast("Заполните ФИО", "error");
    return;
  }

  try {
    const res = await fetch(`/api/users/${currentUser.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (!res.ok) throw new Error("Ошибка сохранения");
    showToast("Профиль обновлён", "success");
    // Обновляем имя в сайдбаре
    document.getElementById("sidebarUserName").textContent = data.display_name;
  } catch (e) {
    showToast(e.message, "error");
  }
}

// ─── Скрываем браузерные уведомления на мобильных ───
(function hideBrowserNotifyOnMobile() {
  if (window.innerWidth <= 768) {
    const card = document.getElementById("browserNotifyCard");
    if (card) card.style.display = "none";
  }
})();

// ─── Навигация с фильтрами (для кликабельных карточек) ───
function navigateTo(tab, filters) {
  // Переключаемся на нужную вкладку
  const links = document.querySelectorAll(`.sidebar-link[data-tab="${tab}"]`);

  // Для профиля — нет sidebar-ссылки, ищем tab напрямую
  if (tab === "profile") {
    document
      .querySelectorAll(".sidebar-link")
      .forEach((l) => l.classList.remove("active"));
    document
      .querySelectorAll(".tab-content")
      .forEach((t) => t.classList.remove("active"));
    const tabEl = document.getElementById("tab-profile");
    if (tabEl) {
      tabEl.classList.add("active");
      loadProfile();
    }
    return;
  }

  if (links.length) links[0].click();

  // Применяем фильтры
  if (tab === "bookings") {
    if (filters.status) {
      const sel = document.getElementById("statusFilter");
      if (sel) sel.value = filters.status;
    }
    loadBookings();
  } else if (tab === "history") {
    if (filters.status) {
      const sel = document.getElementById("historyStatusFilter");
      if (sel) sel.value = filters.status;
    }
    loadHistory();
  } else if (tab === "schedule") {
    document.getElementById("scheduleEmployee").value = "";
    document.getElementById("scheduleDate").value = "";
    loadEmployeesFilter().then(() => loadSchedule());
  }
}

// ─── Утилиты ───
function esc(str) {
  if (str == null) return "\u2014";
  const d = document.createElement("div");
  d.textContent = str;
  return d.innerHTML || "\u2014";
}
function statusBadge(status) {
  return (
    {
      pending: '<span class="badge badge-pending">Заявка</span>',
      active: '<span class="badge badge-active">Активна</span>',
      completed: '<span class="badge badge-completed">Выполнена</span>',
      cancelled: '<span class="badge badge-cancelled">Отменена</span>',
    }[status] || status
  );
}

// Преобразование ДД.ММ.ГГГГ → ГГГГ-ММ-ДД для корректной сортировки дат
function sortDate(d) {
  if (!d || typeof d !== "string") return d || "";
  const p = d.split(".");
  if (p.length === 3 && p[2].length === 4) return `${p[2]}-${p[1]}-${p[0]}`;
  return d;
}

// ─── Кастомный календарь для поля даты ───
let editDatePickerState = { start: null, end: null };

function initDatePicker() {
  const el = document.getElementById("editDate");
  if (!el) return;
  if (el.dataset.pickerInited) return;
  // Если в поле уже есть дата — восстанавливаем состояние
  if (el.value) {
    const parts = el.value.split(".");
    if (parts.length === 3 && parts[2].length === 4) {
      const d = new Date(
        parseInt(parts[2]),
        parseInt(parts[1]) - 1,
        parseInt(parts[0]),
      );
      editDatePickerState.start = d;
    }
  }
  createDatePicker("editDate", editDatePickerState, {
    rangeMode: false,
    disableFuture: false,
  });
}

function destroyDatePicker() {
  const el = document.getElementById("editDate");
  if (el) {
    el.dataset.pickerInited = "";
    // Удаляем связанный календарь из DOM
    const existingCalendar = el
      .closest(".form-row")
      ?.parentElement?.querySelector(".history-calendar");
    if (existingCalendar) existingCalendar.remove();
    // Или ищем в body
    const bodyCalendar = document.querySelector(".history-calendar");
    if (bodyCalendar && bodyCalendar.style.display !== "none") {
      bodyCalendar.remove();
    }
  }
  editDatePickerState = { start: null, end: null };
}

// ─── Проверка пересечения по времени и сотруднику ───
async function checkTimeConflict(date, time, employeeId, excludeId) {
  if (!date || !time || !employeeId) return null;
  try {
    const res = await fetch(`/api/bookings?status=all`);
    if (!res.ok) return null;
    const bookings = await res.json();
    const conflict = bookings.find((b) => {
      if (excludeId && b.id === excludeId) return false;
      if (b.booking_date !== date) return false;
      if (b.booking_time !== time) return false;
      if (String(b.assigned_employee_id) !== String(employeeId)) return false;
      return b.status === "pending" || b.status === "active";
    });
    return conflict || null;
  } catch (e) {
    return null;
  }
}

// ─── Получить запись по ID ───
async function getBookingById(id) {
  try {
    const res = await fetch(`/api/bookings?status=all`);
    if (!res.ok) return null;
    const bookings = await res.json();
    return bookings.find((b) => b.id === id) || null;
  } catch (e) {
    return null;
  }
}

// ─── Инициализация ───
document.addEventListener("DOMContentLoaded", async () => {
  const u = await checkAuth();
  if (u) {
    await loadAll();
    loadSchedule();
    createDatePicker("historyDateRange", historyRange, {
      rangeMode: true,
      onChange: loadHistory,
    });
    createDatePicker("scheduleDate", scheduleDateRange, {
      rangeMode: true,
      onChange: loadSchedule,
    });
  }
});
