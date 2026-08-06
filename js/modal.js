document.addEventListener("DOMContentLoaded", () => {
  const bookingModal = document.getElementById("bookingModal");
  const bookingBtn = document.getElementById("bookingBtn");
  const closeBtns = document.querySelectorAll(".close-btn");
  const serviceInput = document.getElementById("serviceInput");
  const serviceToggle = document.querySelector(".service-select-toggle");
  const serviceOptions = document.querySelector(".service-options");
  const bookingForm = document.getElementById("bookingForm");
  const masterSelect = document.getElementById("clientMaster");
  const masterToggle = document.getElementById("masterSelectToggle");
  const masterOptions = document.getElementById("masterSelectOptions");
  const clientComment = document.getElementById("clientComment");
  const dateInput = document.getElementById("clientDate");
  const timeSelect = document.getElementById("clientTime");
  const timeToggle = document.getElementById("timeSelectToggle");
  const timeFieldGroup = document.getElementById("timeFieldGroup");
  const timeSelectWrap = document.getElementById("timeSelectWrap");
  const timeOptions = document.getElementById("timeSelectOptions");

  var ycServices = [],
    ycCategories = [];
  window.ycServiceMap = {};
  window.ycStaffMap = {};
  var ycServiceStaffIds = {};

  var selectedService = null;
  var selectedStaffId = null;

  var pendingSlotPrefill = null;

  function isoToDisplayDate(iso) {
    var parts = String(iso).split("-");
    if (parts.length !== 3) return iso;
    return parts[2] + "." + parts[1] + "." + parts[0];
  }

  function getApiBase() {
    if (
      window.location.protocol === "file:" ||
      window.location.port === "5500" ||
      window.location.port === "3000"
    )
      return "http://localhost:5000";
    return "";
  }

  function setFieldEnabled(groupId, enabled) {
    var group = document.getElementById(groupId);
    if (!group) return;
    group.style.opacity = enabled ? "1" : "0.4";
    group.style.pointerEvents = enabled ? "auto" : "none";
    group
      .querySelectorAll("input, select, button, textarea")
      .forEach(function (el) {
        el.disabled = !enabled;
      });
  }

  function resetForm() {
    pendingSlotPrefill = null;
    selectedService = null;
    selectedStaffId = null;
    serviceInput.value = "";
    serviceToggle.textContent = "Выберите услугу";
    masterSelect.value = "";
    masterToggle.textContent = "Любой мастер";
    masterToggle.classList.remove("has-value");
    if (masterOptions) masterOptions.style.display = "none";
    dateInput.value = "";
    timeSelect.innerHTML =
      '<option value="" selected disabled>Выберите время</option>';
    timeSelect.disabled = true;
    timeToggle.textContent = "Выберите время";
    timeToggle.classList.remove("has-value");
    timeOptions.innerHTML = "";
    timeOptions.style.display = "none";
    setFieldEnabled("step-service", true);
    setFieldEnabled("step-master", false);
    setFieldEnabled("step-date", false);
    setFieldEnabled("step-time", false);
    setFieldEnabled("step-personal", false);
  }

  function onServiceSelected(svc) {
    selectedService = svc;
    selectedStaffId = null;
    serviceInput.value = svc.title;
    serviceToggle.textContent = svc.title;
    serviceToggle.classList.add("has-value");
    masterSelect.value = "";
    masterToggle.textContent = "Любой мастер";
    masterToggle.classList.remove("has-value");
    populateMasters(svc.id);
    setFieldEnabled("step-master", true);
    setFieldEnabled("step-date", false);
    setFieldEnabled("step-time", false);
    setFieldEnabled("step-personal", false);
    dateInput.value = "";
    timeSelect.innerHTML =
      '<option value="" selected disabled>Выберите время</option>';
    timeOptions.innerHTML = "";
    timeOptions.style.display = "none";

    if (pendingSlotPrefill) {
      var prefill = pendingSlotPrefill;
      var staffIds = (ycServiceStaffIds[svc.id] || []).map(String);
      if (staffIds.indexOf(prefill.staffId) !== -1) {
        onMasterSelected(prefill.staffId);
        dateInput.value = isoToDisplayDate(prefill.date);
        window.tryLoadTimes().then(function () {
          var btn =
            timeOptions &&
            timeOptions.querySelector('[data-time="' + prefill.time + '"]');
          if (btn) btn.click();
        });

        pendingSlotPrefill = null;
      }
    }
  }

  function onMasterSelected(staffId) {
    selectedStaffId = String(staffId);
    var opt = masterSelect.querySelector('option[value="' + staffId + '"]');
    masterSelect.value = staffId;
    masterToggle.textContent = opt ? opt.textContent : "Мастер";
    masterToggle.classList.add("has-value");
    setFieldEnabled("step-date", true);
    setFieldEnabled("step-time", false);
    setFieldEnabled("step-personal", false);
    dateInput.value = "";
    timeSelect.innerHTML =
      '<option value="" selected disabled>Выберите время</option>';
    timeOptions.innerHTML = "";
    timeOptions.style.display = "none";
  }

  function populateServices(filterStaffId) {
    if (
      !serviceOptions ||
      !serviceInput ||
      !ycCategories ||
      ycCategories.length === 0
    )
      return;
    serviceOptions.innerHTML = "";
    serviceInput.innerHTML =
      '<option value="" selected disabled>Выберите услугу</option>';
    ycCategories.forEach(function (cat) {
      var catName = cat.title || "Услуги";
      var catId = cat.id;
      var matched = ycServices.filter(function (svc) {
        var svcCatId = svc.category_id || (svc.category && svc.category.id);
        if (svcCatId !== catId) return false;
        if (filterStaffId) {
          var ids = (ycServiceStaffIds[svc.id] || []).map(String);
          if (ids.indexOf(String(filterStaffId)) === -1) return false;
        }
        return true;
      });
      if (matched.length === 0) return;
      var group = document.createElement("optgroup");
      group.label = catName;
      serviceInput.appendChild(group);
      var header = document.createElement("div");
      header.className = "service-option-group";
      header.textContent = catName;
      serviceOptions.appendChild(header);
      matched.forEach(function (svc) {
        var opt = document.createElement("option");
        opt.value = svc.title;
        opt.textContent = svc.title;
        group.appendChild(opt);
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "service-option";
        btn.textContent = svc.title;
        btn.dataset.value = svc.title;
        btn.setAttribute("role", "option");
        btn.addEventListener("click", function () {
          onServiceSelected(svc);
          serviceOptions
            .closest(".service-select")
            ?.classList.remove("is-open");
        });
        serviceOptions.appendChild(btn);
      });
    });
  }

  function populateMasters(filterServiceId) {
    if (!masterOptions) return;
    masterOptions.innerHTML = "";
    masterSelect.innerHTML = '<option value="">Любой мастер</option>';
    var list = [];
    if (filterServiceId) {
      var ids = ycServiceStaffIds[filterServiceId] || [];
      ids.forEach(function (sid) {
        var s = window.ycStaffMap[sid];
        if (s) list.push(s);
      });
    } else {
      list = Object.values(window.ycStaffMap);
    }
    list.forEach(function (staff) {
      var name = staff.name || "Мастер";
      var opt = document.createElement("option");
      opt.value = staff.id;
      opt.textContent = name;
      masterSelect.appendChild(opt);
      var customOpt = document.createElement("button");
      customOpt.type = "button";
      customOpt.className = "master-option";
      customOpt.textContent = name;
      customOpt.dataset.value = staff.id;
      customOpt.setAttribute("role", "option");
      customOpt.addEventListener("click", function () {
        onMasterSelected(staff.id);
        masterOptions.style.display = "none";
        masterToggle.closest(".master-select")?.classList.remove("is-open");
      });
      masterOptions.appendChild(customOpt);
    });
  }

  serviceToggle?.addEventListener("click", function () {
    serviceOptions.closest(".service-select")?.classList.toggle("is-open");
  });

  if (masterOptions) {
    masterOptions.style.display = "none";
    document.body.appendChild(masterOptions);
  }

  masterToggle?.addEventListener("click", function (e) {
    e.stopPropagation();
    if (masterSelect.disabled || !masterOptions) return;
    var willOpen = masterOptions.style.display !== "flex";
    masterToggle
      .closest(".master-select")
      ?.classList.toggle("is-open", willOpen);
    if (willOpen) {
      var r = masterToggle.getBoundingClientRect();
      masterOptions.style.position = "fixed";
      masterOptions.style.left = r.left + "px";
      masterOptions.style.width = Math.max(r.width, 220) + "px";
      masterOptions.style.top = r.bottom + 6 + "px";
      masterOptions.style.maxHeight = "260px";
      masterOptions.style.zIndex = "100005";
      masterOptions.style.display = "flex";
      masterOptions.style.flexDirection = "column";
    } else {
      masterOptions.style.display = "none";
    }
  });

  var masterReposition = function () {
    repositionDropdown(masterOptions, masterToggle);
  };
  document.querySelectorAll(".modal-content").forEach(function (el) {
    el.addEventListener("scroll", masterReposition);
  });
  window.addEventListener("resize", masterReposition);

  document.addEventListener("click", function (e) {
    if (
      serviceOptions &&
      !serviceOptions.closest(".service-select")?.contains(e.target)
    )
      serviceOptions.closest(".service-select")?.classList.remove("is-open");
    if (
      masterOptions &&
      masterOptions.style.display !== "none" &&
      !masterOptions.contains(e.target) &&
      e.target !== masterToggle
    ) {
      masterOptions.style.display = "none";
      masterToggle.closest(".master-select")?.classList.remove("is-open");
    }
  });

  async function loadYClientsData() {
    var base = getApiBase();
    try {
      var catResp = await fetch(base + "/api/yclients/categories");
      if (catResp.ok) ycCategories = await catResp.json();
      var svcResp = await fetch(base + "/api/yclients/services");
      if (svcResp.ok) {
        ycServices = await svcResp.json();
        window.ycServiceMap = {};
        ycServiceStaffIds = {};
        ycServices.forEach(function (s) {
          window.ycServiceMap[s.title] = s;
          ycServiceStaffIds[s.id] = (s.staff || []).map(function (st) {
            return st.id;
          });
          (s.staff || []).forEach(function (st) {
            if (!window.ycStaffMap[st.id]) {
              window.ycStaffMap[st.id] = {
                id: st.id,
                name: st.name || "Мастер",
                specialization: st.specialization || "",
              };
            }
          });
        });
      }
      populateServices(pendingSlotPrefill ? pendingSlotPrefill.staffId : null);
      populateMasters();
      setFieldEnabled("step-service", true);
      setFieldEnabled("step-master", false);
      setFieldEnabled("step-date", false);
      setFieldEnabled("step-time", false);
      setFieldEnabled("step-personal", false);
    } catch (e) {
      console.warn("YClients data load failed:", e);
    }
  }

  window.tryLoadTimes = async function () {
    if (
      !selectedService ||
      !selectedStaffId ||
      !dateInput ||
      !dateInput.value
    ) {
      return;
    }
    timeSelect.innerHTML = '<option value="" disabled>Загрузка...</option>';
    timeSelect.disabled = true;
    setFieldEnabled("step-time", false);
    var API = getApiBase();
    var url =
      API +
      "/api/yclients/available-times?service_id=" +
      encodeURIComponent(selectedService.id) +
      "&staff_id=" +
      encodeURIComponent(selectedStaffId) +
      "&date=" +
      encodeURIComponent(dateInput.value);
    try {
      var res = await fetch(url);
      if (!res.ok) throw new Error("HTTP " + res.status);
      var slots = await res.json();
      if (
        Array.isArray(slots) &&
        slots.length > 0 &&
        typeof slots[0] === "string"
      )
        slots = slots.map(function (t) {
          return { time: t, available: true };
        });
      if (!Array.isArray(slots)) slots = [];
      timeSelect.innerHTML =
        '<option value="" selected disabled>Выберите время</option>';
      var hasAvail = false;
      slots.forEach(function (sl) {
        if (!sl || !sl.time || sl.available === false) return;
        var opt = document.createElement("option");
        opt.value = sl.time;
        opt.textContent = sl.time;
        hasAvail = true;
        timeSelect.appendChild(opt);
      });
      if (!hasAvail) {
        var e = document.createElement("option");
        e.value = "";
        e.disabled = true;
        e.textContent = "Нет свободных слотов";
        e.selected = true;
        timeSelect.appendChild(e);
      }

      buildTimeButtons(
        slots.filter(function (sl) {
          return sl && sl.time && sl.available !== false;
        }),
      );
      timeSelect.disabled = false;

      setFieldEnabled("step-time", true);
      if (hasAvail) {
        setFieldEnabled("step-personal", true);
      }
    } catch (err) {
      console.error("loadAvailableTimes error:", err);
      timeSelect.innerHTML =
        '<option value="" selected disabled>Ошибка загрузки</option>';
      timeSelect.disabled = false;

      setFieldEnabled("step-time", true);
    }
  };

  window.loadAvailableTimes = window.tryLoadTimes;

  if (timeOptions) {
    timeOptions.style.display = "none";
    document.body.appendChild(timeOptions);
  }

  if (dateInput) {
    var calendar = document.createElement("div");
    calendar.className = "simple-calendar";
    document.body.appendChild(calendar);
    var viewDate = new Date();
    var selectedDate = null;
    var monthNames = [
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
    var dayNames = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
    function pad(n) {
      return n < 10 ? "0" + n : "" + n;
    }

    var ycAvailableDatesCache = {};
    function availableDatesCacheKey(serviceId, staffId, year, month) {
      return serviceId + "|" + (staffId || "") + "|" + year + "-" + month;
    }

    async function fetchAvailableDatesForMonth(
      serviceId,
      staffId,
      year,
      month,
    ) {
      var key = availableDatesCacheKey(serviceId, staffId, year, month);
      if (Object.prototype.hasOwnProperty.call(ycAvailableDatesCache, key)) {
        return ycAvailableDatesCache[key];
      }
      var API = getApiBase();
      var url =
        API +
        "/api/yclients/available-dates?service_id=" +
        encodeURIComponent(serviceId) +
        "&year=" +
        year +
        "&month=" +
        (month + 1); // JS-месяцы с 0, бэкенд ждёт с 1
      if (staffId) url += "&staff_id=" + encodeURIComponent(staffId);
      var result = null;
      try {
        var res = await fetch(url);
        if (res.ok) {
          var data = await res.json();
          if (Array.isArray(data)) {
            result = {};
            data.forEach(function (d) {
              result[String(d)] = true;
            });
          }
        }
      } catch (e) {
        console.warn("available-dates fetch failed:", e);
      }
      ycAvailableDatesCache[key] = result;
      return result;
    }

    function ensureCalendarParent() {
      var isMobile = window.innerWidth <= 600;
      var modalContent = dateInput.closest(".modal-content");
      if (isMobile && modalContent && calendar.parentNode !== modalContent) {
        modalContent.appendChild(calendar);
      } else if (!isMobile && calendar.parentNode !== document.body) {
        document.body.appendChild(calendar);
      }
    }

    function positionCalendar() {
      ensureCalendarParent();
      var isMobile = window.innerWidth <= 600;
      if (isMobile) {
        var modalContent = dateInput.closest(".modal-content");
        if (modalContent) {
          var inputRect = dateInput.getBoundingClientRect();
          var contentRect = modalContent.getBoundingClientRect();
          calendar.style.top =
            inputRect.top -
            contentRect.top +
            modalContent.scrollTop +
            inputRect.height +
            8 +
            "px";
          calendar.style.left = "0";
          calendar.style.transform = "none";
          calendar.style.width = "100%";
          calendar.style.maxWidth = "100%";
        }
      } else {
        var r = dateInput.getBoundingClientRect();
        calendar.style.top = r.bottom + 8 + "px";
        calendar.style.left = "50%";
        calendar.style.transform = "translateX(-50%)";
        calendar.style.width = "280px";
        calendar.style.maxWidth = "calc(100vw - 24px)";
      }
    }

    function buildCalendarHtml(y, m, availableDates) {
      var sw = new Date(y, m, 1).getDay() - 1;
      if (sw < 0) sw = 6;
      var dim = new Date(y, m + 1, 0).getDate();
      var td = new Date();
      td.setHours(0, 0, 0, 0);
      var html =
        '<div class="sc-header"><button type="button" class="sc-nav sc-prev">&#10094;</button><span class="sc-title">' +
        monthNames[m] +
        " " +
        y +
        '</span><button type="button" class="sc-nav sc-next">&#10095;</button></div>';
      html += '<div class="sc-weekdays">';
      for (var i = 0; i < 7; i++) html += "<span>" + dayNames[i] + "</span>";
      html += '</div><div class="sc-days">';
      for (var i = 0; i < sw; i++)
        html += '<span class="sc-day sc-empty"></span>';
      for (var d = 1; d <= dim; d++) {
        var dt = new Date(y, m, d);
        var iso = y + "-" + pad(m + 1) + "-" + pad(d);
        var cls = "sc-day";
        var unavailable = availableDates !== null && !availableDates[iso];
        if (dt < td || unavailable) cls += " sc-disabled";
        if (selectedDate && selectedDate.getTime() === dt.getTime())
          cls += " sc-selected";
        html +=
          '<span class="' + cls + '" data-day="' + d + '">' + d + "</span>";
      }
      html += "</div>";
      return html;
    }

    function buildCalendarLoaderHtml() {
      return (
        '<div class="sc-loader"><div class="sc-loader-spinner"></div>' +
        '<div class="sc-loader-text">Ищем окошко для вас…</div></div>'
      );
    }

    var calendarRenderToken = 0;

    function attachCalendarHandlers(y, m) {
      calendar
        .querySelector(".sc-prev")
        ?.addEventListener("click", function (e) {
          e.stopPropagation();
          viewDate.setMonth(viewDate.getMonth() - 1);
          renderCalendar();
        });
      calendar
        .querySelector(".sc-next")
        ?.addEventListener("click", function (e) {
          e.stopPropagation();
          viewDate.setMonth(viewDate.getMonth() + 1);
          renderCalendar();
        });
      calendar
        .querySelectorAll(".sc-day:not(.sc-empty):not(.sc-disabled)")
        .forEach(function (el) {
          el.addEventListener("click", function () {
            var day = parseInt(this.dataset.day, 10);
            selectedDate = new Date(y, m, day);
            dateInput.value = pad(day) + "." + pad(m + 1) + "." + y;
            calendar.classList.remove("active");
            window.tryLoadTimes();
          });
        });
    }

    async function renderCalendar() {
      var y = viewDate.getFullYear(),
        m = viewDate.getMonth();
      var myToken = ++calendarRenderToken;

      if (!selectedService || !selectedStaffId) {
        calendar.innerHTML = buildCalendarHtml(y, m, null);
        attachCalendarHandlers(y, m);
        positionCalendar();
        return;
      }

      calendar.innerHTML = buildCalendarLoaderHtml();
      positionCalendar();

      var availableDates = await fetchAvailableDatesForMonth(
        selectedService.id,
        selectedStaffId,
        y,
        m,
      );
      if (myToken !== calendarRenderToken) return; // уже неактуально
      calendar.innerHTML = buildCalendarHtml(y, m, availableDates);
      attachCalendarHandlers(y, m);
      positionCalendar();
    }
    dateInput.addEventListener("click", function () {
      if (!dateInput.disabled) {
        calendar.classList.add("active");
        renderCalendar();
      }
    });
    dateInput.addEventListener("focus", function () {
      if (!dateInput.disabled) {
        calendar.classList.add("active");
        renderCalendar();
      }
    });
    document.addEventListener("click", function (e) {
      if (!calendar.contains(e.target) && e.target !== dateInput)
        calendar.classList.remove("active");
    });

    window.addEventListener("resize", function () {
      if (calendar.classList.contains("active")) renderCalendar();
    });
  }

  function buildTimeButtons(slots) {
    if (!timeOptions) return;
    timeOptions.innerHTML = "";
    if (!slots || slots.length === 0) {
      var msg = document.createElement("div");
      msg.className = "time-select-option disabled";
      msg.textContent = "Нет свободных слотов";
      timeOptions.appendChild(msg);
      return;
    }
    slots.forEach(function (sl) {
      if (!sl || !sl.time) return;
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "time-select-option";
      btn.textContent = sl.time;
      btn.dataset.time = sl.time;
      btn.addEventListener("click", function () {
        timeSelect.value = this.dataset.time;
        timeToggle.textContent = this.dataset.time;
        timeToggle.classList.add("has-value");
        timeSelectWrap.classList.remove("is-open");
        timeOptions.style.display = "none";
      });
      timeOptions.appendChild(btn);
    });
  }

  function repositionDropdown(dropdown, toggleEl) {
    if (!dropdown || dropdown.style.display === "none") return;
    var r = toggleEl.getBoundingClientRect();
    dropdown.style.top = r.bottom + 6 + "px";
    dropdown.style.left = r.left + "px";
  }

  timeToggle?.addEventListener("click", function (e) {
    e.stopPropagation();
    if (!timeSelect.disabled && timeOptions) {
      timeOptions.style.display =
        timeOptions.style.display === "flex" ? "none" : "flex";
      if (timeOptions.style.display === "flex") {
        var r = timeToggle.getBoundingClientRect();
        timeOptions.style.position = "fixed";
        timeOptions.style.left = r.left + "px";
        timeOptions.style.top = r.bottom + 6 + "px";
        timeOptions.style.width = r.width + "px";
        timeOptions.style.maxHeight = "220px";
        timeOptions.style.zIndex = "100000";
      }
    }
  });
  document.addEventListener("click", function (e) {
    if (
      timeOptions &&
      !timeOptions.contains(e.target) &&
      e.target !== timeToggle
    )
      timeOptions.style.display = "none";
  });

  var timeReposition = function () {
    repositionDropdown(timeOptions, timeToggle);
  };
  document.querySelectorAll(".modal-content").forEach(function (el) {
    el.addEventListener("scroll", timeReposition);
  });
  window.addEventListener("resize", timeReposition);

  bookingBtn?.addEventListener("click", function () {
    openModal(bookingModal);
  });

  document.querySelectorAll(".service-btn").forEach(function (btn) {
    btn.addEventListener("click", function (e) {
      var t = e.target.dataset.service;
      openModal(bookingModal);
      loadYClientsData().then(function () {
        var s = window.ycServiceMap[t];
        if (s) onServiceSelected(s);
      });
    });
  });

  closeBtns.forEach(function (btn) {
    btn.addEventListener("click", function () {
      closeModal(btn.closest(".modal"));
    });
  });
  document.querySelectorAll(".modal").forEach(function (modal) {
    modal.addEventListener("click", function (e) {
      if (e.target === modal) closeModal(modal);
    });
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape")
      document.querySelectorAll(".modal.active").forEach(function (m) {
        closeModal(m);
      });
  });

  window.openModal = function (modal) {
    modal.classList.add("active");
    document.body.style.overflow = "hidden";
    modal.querySelector(".modal-content").style.animation =
      "slideUp 0.4s ease forwards";
    if (modal === bookingModal) {
      resetForm();
      loadYClientsData();
    }
  };

  window.openBookingFromSlot = function (staffId, isoDate, time) {
    if (!bookingModal) return;
    window.openModal(bookingModal);
    pendingSlotPrefill = {
      staffId: String(staffId),
      date: isoDate,
      time: time,
    };
  };

  window.closeModal = function (modal) {
    modal.classList.remove("active");
    document.body.style.overflow = "";
    resetForm();
  };

  var formError = document.createElement("div");
  formError.className = "form-error-msg";
  var submitBtnEl = bookingForm?.querySelector(".submit-btn");
  if (submitBtnEl && submitBtnEl.parentNode) {
    submitBtnEl.parentNode.insertBefore(formError, submitBtnEl);
  } else if (bookingForm) {
    bookingForm.appendChild(formError);
  }
  function showFormError(m) {
    formError.textContent = m;
    formError.classList.add("visible");
  }
  function hideFormError() {
    formError.classList.remove("visible");
    formError.textContent = "";
  }

  bookingForm?.addEventListener("submit", function (e) {
    e.preventDefault();
    submitBooking();
  });

  async function submitBooking() {
    hideFormError();
    var name = document.getElementById("clientName")?.value.trim();
    var phone = document.getElementById("clientPhone")?.value.trim();
    var date = dateInput?.value.trim();
    var time = timeSelect?.value;
    var comment = clientComment?.value.trim() || "";

    if (!selectedService || !selectedStaffId) {
      showFormError("Выберите услугу и мастера");
      return;
    }

    if (!name || name.length < 2 || !/^[a-zA-Zа-яА-ЯёЁ\s\-']+$/.test(name)) {
      showFormError("Введите корректное имя (только буквы, минимум 2 символа)");
      return;
    }

    var phoneClean = phone.replace(/[^\d]/g, "");
    if (phoneClean.length < 10) {
      showFormError("Введите корректный номер телефона (минимум 10 цифр)");
      return;
    }

    if (!name || !phone || !date || !time) {
      showFormError("Заполните все поля");
      return;
    }

    var btn = bookingForm.querySelector(".submit-btn");
    var orig = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Отправка...";
    try {
      var API = getApiBase();
      var payload = {
        client_name: name,
        client_phone: phone,
        service: selectedService.title,
        booking_date: date,
        booking_time: time,
        comment: comment,
        yclients_service_id: selectedService.id,
        yclients_staff_id: selectedStaffId,
        assigned_employee_name:
          (window.ycStaffMap[selectedStaffId] &&
            window.ycStaffMap[selectedStaffId].name) ||
          "Мастер",
      };
      var res = await fetch(API + "/api/bookings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        var errData = await res.json().catch(function () {
          return {};
        });
        if (res.status === 409) {
          showFormError("⛔ Это время занято");
          return;
        }
        throw new Error(errData.error || "Ошибка");
      }

      var resData = await res.json().catch(function () {
        return {};
      });
      var clientId = resData.client_id;

      var overlay = document.createElement("div");
      overlay.className = "success-overlay";
      overlay.innerHTML =
        '<div class="success-modal">' +
        '<div class="success-checkmark"><svg viewBox="0 0 52 52"><circle cx="26" cy="26" r="25" fill="none" stroke="#8e9165" stroke-width="2"/><path fill="none" stroke="#8e9165" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" d="M14 27l7 7 16-16"/></svg></div>' +
        '<h2 class="success-title">Заявка отправлена!</h2>' +
        '<p class="success-text">Мы свяжемся с вами<br/>в ближайшее время</p>' +
        // [ЗАКОММЕНТИРОВАНО] Кнопки уведомлений — отключено
        // (clientId && clientId !== -1 ? (
        //   '<p class="notify-prompt">Получать уведомления о записи?</p>' +
        //   '<div class="notify-buttons">' +
        //     '<button type="button" class="notify-btn notify-btn--telegram" data-provider="telegram">Подключить Telegram</button>' +
        //     '<button type="button" class="notify-btn notify-btn--max" data-provider="max">Подключить MAX</button>' +
        //   '</div>'
        // ) : '') +
        '<button class="success-btn" onclick="this.closest(\'.success-overlay\').remove()">Хорошо</button>' +
        "</div>";
      document.body.appendChild(overlay);
      requestAnimationFrame(function () {
        overlay.classList.add("active");
        requestAnimationFrame(function () {
          overlay.querySelector(".success-modal")?.classList.add("active");
        });
      });

      if (clientId && clientId !== -1) {
        overlay.querySelectorAll(".notify-btn").forEach(function (b) {
          b.addEventListener("click", async function () {
            var provider = b.dataset.provider;
            b.disabled = true;
            var origText = b.textContent;
            b.textContent = "Открываем...";
            try {
              var API = getApiBase();
              var r = await fetch(API + "/api/notifications/link-token", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  client_id: clientId,
                  provider: provider,
                }),
              });
              var d = await r.json();
              if (d.deeplink) window.open(d.deeplink, "_blank");
            } catch (e) {
              console.error("Не удалось получить ссылку для " + provider, e);
            } finally {
              b.disabled = false;
              b.textContent = origText;
            }
          });
        });
      }

      setTimeout(function () {
        overlay.classList.remove("active");
        setTimeout(function () {
          overlay.remove();
        }, 500);
      }, 5000);

      bookingForm.reset();
      closeModal(bookingModal);
    } catch (err) {
      showFormError("Ошибка: " + err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = orig;
    }
  }
});

const urlParams = new URLSearchParams(window.location.search);
if (urlParams.get("open_booking") === "1") {
  const checkAndOpen = setInterval(() => {
    if (window.ycStaffMap && Object.keys(window.ycStaffMap).length > 0) {
      clearInterval(checkAndOpen);
      if (!bookingModal.classList.contains("active")) {
        window.openModal(bookingModal);
      }
    }
  }, 100);

  setTimeout(() => {
    clearInterval(checkAndOpen);
    if (!bookingModal.classList.contains("active")) {
      window.openModal(bookingModal);
    }
  }, 5000);
}
