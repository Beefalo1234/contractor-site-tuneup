// Contractor Site Tune-Up — landing page lead form.
// POSTs to the relay (see config.js); falls back to a pre-filled email
// if the relay is unreachable, so leads are never silently lost.
(function () {
  "use strict";

  var form = document.getElementById("lead-form");
  var success = document.getElementById("form-success");
  var note = document.getElementById("form-note");
  var mailtoLink = document.getElementById("mailto-fallback");

  function buildMailto(data) {
    var subject = encodeURIComponent("Audit request — " + (data.company || data.name));
    var body = encodeURIComponent(
      "Hi — I'd like to reserve the $49 launch audit.\n\n" +
      "Name: " + data.name + "\n" +
      "Business: " + (data.company || "-") + "\n" +
      "Website: " + (data.website || "-") + "\n" +
      "Trade: " + (data.trade || "-") + "\n" +
      "Phone: " + (data.phone || "-") + "\n" +
      "Intent: " + data.intent + "\n\n" +
      "(Sent from the Contractor Site Tune-Up landing page.)"
    );
    return "mailto:graydon3.14@gmail.com?subject=" + subject + "&body=" + body;
  }

  function postLead(data) {
    var body = JSON.stringify(data);
    var i = 0;
    function attempt() {
      if (i >= RELAY_URLS.length) return Promise.reject(new Error("all relays down"));
      var url = RELAY_URLS[i++] + "/api/lead";
      return fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body
      }).then(function (res) {
        if (!res.ok) throw new Error("relay error " + res.status);
        return res.json();
      }).catch(function () { return attempt(); });
    }
    return attempt();
  }

  function showSuccess(mailtoHref) {
    form.classList.add("hidden");
    success.classList.remove("hidden");
    mailtoLink.href = mailtoHref;
    success.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();

    // Honeypot: humans never fill this; bots do.
    if (form.website2 && form.website2.value) return;

    var data = {
      name: form.name.value.trim(),
      company: form.company.value.trim(),
      website: form.website.value.trim(),
      trade: form.trade.value,
      email: form.email.value.trim(),
      phone: form.phone.value.trim(),
      intent: (document.querySelector('input[name="intent"]:checked') || {}).value || "audit",
      source: "landing-page"
    };

    if (!data.name || !data.email || !data.website) {
      note.textContent = "Please fill in your name, email, and website.";
      note.style.color = "#c0392b";
      return;
    }

    note.textContent = "Sending…";
    note.style.color = "";

    var mailtoHref = buildMailto(data);

    postLead(data).then(function (res) {
      showSuccess(mailtoHref);
    }).catch(function () {
      // Relay unreachable — never lose the lead: open a pre-filled email.
      window.location.href = mailtoHref;
      showSuccess(mailtoHref);
    });
  });
})();
